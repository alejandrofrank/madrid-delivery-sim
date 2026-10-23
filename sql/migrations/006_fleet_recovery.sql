-- Fleet expansion is opt-in; existing delivery runs retain migration 005 behavior.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='lab_courier_executor') THEN
  CREATE ROLE lab_courier_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='lab_judge_executor') THEN
  CREATE ROLE lab_judge_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
 END IF;
END $$;
CREATE TABLE public.lab_fleet_scenarios(run_id uuid PRIMARY KEY REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE, mode text NOT NULL DEFAULT 'expansion');
ALTER TABLE public.lab_fulfillments ADD COLUMN deadline_sim integer NOT NULL DEFAULT 20000;
ALTER TABLE public.lab_fleet ADD COLUMN status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','offline'));
ALTER TABLE public.lab_delivery_jobs ADD COLUMN attempt integer NOT NULL DEFAULT 0,
 ADD COLUMN deadline_sim integer NOT NULL DEFAULT 20000, ADD COLUMN retry_limit integer NOT NULL DEFAULT 2,
 ADD COLUMN accepted boolean NOT NULL DEFAULT true, ADD COLUMN parcel_node integer,
 ADD COLUMN collected boolean NOT NULL DEFAULT false, ADD COLUMN route_durations jsonb,
 ADD COLUMN traffic_delay_seconds integer NOT NULL DEFAULT 0;
ALTER TABLE public.lab_delivery_jobs DROP CONSTRAINT lab_delivery_jobs_status_check;
ALTER TABLE public.lab_delivery_jobs ADD CHECK(status IN ('ready','assigned','in_transit','arrived','delivered','deferred','awaiting_review','abandoned'));
CREATE TABLE public.lab_delivery_attempts(
 run_id uuid REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,basket text,attempt integer,
 courier text NOT NULL,status text NOT NULL,route jsonb NOT NULL,edge_durations jsonb NOT NULL,
 depart_sim integer NOT NULL,pickup_sim integer NOT NULL,arrive_sim integer NOT NULL,
 accepted boolean NOT NULL DEFAULT false,last_node integer,PRIMARY KEY(run_id,basket,attempt));
CREATE TABLE public.lab_incidents(run_id uuid REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,sim_time integer NOT NULL,kind text NOT NULL,
 basket text,courier text,detail jsonb NOT NULL DEFAULT '{}'::jsonb);
CREATE TABLE public.lab_briefs(run_id uuid REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 basket text,attempt integer,courier text NOT NULL,body jsonb NOT NULL,created_sim integer NOT NULL,PRIMARY KEY(run_id,basket,attempt));
CREATE TABLE public.lab_retry_reviews(run_id uuid REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 basket text,attempt integer,verdict text NOT NULL CHECK(verdict IN ('approved','denied')),reason text NOT NULL,
 estimated_seconds integer,remaining_seconds integer NOT NULL,PRIMARY KEY(run_id,basket,attempt));
REVOKE ALL ON public.lab_fleet_scenarios,public.lab_delivery_attempts,public.lab_incidents,public.lab_briefs,public.lab_retry_reviews FROM PUBLIC;

