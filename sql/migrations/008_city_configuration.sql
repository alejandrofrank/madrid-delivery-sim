-- Persist trusted city inputs without exposing raw configuration to agent roles.
CREATE TABLE public.lab_city_configs(
 run_id uuid PRIMARY KEY REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 config jsonb NOT NULL CHECK (
  jsonb_typeof(config)='object' AND config ? 'traffic_multiplier'
  AND jsonb_typeof(config->'traffic_multiplier')='number'
  AND (config->>'traffic_multiplier')::numeric BETWEEN 0.5 AND 3
 )
);
REVOKE ALL ON public.lab_city_configs FROM PUBLIC;
ALTER TABLE public.lab_fleet ADD COLUMN home_store text;

CREATE OR REPLACE FUNCTION public.fleet_route_metrics(runid uuid,path jsonb,startnode integer,pickup integer,customer integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE world jsonb;n integer;prev integer;firstn integer;seconds integer;total integer:=0;pickseconds integer;durations jsonb:='[]';factor numeric;base_seconds integer;base_total integer:=0;
BEGIN
 IF path IS NULL OR jsonb_typeof(path)<>'array' THEN RAISE EXCEPTION 'Invalid route'; END IF;
 IF jsonb_array_length(path) NOT BETWEEN 1 AND 1000 THEN RAISE EXCEPTION 'Invalid route length'; END IF;
 SELECT coalesce((SELECT (config->>'traffic_multiplier')::numeric FROM public.lab_city_configs WHERE run_id=runid),2) INTO factor;
 SELECT city INTO world FROM public.lab_worlds WHERE run_id=runid;
 FOR n IN SELECT value::integer FROM jsonb_array_elements_text(path) LOOP
  IF prev IS NULL THEN firstn:=n; ELSE
   SELECT (e->>'travel_seconds')::integer INTO base_seconds FROM jsonb_array_elements(world->'edges') e
   WHERE (e->>'from')::integer=prev AND (e->>'to')::integer=n AND e->'modes' ? 'bike';
   seconds:=ceil(base_seconds*factor)::integer;
   IF seconds IS NULL OR seconds<=0 THEN RAISE EXCEPTION 'Invalid bike edge'; END IF;
   base_total:=base_total+base_seconds;total:=total+seconds;durations:=durations||jsonb_build_array(seconds);
  END IF;
  IF n=pickup AND pickseconds IS NULL THEN pickseconds:=total; END IF;
  prev:=n;
 END LOOP;
 IF firstn IS DISTINCT FROM startnode OR prev IS DISTINCT FROM customer OR pickseconds IS NULL THEN RAISE EXCEPTION 'Invalid route endpoints'; END IF;
 RETURN jsonb_build_object('total',total,'pickup',pickseconds,'durations',durations,'delay',greatest(0,total-base_total));
END $$;

CREATE OR REPLACE FUNCTION public.workflow_context(basketid text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;result jsonb;factor numeric;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 SELECT coalesce((SELECT (config->>'traffic_multiplier')::numeric FROM public.lab_city_configs WHERE run_id=b.run_id),2) INTO factor;
 IF b.definition->>'role' IS DISTINCT FROM 'dispatcher' OR NOT EXISTS(SELECT 1 FROM public.lab_fleet_scenarios WHERE run_id=b.run_id) THEN
 RETURN public.workflow_context_legacy(basketid); END IF;
 SELECT jsonb_build_object('expanded',true,'job',(to_jsonb(j)-'run_id'-'store')||jsonb_build_object('pickup_node',coalesce(j.parcel_node,j.pickup_node)),
 'fleet',(SELECT coalesce(jsonb_agg(to_jsonb(c)-'run_id'),'[]') FROM public.lab_fleet c WHERE c.run_id=b.run_id AND c.status='active'),
 'roads',jsonb_build_object('nodes',w.city->'nodes','edges',(SELECT jsonb_agg(e||jsonb_build_object('travel_seconds',ceil((e->>'travel_seconds')::numeric*factor)::integer)) FROM jsonb_array_elements(w.city->'edges') e))) INTO result
 FROM public.lab_delivery_jobs j JOIN public.lab_worlds w ON w.run_id=j.run_id WHERE j.run_id=b.run_id AND j.basket=basketid;
 IF result IS NULL THEN RAISE EXCEPTION 'Unknown scoped basket' USING ERRCODE='42501'; END IF; RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.judge_context(basketid text,attemptid integer) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;result jsonb;factor numeric;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 SELECT coalesce((SELECT (config->>'traffic_multiplier')::numeric FROM public.lab_city_configs WHERE run_id=b.run_id),2) INTO factor;
 IF b.definition->>'role' IS DISTINCT FROM 'judge' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 SELECT jsonb_build_object('expanded',true,'job',(to_jsonb(j)-'run_id'-'store')||jsonb_build_object('pickup_node',coalesce(j.parcel_node,j.pickup_node)),
 'fleet',(SELECT coalesce(jsonb_agg(to_jsonb(c)-'run_id'),'[]') FROM public.lab_fleet c WHERE c.run_id=b.run_id AND c.status='active' AND c.busy_basket IS NULL),
 'roads',jsonb_build_object('nodes',w.city->'nodes','edges',(SELECT jsonb_agg(e||jsonb_build_object('travel_seconds',ceil((e->>'travel_seconds')::numeric*factor)::integer)) FROM jsonb_array_elements(w.city->'edges') e))) INTO result
 FROM public.lab_delivery_jobs j JOIN public.lab_worlds w ON w.run_id=j.run_id WHERE j.run_id=b.run_id AND j.basket=basketid AND j.attempt=attemptid AND j.status='awaiting_review';
 IF result IS NULL THEN RAISE EXCEPTION 'Unknown failed attempt' USING ERRCODE='42501'; END IF; RETURN result;
END $$;

CREATE OR REPLACE FUNCTION public.dispatch_assign(basketid text,courierid text,path jsonb) RETURNS jsonb
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
 travel_seconds=(m->>'total')::integer,traffic_delay_seconds=(m->>'delay')::integer,accepted=false,
 depart_sim=sim,pickup_sim=sim+(m->>'pickup')::integer,arrive_sim=sim+(m->>'total')::integer WHERE run_id=b.run_id AND basket=basketid;
 UPDATE public.lab_fleet SET busy_basket=basketid WHERE run_id=b.run_id AND id=courierid;
 INSERT INTO public.lab_delivery_attempts VALUES(b.run_id,basketid,j.attempt+1,courierid,'assigned',path,m->'durations',sim,sim+(m->>'pickup')::integer,sim+(m->>'total')::integer,false,c.node);
 INSERT INTO public.lab_briefs VALUES(b.run_id,basketid,j.attempt+1,courierid,body,sim);
 RETURN jsonb_build_object('basket',basketid,'status','assigned','courier',courierid,'attempt',j.attempt+1,'route',path,'arrive_sim',sim+(m->>'total')::integer,'briefing',true);
END $$;

ALTER TABLE public.lab_city_configs ADD COLUMN order_schedule jsonb NOT NULL DEFAULT '[]'::jsonb, ADD COLUMN dropout_schedule jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE public.lab_city_configs ADD COLUMN summary jsonb NOT NULL DEFAULT '{}'::jsonb;
