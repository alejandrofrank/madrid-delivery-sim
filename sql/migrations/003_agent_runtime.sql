-- Session identity is the boundary; SET ROLE cannot change session_user.
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='lab_inventory_executor') THEN
  CREATE ROLE lab_inventory_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
 END IF;
END $$;
ALTER ROLE lab_inventory_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO lab_inventory_executor;
ALTER TABLE public.events ADD COLUMN target_store text;
CREATE TABLE public.agent_bindings (
 login_role name PRIMARY KEY, run_id uuid NOT NULL REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 store text NOT NULL, agent_id text NOT NULL, definition jsonb NOT NULL, definition_hash text NOT NULL,
 UNIQUE(run_id,store)
);
CREATE TABLE public.agent_run_budgets (
 run_id uuid PRIMARY KEY REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 events_limit integer NOT NULL DEFAULT 500 CHECK(events_limit>0),
 tools_limit integer NOT NULL DEFAULT 2000 CHECK(tools_limit>0),
 events_reserved integer NOT NULL DEFAULT 0 CHECK(events_reserved>=0 AND events_reserved<=events_limit),
 tools_reserved integer NOT NULL DEFAULT 0 CHECK(tools_reserved>=0 AND tools_reserved<=tools_limit)
);
CREATE TABLE public.agent_budgets (
 run_id uuid NOT NULL REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE, store text NOT NULL,
 events_limit integer NOT NULL CHECK(events_limit>0), tools_limit integer NOT NULL CHECK(tools_limit>0),
 step_slots integer NOT NULL CHECK(step_slots>0), memory_entries_limit integer NOT NULL CHECK(memory_entries_limit>0),
 memory_bytes_limit integer NOT NULL CHECK(memory_bytes_limit>0),
 events_reserved integer NOT NULL DEFAULT 0 CHECK(events_reserved>=0 AND events_reserved<=events_limit),
 tools_reserved integer NOT NULL DEFAULT 0 CHECK(tools_reserved>=0 AND tools_reserved<=tools_limit), PRIMARY KEY(run_id,store)
);
CREATE TABLE public.agent_event_budgets (
 run_id uuid NOT NULL REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE, store text NOT NULL,
 event_id bigint NOT NULL REFERENCES public.events(id) ON DELETE CASCADE, attempt integer NOT NULL CHECK(attempt>0),
 slots integer NOT NULL CHECK(slots>0), observed_tools integer NOT NULL DEFAULT 0 CHECK(observed_tools>=0 AND observed_tools<=slots),
 PRIMARY KEY(event_id,attempt)
);
CREATE TABLE public.agent_memories (
 run_id uuid NOT NULL REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE, store text NOT NULL,
 key text NOT NULL CHECK(length(key) BETWEEN 1 AND 100),
 body jsonb NOT NULL CHECK(octet_length(body::text)<=2048), observed_sim integer NOT NULL,
 expires_sim integer NOT NULL CHECK(expires_sim>observed_sim),
 event_id bigint NOT NULL REFERENCES public.events(id) ON DELETE CASCADE, PRIMARY KEY(run_id,store,key)
);
CREATE FUNCTION public.agent_scope() RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT jsonb_build_object('run_id',run_id,'store',store,'agent_id',agent_id,'definition_hash',definition_hash)
 FROM public.agent_bindings WHERE login_role=session_user
$$;
CREATE FUNCTION public.agent_definition() RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT definition FROM public.agent_bindings WHERE login_role=session_user
$$;
CREATE FUNCTION public.agent_clock() RETURNS integer LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT r.sim_time FROM public.runs r JOIN public.agent_bindings b ON b.run_id=r.id WHERE b.login_role=session_user
$$;
CREATE FUNCTION public.agent_catalogue() RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT coalesce(jsonb_agg(p.product - 'url' ORDER BY p.product->>'source',p.product->>'listing_id'),'[]'::jsonb)
 FROM public.agent_bindings b JOIN public.lab_worlds w ON w.run_id=b.run_id
 CROSS JOIN LATERAL jsonb_array_elements(w.catalogue->'products') p(product)
 WHERE b.login_role=session_user AND EXISTS (SELECT 1 FROM public.lab_stock s WHERE s.run_id=b.run_id AND s.store=b.store
 AND s.sku=(p.product->>'source')||':'||(p.product->>'listing_id'))
$$;
CREATE FUNCTION public.agent_queue_room(capacity integer) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT EXISTS(SELECT 1 FROM public.agent_bindings b WHERE b.login_role=session_user AND
 (SELECT count(*) FROM public.events e WHERE e.run_id=b.run_id AND e.state IN ('ready','leased'))<greatest(1,least(coalesce(capacity,1),10000)))