-- Private route validator: metrics are recomputed from authoritative bike roads.
CREATE FUNCTION public.fleet_route_metrics(runid uuid,path jsonb,startnode integer,pickup integer,customer integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE world jsonb;n integer;prev integer;firstn integer;seconds integer;total integer:=0;pickseconds integer;durations jsonb:='[]';
BEGIN
 IF path IS NULL OR jsonb_typeof(path)<>'array' THEN RAISE EXCEPTION 'Invalid route'; END IF;
 IF jsonb_array_length(path) NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'Invalid route length'; END IF;
 SELECT city INTO world FROM public.lab_worlds WHERE run_id=runid;
 FOR n IN SELECT value::integer FROM jsonb_array_elements_text(path) LOOP
  IF prev IS NULL THEN firstn:=n; ELSE
   SELECT (e->>'travel_seconds')::integer*2 INTO seconds FROM jsonb_array_elements(world->'edges') e
   WHERE (e->>'from')::integer=prev AND (e->>'to')::integer=n AND e->'modes' ? 'bike';
   IF seconds IS NULL OR seconds<=0 THEN RAISE EXCEPTION 'Invalid bike edge'; END IF;
   total:=total+seconds;durations:=durations||jsonb_build_array(seconds);
  END IF;
  IF n=pickup AND pickseconds IS NULL THEN pickseconds:=total; END IF;
  prev:=n;
 END LOOP;
 IF firstn IS DISTINCT FROM startnode OR prev IS DISTINCT FROM customer OR pickseconds IS NULL THEN RAISE EXCEPTION 'Invalid route endpoints'; END IF;
 RETURN jsonb_build_object('total',total,'pickup',pickseconds,'durations',durations);
END $$;
ALTER FUNCTION public.workflow_context(text) RENAME TO workflow_context_legacy;
CREATE FUNCTION public.workflow_context(basketid text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;result jsonb;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'dispatcher' OR NOT EXISTS(SELECT 1 FROM public.lab_fleet_scenarios WHERE run_id=b.run_id) THEN
 RETURN public.workflow_context_legacy(basketid); END IF;
 SELECT jsonb_build_object('expanded',true,'job',(to_jsonb(j)-'run_id'-'store')||jsonb_build_object('pickup_node',coalesce(j.parcel_node,j.pickup_node)),
 'fleet',(SELECT coalesce(jsonb_agg(to_jsonb(c)-'run_id'),'[]') FROM public.lab_fleet c WHERE c.run_id=b.run_id AND c.status='active'),
 'roads',jsonb_build_object('nodes',w.city->'nodes','edges',(SELECT jsonb_agg(e||jsonb_build_object('travel_seconds',(e->>'travel_seconds')::integer*2)) FROM jsonb_array_elements(w.city->'edges') e))) INTO result
 FROM public.lab_delivery_jobs j JOIN public.lab_worlds w ON w.run_id=j.run_id WHERE j.run_id=b.run_id AND j.basket=basketid;
 IF result IS NULL THEN RAISE EXCEPTION 'Unknown scoped basket' USING ERRCODE='42501'; END IF; RETURN result;
END $$;
ALTER FUNCTION public.dispatch_assign(text,text,jsonb) RENAME TO dispatch_assign_legacy;
CREATE FUNCTION public.dispatch_assign(basketid text,courierid text,path jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;j public.lab_delivery_jobs%ROWTYPE;c public.lab_fleet%ROWTYPE;m jsonb;sim integer;body jsonb;review jsonb;failure text;sources jsonb;prior text;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'dispatcher' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.lab_fleet_scenarios WHERE run_id=b.run_id) THEN RETURN public.dispatch_assign_legacy(basketid,courierid,path); END IF;
 SELECT * INTO j FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=basketid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown basket' USING ERRCODE='42501'; END IF;
 IF j.status NOT IN ('ready','deferred') THEN RETURN jsonb_build_object('basket',basketid,'status',j.status,'attempt',j.attempt); END IF;
 SELECT * INTO c FROM public.lab_fleet WHERE run_id=b.run_id AND id=courierid FOR UPDATE;
 IF NOT FOUND OR c.status<>'active' OR c.busy_basket IS NOT NULL THEN RAISE EXCEPTION 'Active available courier required'; END IF;
 SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
 m:=public.fleet_route_metrics(b.run_id,path,c.node,coalesce(j.parcel_node,j.pickup_node),j.customer_node);
 IF j.attempt>0 THEN
  IF NOT EXISTS(SELECT 1 FROM public.lab_retry_reviews WHERE run_id=b.run_id AND basket=basketid AND attempt=j.attempt AND verdict='approved') THEN RAISE EXCEPTION 'Approved current review required'; END IF;
  IF j.attempt>=j.retry_limit OR (m->>'total')::integer>j.deadline_sim-sim OR ceil((m->>'total')::numeric/60)>100 THEN RAISE EXCEPTION 'Recovery route exceeds current deadline or retry budget'; END IF;
 END IF;
 prior:=j.courier;
 SELECT jsonb_build_object('verdict',verdict,'reason',reason) INTO review FROM public.lab_retry_reviews WHERE run_id=b.run_id AND basket=basketid AND attempt=j.attempt;
 SELECT kind INTO failure FROM public.lab_incidents WHERE run_id=b.run_id AND basket=basketid ORDER BY id DESC LIMIT 1;
 SELECT coalesce(jsonb_agg(detail->'source_event') FILTER(WHERE detail ? 'source_event'),'[]') INTO sources FROM public.lab_incidents WHERE run_id=b.run_id AND basket=basketid;
 body:=jsonb_build_object('basket',basketid,'attempt',j.attempt+1,'objective','Collect parcel at custody checkpoint and deliver to customer',
 'custody_checkpoint',jsonb_build_object('node',coalesce(j.parcel_node,j.pickup_node),'recorded_sim',sim),
 'parcel_state',CASE WHEN j.collected THEN 'held_at_checkpoint' ELSE 'awaiting_collection' END,'prior_courier',prior,'prior_attempt',j.attempt,
 'failure_reason',failure,'source_events',sources,'judge',review,'expires_sim',j.deadline_sim,'route',path,'customer_node',j.customer_node);
 UPDATE public.lab_delivery_jobs SET status='assigned',attempt=j.attempt+1,courier=courierid,route=path,route_durations=m->'durations',
 travel_seconds=(m->>'total')::integer,traffic_delay_seconds=(m->>'total')::integer/2,accepted=false,
 depart_sim=sim,pickup_sim=sim+(m->>'pickup')::integer,arrive_sim=sim+(m->>'total')::integer WHERE run_id=b.run_id AND basket=basketid;
 UPDATE public.lab_fleet SET busy_basket=basketid WHERE run_id=b.run_id AND id=courierid;
 INSERT INTO public.lab_delivery_attempts VALUES(b.run_id,basketid,j.attempt+1,courierid,'assigned',path,m->'durations',sim,sim+(m->>'pickup')::integer,sim+(m->>'total')::integer,false,c.node);
 INSERT INTO public.lab_briefs VALUES(b.run_id,basketid,j.attempt+1,courierid,body,sim);
 RETURN jsonb_build_object('basket',basketid,'status','assigned','courier',courierid,'attempt',j.attempt+1,'route',path,'arrive_sim',sim+(m->>'total')::integer,'briefing',true);
END $$;
CREATE FUNCTION public.courier_context(basketid text,attemptid integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;result jsonb;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'courier' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 SELECT br.body||jsonb_build_object('status',j.status,'accepted',j.accepted) INTO result FROM public.lab_briefs br JOIN public.lab_delivery_jobs j USING(run_id,basket,attempt)
 WHERE br.run_id=b.run_id AND br.basket=basketid AND br.attempt=attemptid AND 'courier:'||br.courier=b.store;
 IF result IS NULL THEN RAISE EXCEPTION 'Unknown current briefing' USING ERRCODE='42501'; END IF;RETURN result;
END $$;
CREATE FUNCTION public.courier_accept(basketid text,attemptid integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;j public.lab_delivery_jobs%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'courier' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 SELECT * INTO j FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=basketid AND attempt=attemptid AND 'courier:'||courier=b.store FOR UPDATE;
 IF NOT FOUND OR j.status<>'assigned' OR NOT EXISTS(SELECT 1 FROM public.lab_fleet WHERE run_id=b.run_id AND id=j.courier AND status='active' AND busy_basket=basketid) THEN RAISE EXCEPTION 'Current online assignment required'; END IF;
 UPDATE public.lab_delivery_jobs SET accepted=true WHERE run_id=b.run_id AND basket=basketid;
 UPDATE public.lab_delivery_attempts SET accepted=true WHERE run_id=b.run_id AND basket=basketid AND attempt=attemptid;
 RETURN jsonb_build_object('basket',basketid,'attempt',attemptid,'status','accepted');
END $$;
CREATE FUNCTION public.judge_context(basketid text,attemptid integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;result jsonb;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'judge' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 SELECT jsonb_build_object('expanded',true,'job',(to_jsonb(j)-'run_id'-'store')||jsonb_build_object('pickup_node',coalesce(j.parcel_node,j.pickup_node)),
 'fleet',(SELECT coalesce(jsonb_agg(to_jsonb(c)-'run_id'),'[]') FROM public.lab_fleet c WHERE c.run_id=b.run_id AND c.status='active' AND c.busy_basket IS NULL),
 'roads',jsonb_build_object('nodes',w.city->'nodes','edges',(SELECT jsonb_agg(e||jsonb_build_object('travel_seconds',(e->>'travel_seconds')::integer*2)) FROM jsonb_array_elements(w.city->'edges') e))) INTO result
 FROM public.lab_delivery_jobs j JOIN public.lab_worlds w ON w.run_id=j.run_id WHERE j.run_id=b.run_id AND j.basket=basketid AND j.attempt=attemptid AND j.status='awaiting_review';
 IF result IS NULL THEN RAISE EXCEPTION 'Unknown failed attempt' USING ERRCODE='42501'; END IF; RETURN result;
END $$;
CREATE FUNCTION public.judge_review(basketid text,attemptid integer,courierid text DEFAULT NULL,path jsonb DEFAULT NULL) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;j public.lab_delivery_jobs%ROWTYPE;c public.lab_fleet%ROWTYPE;m jsonb;sim integer;estimate integer;remaining integer;verdict text:='denied';reason text:='No feasible active courier';prior public.lab_retry_reviews%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'judge' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 SELECT * INTO j FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=basketid AND attempt=attemptid FOR UPDATE;
 IF NOT FOUND OR j.status<>'awaiting_review' THEN RAISE EXCEPTION 'Current failed attempt required'; END IF;
 SELECT * INTO prior FROM public.lab_retry_reviews WHERE run_id=b.run_id AND basket=basketid AND attempt=attemptid;
 IF FOUND THEN RETURN to_jsonb(prior)-'run_id'; END IF;
 SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;remaining:=j.deadline_sim-sim;
 SELECT * INTO c FROM public.lab_fleet WHERE run_id=b.run_id AND id=courierid AND status='active' AND busy_basket IS NULL;
 IF FOUND AND path IS NOT NULL THEN
  BEGIN m:=public.fleet_route_metrics(b.run_id,path,c.node,coalesce(j.parcel_node,j.pickup_node),j.customer_node);estimate:=(m->>'total')::integer;
  EXCEPTION WHEN raise_exception OR invalid_text_representation OR numeric_value_out_of_range THEN estimate:=NULL; END;
 END IF;
 IF remaining<0 THEN reason:='Delivery deadline expired';
 ELSIF j.attempt>=j.retry_limit THEN reason:='Retry limit exhausted';
 ELSIF estimate IS NOT NULL AND estimate<=remaining AND ceil(estimate/60.0)<=100 THEN verdict:='approved';reason:='Route fits remaining deadline and retry budget';
 ELSIF estimate IS NOT NULL THEN reason:='Route exceeds deadline or step budget'; END IF;
 INSERT INTO public.lab_retry_reviews VALUES(b.run_id,basketid,attemptid,verdict,reason,estimate,remaining);
 RETURN jsonb_build_object('basket',basketid,'attempt',attemptid,'verdict',verdict,'reason',reason,'estimated_seconds',estimate,'remaining_seconds',remaining);
END $$;
CREATE FUNCTION public.dispatch_recover(basketid text,attemptid integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;j public.lab_delivery_jobs%ROWTYPE;review public.lab_retry_reviews%ROWTYPE;nextstatus text;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'dispatcher' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 SELECT * INTO j FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=basketid AND attempt=attemptid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown current attempt'; END IF;
 SELECT * INTO review FROM public.lab_retry_reviews WHERE run_id=b.run_id AND basket=basketid AND attempt=attemptid;
 IF NOT FOUND THEN RAISE EXCEPTION 'Matching review required'; END IF;
 nextstatus:=CASE WHEN review.verdict='approved' THEN 'ready' ELSE 'abandoned' END;
 IF j.status='awaiting_review' THEN UPDATE public.lab_delivery_jobs SET status=nextstatus WHERE run_id=b.run_id AND basket=basketid;
 ELSIF j.status<>nextstatus THEN RAISE EXCEPTION 'Review no longer current'; END IF;
 RETURN jsonb_build_object('basket',basketid,'attempt',attemptid,'status',nextstatus,'verdict',review.verdict);
END $$;
CREATE FUNCTION public.dispatch_defer(basketid text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'dispatcher' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 UPDATE public.lab_delivery_jobs SET status='deferred' WHERE run_id=b.run_id AND basket=basketid AND status IN ('ready','deferred');
 IF NOT FOUND THEN RAISE EXCEPTION 'Ready job required'; END IF; RETURN jsonb_build_object('basket',basketid,'status','deferred');
END $$;
ALTER FUNCTION public.dispatch_complete(text) RENAME TO dispatch_complete_legacy;
CREATE FUNCTION public.dispatch_complete(basketid text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;j public.lab_delivery_jobs%ROWTYPE;result jsonb;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'dispatcher' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 IF EXISTS(SELECT 1 FROM public.lab_fleet_scenarios WHERE run_id=b.run_id) THEN
  SELECT * INTO j FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=basketid FOR UPDATE;
  IF NOT FOUND OR NOT j.accepted OR j.status NOT IN ('arrived','delivered') THEN RAISE EXCEPTION 'Accepted world arrival required'; END IF;
  UPDATE public.lab_delivery_attempts SET status='completed' WHERE run_id=b.run_id AND basket=basketid AND attempt=j.attempt;
 END IF;
 result:=public.dispatch_complete_legacy(basketid);RETURN result;
END $$;
CREATE OR REPLACE FUNCTION public.agent_destination(topic text,payload jsonb) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;j public.lab_delivery_jobs%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND OR NOT(b.definition->'emits' ? topic) THEN RETURN NULL; END IF;
 IF topic='basket.reserved' THEN
  IF b.definition->>'role'<>'inventory' OR NOT EXISTS(SELECT 1 FROM public.lab_fulfillments f WHERE f.run_id=b.run_id AND f.basket=payload->>'basket' AND f.store=b.store) THEN RETURN NULL; END IF;RETURN 'fulfillment:'||b.store;
 ELSIF topic='basket.ready' THEN
  IF b.definition->>'role'<>'fulfillment' OR NOT EXISTS(SELECT 1 FROM public.lab_fulfillments f WHERE f.run_id=b.run_id AND f.basket=payload->>'basket' AND 'fulfillment:'||f.store=b.store AND f.status='picked') THEN RETURN NULL; END IF;RETURN 'dispatcher:fleet';
 ELSIF topic IN ('courier.briefed','recovery.requested','recovery.reviewed','courier.accepted') THEN
  SELECT * INTO j FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=payload->>'basket' AND attempt=(payload->>'attempt')::integer;
  IF NOT FOUND THEN RETURN NULL; END IF;
  IF topic='courier.briefed' AND b.definition->>'role'='dispatcher' THEN RETURN 'courier:'||j.courier;
  ELSIF topic='recovery.requested' AND b.definition->>'role'='dispatcher' THEN RETURN 'judge:fleet';
  ELSIF topic='recovery.reviewed' AND b.definition->>'role'='judge' THEN RETURN 'dispatcher:fleet';
  ELSIF topic='courier.accepted' AND b.definition->>'role'='courier' AND b.store='courier:'||j.courier THEN RETURN 'dispatcher:fleet';
  ELSE RETURN NULL; END IF;
 ELSE RETURN b.store; END IF;
END $$;

GRANT USAGE ON SCHEMA public TO lab_courier_executor,lab_judge_executor;
GRANT SELECT ON public.agent_budgets,public.agent_event_budgets TO lab_courier_executor,lab_judge_executor;
GRANT UPDATE(observed_tools) ON public.agent_event_budgets TO lab_courier_executor,lab_judge_executor;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.agent_memories TO lab_courier_executor,lab_judge_executor;
GRANT SELECT,INSERT,UPDATE ON public.events TO lab_courier_executor,lab_judge_executor;
GRANT SELECT,INSERT ON public.decisions TO lab_courier_executor,lab_judge_executor;
GRANT USAGE ON SEQUENCE public.events_id_seq,public.decisions_id_seq TO lab_courier_executor,lab_judge_executor;
DO $$ DECLARE tbl text; BEGIN
 FOREACH tbl IN ARRAY ARRAY['agent_memories','agent_budgets','agent_event_budgets'] LOOP
 EXECUTE format('CREATE POLICY fleet_scope ON public.%I TO lab_courier_executor,lab_judge_executor USING (run_id=(public.agent_scope()->>''run_id'')::uuid AND store=public.agent_scope()->>''store'') WITH CHECK (run_id=(public.agent_scope()->>''run_id'')::uuid AND store=public.agent_scope()->>''store'')',tbl);
 END LOOP;
END $$;
CREATE POLICY fleet_events_read ON public.events FOR SELECT TO lab_courier_executor,lab_judge_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND ((target_store=public.agent_scope()->>'store' AND public.agent_definition()->'accepts' ? topic)
 OR (producer=public.agent_definition()->>'role' AND public.agent_definition()->'emits' ? topic AND target_store=public.agent_destination(topic,payload))));
CREATE POLICY fleet_events_update ON public.events FOR UPDATE TO lab_courier_executor,lab_judge_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store' AND public.agent_definition()->'accepts' ? topic) WITH CHECK (
 run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store' AND public.agent_definition()->'accepts' ? topic);
CREATE POLICY fleet_events_insert ON public.events FOR INSERT TO lab_courier_executor,lab_judge_executor WITH CHECK (
 run_id=(public.agent_scope()->>'run_id')::uuid AND producer=public.agent_definition()->>'role' AND public.agent_definition()->'emits' ? topic AND target_store=public.agent_destination(topic,payload));
CREATE POLICY fleet_decisions ON public.decisions TO lab_courier_executor,lab_judge_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND agent=public.agent_scope()->>'agent_id') WITH CHECK (
 run_id=(public.agent_scope()->>'run_id')::uuid AND agent=public.agent_scope()->>'agent_id');
REVOKE ALL ON FUNCTION public.fleet_route_metrics(uuid,jsonb,integer,integer,integer),public.workflow_context_legacy(text),public.dispatch_assign_legacy(text,text,jsonb),public.dispatch_complete_legacy(text) FROM PUBLIC,lab_dispatch_executor,lab_fulfillment_executor;
REVOKE ALL ON FUNCTION public.workflow_context(text),public.dispatch_assign(text,text,jsonb),public.dispatch_complete(text),public.dispatch_recover(text,integer),public.dispatch_defer(text),public.courier_context(text,integer),public.courier_accept(text,integer),public.judge_context(text,integer),public.judge_review(text,integer,text,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.workflow_context(text) TO lab_dispatch_executor,lab_fulfillment_executor;
GRANT EXECUTE ON FUNCTION public.dispatch_assign(text,text,jsonb),public.dispatch_complete(text),public.dispatch_recover(text,integer),public.dispatch_defer(text) TO lab_dispatch_executor;
GRANT EXECUTE ON FUNCTION public.courier_context(text,integer),public.courier_accept(text,integer) TO lab_courier_executor;
GRANT EXECUTE ON FUNCTION public.judge_context(text,integer),public.judge_review(text,integer,text,jsonb) TO lab_judge_executor;
GRANT EXECUTE ON FUNCTION public.agent_scope(),public.agent_definition(),public.agent_clock(),public.agent_queue_room(integer),public.agent_reserve_budget(bigint,uuid,integer),public.agent_destination(text,jsonb) TO lab_courier_executor,lab_judge_executor;

-- Preserve inventory picking semantics, while carrying expanded task deadlines.
ALTER FUNCTION public.fulfillment_pick(text) RENAME TO fulfillment_pick_legacy;
CREATE FUNCTION public.fulfillment_pick(basketid text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;result jsonb;
BEGIN
 result:=public.fulfillment_pick_legacy(basketid);
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF EXISTS(SELECT 1 FROM public.lab_fleet_scenarios WHERE run_id=b.run_id) THEN
  UPDATE public.lab_delivery_jobs j SET deadline_sim=f.deadline_sim
  FROM public.lab_fulfillments f WHERE j.run_id=b.run_id AND j.basket=basketid
   AND f.run_id=j.run_id AND f.basket=j.basket AND 'fulfillment:'||f.store=b.store;
 END IF;
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.fulfillment_pick_legacy(text) FROM PUBLIC,lab_fulfillment_executor;
REVOKE ALL ON FUNCTION public.fulfillment_pick(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.fulfillment_pick(text) TO lab_fulfillment_executor;
