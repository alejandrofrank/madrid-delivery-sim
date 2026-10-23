-- Store namespaces are role-specific; inventory retains its physical store key.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='lab_fulfillment_executor') THEN
 CREATE ROLE lab_fulfillment_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='lab_dispatch_executor') THEN
 CREATE ROLE lab_dispatch_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
 END IF;
END $$;
CREATE TABLE public.lab_fulfillments (
 run_id uuid REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 basket text NOT NULL, store text NOT NULL, customer_node integer NOT NULL,
 status text NOT NULL DEFAULT 'awaiting_reservation' CHECK(status IN ('awaiting_reservation','picked')),
 picked_sim integer, PRIMARY KEY(run_id,basket)
);
CREATE TABLE public.lab_delivery_jobs (
 run_id uuid REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 basket text NOT NULL, store text NOT NULL, pickup_node integer NOT NULL, customer_node integer NOT NULL,
 status text NOT NULL DEFAULT 'ready' CHECK(status IN ('ready','assigned','in_transit','arrived','delivered')),
 courier text, route jsonb, travel_seconds integer, depart_sim integer, pickup_sim integer, arrive_sim integer,
 PRIMARY KEY(run_id,basket)
);
CREATE TABLE public.lab_fleet (
 run_id uuid REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 id text NOT NULL, node integer NOT NULL, busy_basket text, PRIMARY KEY(run_id,id)
);
-- Only trusted world/operator code accesses these tables directly. Agents use projections and commands.
REVOKE ALL ON public.lab_fulfillments,public.lab_delivery_jobs,public.lab_fleet FROM PUBLIC;
CREATE OR REPLACE FUNCTION public.agent_reserve_budget(eventid bigint, token uuid, attempt integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; rb public.agent_run_budgets%ROWTYPE; ab public.agent_budgets%ROWTYPE; ticket public.agent_event_budgets%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND THEN RETURN jsonb_build_object('status','denied'); END IF;
 -- Lock the event before aggregate/agent budgets, serializing repeated tickets.
 PERFORM 1 FROM public.events e WHERE e.id=eventid AND e.run_id=b.run_id AND e.target_store=b.store
 AND e.state='leased' AND e.lease_token=token AND e.attempts=attempt AND e.lease_until>clock_timestamp()
 AND b.definition->'accepts' ? e.topic FOR UPDATE;
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

CREATE FUNCTION public.agent_destination(topic text, payload jsonb) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF NOT (b.definition->'emits' ? topic) THEN RETURN NULL; END IF;
 IF topic='basket.reserved' THEN
  IF b.definition->>'role'<>'inventory' OR NOT EXISTS(SELECT 1 FROM public.lab_fulfillments f
    WHERE f.run_id=b.run_id AND f.basket=payload->>'basket' AND f.store=b.store) THEN
   RETURN NULL; END IF;
  RETURN 'fulfillment:'||b.store;
 ELSIF topic='basket.ready' THEN
  IF b.definition->>'role'<>'fulfillment' OR NOT EXISTS(SELECT 1 FROM public.lab_fulfillments f
   WHERE f.run_id=b.run_id AND f.basket=payload->>'basket' AND 'fulfillment:'||f.store=b.store AND f.status='picked') THEN
   RETURN NULL; END IF;
  RETURN 'dispatcher:fleet';
 ELSE RETURN b.store;
 END IF;
END $$;
CREATE FUNCTION public.workflow_context(basketid text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; result jsonb;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role'='fulfillment' THEN
  SELECT jsonb_build_object('basket',f.basket,'sku',k.sku,'quantity',k.quantity,
   'reservation_status',k.status,'expires_sim',k.expires_sim,'status',f.status)
   INTO result FROM public.lab_fulfillments f JOIN public.lab_baskets k ON k.run_id=f.run_id AND k.id=f.basket
   WHERE f.run_id=b.run_id AND f.basket=basketid AND 'fulfillment:'||f.store=b.store;
 ELSIF b.definition->>'role'='dispatcher' THEN
  SELECT jsonb_build_object('job',to_jsonb(j)-'run_id'-'store','fleet',
   (SELECT coalesce(jsonb_agg(to_jsonb(c)-'run_id'),'[]'::jsonb) FROM public.lab_fleet c WHERE c.run_id=b.run_id),
   'roads',jsonb_build_object('nodes',w.city->'nodes','edges',w.city->'edges')) INTO result
   FROM public.lab_delivery_jobs j JOIN public.lab_worlds w ON w.run_id=j.run_id
   WHERE j.run_id=b.run_id AND j.basket=basketid;
 ELSE RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 IF result IS NULL THEN RAISE EXCEPTION 'Unknown scoped basket' USING ERRCODE='42501'; END IF;
 RETURN result;
END $$;
CREATE FUNCTION public.fulfillment_pick(basketid text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; f public.lab_fulfillments%ROWTYPE;
 k public.lab_baskets%ROWTYPE; sim integer; pickup integer;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'fulfillment' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 SELECT * INTO f FROM public.lab_fulfillments WHERE run_id=b.run_id AND basket=basketid AND 'fulfillment:'||store=b.store FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown scoped basket' USING ERRCODE='42501'; END IF;
 IF f.status='picked' THEN RETURN jsonb_build_object('basket',basketid,'status','picked'); END IF;
 SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
 SELECT * INTO k FROM public.lab_baskets WHERE run_id=b.run_id AND id=basketid AND store=f.store;
 IF NOT FOUND OR k.status<>'reserved' OR k.expires_sim<=sim THEN RAISE EXCEPTION 'Live reservation required'; END IF;
 PERFORM 1 FROM public.lab_stock WHERE run_id=b.run_id AND store=k.store AND sku=k.sku FOR UPDATE;
 SELECT * INTO k FROM public.lab_baskets WHERE run_id=b.run_id AND id=basketid FOR UPDATE;
 IF k.status<>'reserved' THEN RAISE EXCEPTION 'Reservation changed'; END IF;
 UPDATE public.lab_stock SET on_hand=on_hand-k.quantity,reserved=reserved-k.quantity,version=version+1
 WHERE run_id=b.run_id AND store=k.store AND sku=k.sku AND reserved>=k.quantity;
 IF NOT FOUND THEN RAISE EXCEPTION 'Stock not reserved'; END IF;
 UPDATE public.lab_baskets SET status='picked' WHERE run_id=b.run_id AND id=basketid;
 INSERT INTO public.lab_movements VALUES(b.run_id,'pick:'||basketid,k.store,k.sku,sim,'picked',-k.quantity,-k.quantity);
 UPDATE public.lab_fulfillments SET status='picked',picked_sim=sim WHERE run_id=b.run_id AND basket=basketid;
 SELECT (s->>'node')::integer INTO pickup FROM public.lab_worlds w CROSS JOIN LATERAL jsonb_array_elements(w.city->'stores') s
 WHERE w.run_id=b.run_id AND s->>'id'=f.store;
 INSERT INTO public.lab_delivery_jobs(run_id,basket,store,pickup_node,customer_node) VALUES(b.run_id,basketid,f.store,pickup,f.customer_node);
 RETURN jsonb_build_object('basket',basketid,'status','picked');
END $$;
ALTER TABLE public.lab_baskets DROP CONSTRAINT lab_baskets_status_check;
ALTER TABLE public.lab_baskets ADD CHECK(status IN ('reserved','rejected','expired','cancelled','picked','delivered'));
CREATE FUNCTION public.dispatch_assign(basketid text, courierid text, path jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; j public.lab_delivery_jobs%ROWTYPE; c public.lab_fleet%ROWTYPE;
 sim integer; n integer; previous integer; firstnode integer; total integer:=0; pickup_seconds integer;
 edge_seconds integer; world jsonb;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'dispatcher' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 SELECT * INTO j FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=basketid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown basket' USING ERRCODE='42501'; END IF;
 IF j.status<>'ready' THEN RETURN jsonb_build_object('basket',basketid,'status',j.status); END IF;
 SELECT * INTO c FROM public.lab_fleet WHERE run_id=b.run_id AND id=courierid FOR UPDATE;
 IF NOT FOUND OR c.busy_basket IS NOT NULL THEN RAISE EXCEPTION 'Available courier required'; END IF;
 IF path IS NULL OR jsonb_typeof(path)<>'array' OR jsonb_array_length(path) NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'Invalid route'; END IF;
 SELECT city INTO world FROM public.lab_worlds WHERE run_id=b.run_id;
 FOR n IN SELECT value::integer FROM jsonb_array_elements_text(path) LOOP
  IF previous IS NULL THEN firstnode:=n;
  ELSE
   SELECT (e->>'travel_seconds')::integer INTO edge_seconds FROM jsonb_array_elements(world->'edges') e
    WHERE (e->>'from')::integer=previous AND (e->>'to')::integer=n;
   IF edge_seconds IS NULL THEN RAISE EXCEPTION 'Disconnected route'; END IF;
   total:=total+edge_seconds;
  END IF;
  IF n=j.pickup_node AND pickup_seconds IS NULL THEN pickup_seconds:=total; END IF;
  previous:=n;
 END LOOP;
 IF firstnode<>c.node OR previous<>j.customer_node OR pickup_seconds IS NULL THEN RAISE EXCEPTION 'Route endpoints or pickup invalid'; END IF;
 SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
 UPDATE public.lab_delivery_jobs SET status='assigned',courier=courierid,route=path,travel_seconds=total,
 depart_sim=sim,pickup_sim=sim+pickup_seconds,arrive_sim=sim+total WHERE run_id=b.run_id AND basket=basketid;
 UPDATE public.lab_fleet SET busy_basket=basketid WHERE run_id=b.run_id AND id=courierid;
 RETURN jsonb_build_object('basket',basketid,'status','assigned','courier',courierid,'route',path,'arrive_sim',sim+total);
END $$;
CREATE FUNCTION public.dispatch_complete(basketid text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; j public.lab_delivery_jobs%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'dispatcher' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 SELECT * INTO j FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=basketid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown basket' USING ERRCODE='42501'; END IF;
 IF j.status='delivered' THEN RETURN jsonb_build_object('basket',basketid,'status','delivered'); END IF;
 IF j.status<>'arrived' THEN RAISE EXCEPTION 'World arrival required'; END IF;
 UPDATE public.lab_delivery_jobs SET status='delivered' WHERE run_id=b.run_id AND basket=basketid;
 UPDATE public.lab_baskets SET status='delivered' WHERE run_id=b.run_id AND id=basketid AND status='picked';
 UPDATE public.lab_fleet SET busy_basket=NULL WHERE run_id=b.run_id AND id=j.courier AND busy_basket=basketid;
 RETURN jsonb_build_object('basket',basketid,'status','delivered','courier',j.courier);
END $$;
GRANT USAGE ON SCHEMA public TO lab_fulfillment_executor,lab_dispatch_executor;
GRANT SELECT ON public.agent_budgets,public.agent_event_budgets TO lab_fulfillment_executor,lab_dispatch_executor;
GRANT UPDATE(observed_tools) ON public.agent_event_budgets TO lab_fulfillment_executor,lab_dispatch_executor;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.agent_memories TO lab_fulfillment_executor,lab_dispatch_executor;
GRANT SELECT,INSERT,UPDATE ON public.events TO lab_fulfillment_executor,lab_dispatch_executor;
GRANT SELECT,INSERT ON public.decisions TO lab_fulfillment_executor,lab_dispatch_executor;
GRANT USAGE ON SEQUENCE public.events_id_seq,public.decisions_id_seq TO lab_fulfillment_executor,lab_dispatch_executor;
DO $$ DECLARE tbl text; BEGIN
 FOREACH tbl IN ARRAY ARRAY['agent_memories','agent_budgets','agent_event_budgets'] LOOP
  EXECUTE format('CREATE POLICY workflow_scope ON public.%I TO lab_fulfillment_executor,lab_dispatch_executor USING (run_id=(public.agent_scope()->>''run_id'')::uuid AND store=public.agent_scope()->>''store'') WITH CHECK (run_id=(public.agent_scope()->>''run_id'')::uuid AND store=public.agent_scope()->>''store'')',tbl);
 END LOOP;
END $$;
CREATE POLICY workflow_events_read ON public.events FOR SELECT TO lab_fulfillment_executor,lab_dispatch_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND (
 (target_store=public.agent_scope()->>'store' AND (public.agent_definition()->'accepts' ? topic)) OR
 (producer=public.agent_definition()->>'role' AND (public.agent_definition()->'emits' ? topic)
 AND target_store=public.agent_destination(topic,payload))));
CREATE POLICY workflow_events_update ON public.events FOR UPDATE TO lab_fulfillment_executor,lab_dispatch_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store'
 AND (public.agent_definition()->'accepts' ? topic)) WITH CHECK (
 run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store'
 AND (public.agent_definition()->'accepts' ? topic));
CREATE POLICY workflow_events_insert ON public.events FOR INSERT TO lab_fulfillment_executor,lab_dispatch_executor WITH CHECK (
 run_id=(public.agent_scope()->>'run_id')::uuid AND producer=public.agent_definition()->>'role'
 AND (public.agent_definition()->'emits' ? topic) AND target_store=public.agent_destination(topic,payload));
CREATE POLICY workflow_decisions ON public.decisions TO lab_fulfillment_executor,lab_dispatch_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND agent=public.agent_scope()->>'agent_id') WITH CHECK (
 run_id=(public.agent_scope()->>'run_id')::uuid AND agent=public.agent_scope()->>'agent_id');
CREATE POLICY inventory_handoff_read ON public.events FOR SELECT TO lab_inventory_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND topic='basket.reserved' AND producer='inventory'
 AND target_store='fulfillment:'||(public.agent_scope()->>'store'));
CREATE POLICY inventory_handoff_insert ON public.events FOR INSERT TO lab_inventory_executor WITH CHECK (
 run_id=(public.agent_scope()->>'run_id')::uuid AND topic='basket.reserved' AND producer='inventory'
 AND target_store=public.agent_destination(topic,payload));
REVOKE ALL ON FUNCTION public.agent_destination(text,jsonb),public.workflow_context(text),public.fulfillment_pick(text),public.dispatch_assign(text,text,jsonb),public.dispatch_complete(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agent_destination(text,jsonb) TO lab_inventory_executor,lab_fulfillment_executor,lab_dispatch_executor;
GRANT EXECUTE ON FUNCTION public.agent_scope(),public.agent_definition(),public.agent_clock(),public.agent_queue_room(integer),public.agent_reserve_budget(bigint,uuid,integer),public.workflow_context(text) TO lab_fulfillment_executor,lab_dispatch_executor;
GRANT EXECUTE ON FUNCTION public.fulfillment_pick(text) TO lab_fulfillment_executor;
GRANT EXECUTE ON FUNCTION public.dispatch_assign(text,text,jsonb),public.dispatch_complete(text) TO lab_dispatch_executor;