$$;
CREATE FUNCTION public.agent_reserve_budget(eventid bigint, token uuid, attempt integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; rb public.agent_run_budgets%ROWTYPE; ab public.agent_budgets%ROWTYPE; ticket public.agent_event_budgets%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND THEN RETURN jsonb_build_object('status','denied'); END IF;
 -- Lock the event before aggregate/agent budgets, serializing repeated tickets.
 PERFORM 1 FROM public.events e WHERE e.id=eventid AND e.run_id=b.run_id AND e.target_store=b.store
 AND e.state='leased' AND e.lease_token=token AND e.attempts=attempt AND e.lease_until>clock_timestamp()
 AND e.topic IN ('basket.requested','reservation.expire','shipment.delayed','shipment.received','inventory.decided') FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('status','denied'); END IF;
 SELECT * INTO ticket FROM public.agent_event_budgets t WHERE t.event_id=eventid AND t.attempt=agent_reserve_budget.attempt;
 IF FOUND THEN RETURN jsonb_build_object('status','reserved','slots',ticket.slots); END IF;
 SELECT * INTO rb FROM public.agent_run_budgets WHERE run_id=b.run_id FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('status','denied'); END IF;
 SELECT * INTO ab FROM public.agent_budgets WHERE run_id=b.run_id AND store=b.store FOR UPDATE;
 IF NOT FOUND THEN RETURN jsonb_build_object('status','denied'); END IF;
 IF rb.events_reserved>=rb.events_limit OR ab.events_reserved>=ab.events_limit
 OR ab.step_slots>rb.tools_limit-rb.tools_reserved OR ab.step_slots>ab.tools_limit-ab.tools_reserved THEN
 RETURN jsonb_build_object('status','denied'); END IF;
 UPDATE public.agent_run_budgets SET events_reserved=events_reserved+1,tools_reserved=tools_reserved+ab.step_slots WHERE run_id=b.run_id;
 UPDATE public.agent_budgets SET events_reserved=events_reserved+1,tools_reserved=tools_reserved+ab.step_slots WHERE run_id=b.run_id AND store=b.store;
 INSERT INTO public.agent_event_budgets(run_id,store,event_id,attempt,slots) VALUES(b.run_id,b.store,eventid,attempt,ab.step_slots);
 RETURN jsonb_build_object('status','reserved','slots',ab.step_slots);
END $$;
CREATE FUNCTION public.agent_memory_capacity() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE ab public.agent_budgets%ROWTYPE; entries bigint; bytes bigint;
BEGIN
 IF session_user<>current_user AND (
 public.agent_scope() IS NULL OR NEW.run_id<>(public.agent_scope()->>'run_id')::uuid
 OR NEW.store<>public.agent_scope()->>'store') THEN
 RAISE EXCEPTION 'memory write exceeds agent scope' USING ERRCODE='42501'; END IF;
 SELECT * INTO ab FROM public.agent_budgets WHERE run_id=NEW.run_id AND store=NEW.store FOR UPDATE;
 IF NOT FOUND THEN RETURN NEW; END IF;
 SELECT count(*),coalesce(sum(octet_length(body::text)),0) INTO entries,bytes FROM public.agent_memories
 WHERE run_id=NEW.run_id AND store=NEW.store AND key<>NEW.key;
 IF entries+1>ab.memory_entries_limit OR bytes+octet_length(NEW.body::text)>ab.memory_bytes_limit THEN
 RAISE EXCEPTION 'agent memory capacity exceeded' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER agent_memory_capacity BEFORE INSERT OR UPDATE ON public.agent_memories FOR EACH ROW EXECUTE FUNCTION public.agent_memory_capacity();

DO $$ DECLARE tbl text; BEGIN
 FOREACH tbl IN ARRAY ARRAY['lab_stock','lab_baskets','lab_shipments','lab_movements','agent_memories','agent_budgets','agent_event_budgets'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',tbl);
  EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',tbl);
  EXECUTE format('CREATE POLICY agent_scope_policy ON public.%I TO lab_inventory_executor USING (run_id=(public.agent_scope()->>''run_id'')::uuid AND store=public.agent_scope()->>''store'') WITH CHECK (run_id=(public.agent_scope()->>''run_id'')::uuid AND store=public.agent_scope()->>''store'')',tbl);
 END LOOP;
END $$;
ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.events FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_events_read ON public.events FOR SELECT TO lab_inventory_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store'
 AND topic IN ('basket.requested','reservation.expire','shipment.delayed','shipment.received','inventory.decided'));
CREATE POLICY agent_events_update ON public.events FOR UPDATE TO lab_inventory_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store'
 AND topic IN ('basket.requested','reservation.expire','shipment.delayed','shipment.received','inventory.decided')) WITH CHECK (
 run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store'
 AND topic IN ('basket.requested','reservation.expire','shipment.delayed','shipment.received','inventory.decided'));
CREATE POLICY agent_events_insert ON public.events FOR INSERT TO lab_inventory_executor WITH CHECK (
 run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store'
 AND producer='inventory' AND topic IN ('inventory.decided','shipment.received'));
ALTER TABLE public.decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY agent_decisions ON public.decisions TO lab_inventory_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND agent=public.agent_scope()->>'agent_id') WITH CHECK (
 run_id=(public.agent_scope()->>'run_id')::uuid AND agent=public.agent_scope()->>'agent_id');
GRANT SELECT,INSERT,UPDATE ON public.lab_stock,public.lab_baskets,public.lab_shipments,public.lab_movements TO lab_inventory_executor;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.agent_memories TO lab_inventory_executor;
GRANT SELECT ON public.agent_budgets,public.agent_event_budgets TO lab_inventory_executor;
GRANT UPDATE(observed_tools) ON public.agent_event_budgets TO lab_inventory_executor;
GRANT SELECT,INSERT,UPDATE ON public.events TO lab_inventory_executor;
GRANT SELECT,INSERT ON public.decisions TO lab_inventory_executor;
GRANT USAGE ON SEQUENCE public.events_id_seq,public.decisions_id_seq TO lab_inventory_executor;
REVOKE ALL ON FUNCTION public.agent_scope(),public.agent_definition(),public.agent_clock(),public.agent_catalogue(),public.agent_queue_room(integer),public.agent_reserve_budget(bigint,uuid,integer),public.agent_memory_capacity() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agent_scope(),public.agent_definition(),public.agent_clock(),public.agent_catalogue(),public.agent_queue_room(integer),public.agent_reserve_budget(bigint,uuid,integer) TO lab_inventory_executor;

