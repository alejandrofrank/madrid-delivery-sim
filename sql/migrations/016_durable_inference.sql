-- One optional provider dispatch per incoming event. A committed in-flight marker
-- is an uncertainty boundary, not an exactly-once provider/billing guarantee.
CREATE TABLE public.agent_inference_requests (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 run_id uuid NOT NULL REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 store text NOT NULL, definition_hash text NOT NULL,
 event_id bigint NOT NULL UNIQUE REFERENCES public.events(id) ON DELETE CASCADE,
 endpoint text NOT NULL, event_payload jsonb NOT NULL,
 context jsonb NOT NULL, memory jsonb NOT NULL, sim_time integer NOT NULL,
 proposal jsonb, sanitized_request jsonb, request_hash text,
 state text NOT NULL CHECK(state IN ('preparing','prepared','in_flight','succeeded','failed','unknown','applied')),
 prepared_attempt integer NOT NULL, dispatch_attempt integer, dispatch_lease uuid,
 dispatch_token uuid, result jsonb, error_code text,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 dispatched_at timestamptz, result_at timestamptz, applied_at timestamptz,
 CHECK(octet_length(context::text)<=8388608 AND octet_length(memory::text)<=8192),
 CHECK(result IS NULL OR (jsonb_typeof(result)='object' AND octet_length(result::text)<=4096)),
 CHECK(state='preparing' OR (proposal IS NOT NULL AND sanitized_request IS NOT NULL AND request_hash IS NOT NULL))
);
CREATE TABLE public.agent_inference_history (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 request_id uuid NOT NULL REFERENCES public.agent_inference_requests(id) ON DELETE CASCADE,
 state text NOT NULL, attempt integer NOT NULL, code text,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(code IS NULL OR code ~ '^[A-Za-z][A-Za-z0-9_]{0,79}$')
);
REVOKE ALL ON public.agent_inference_requests,public.agent_inference_history FROM PUBLIC;

-- Internal helpers are never granted to agent roles. Every public transition
-- reconstructs ownership from session_user and an authoritative live queue lease.
CREATE FUNCTION public.agent_inference_scope(eventid bigint,token uuid,eventattempt integer)
RETURNS public.agent_bindings LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND OR b.definition->>'role' IS DISTINCT FROM 'judge'
 OR b.definition->>'policy' IS DISTINCT FROM 'gcp_ai'
 OR current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Authenticated cloud judge required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(b.run_id::text,0));
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) OR NOT EXISTS(
  SELECT 1 FROM public.events e JOIN public.agent_event_budgets t ON t.event_id=e.id
  AND t.attempt=e.attempts WHERE e.id=eventid AND e.topic='delivery.failed'
  AND t.run_id=b.run_id AND t.store=b.store) THEN
  RAISE EXCEPTION 'Active scoped judge lease and ticket required' USING ERRCODE='42501'; END IF;
 RETURN b;
END $$;

CREATE FUNCTION public.agent_inference_read(eventid bigint,token uuid,eventattempt integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; q public.agent_inference_requests%ROWTYPE; e public.events%ROWTYPE;
BEGIN
 b:=public.agent_inference_scope(eventid,token,eventattempt);
 SELECT * INTO e FROM public.events WHERE id=eventid;
 SELECT * INTO q FROM public.agent_inference_requests WHERE event_id=eventid
  AND run_id=b.run_id AND store=b.store AND definition_hash=b.definition_hash;
 IF NOT FOUND OR q.event_payload IS DISTINCT FROM e.payload THEN
  RAISE EXCEPTION 'Matching scoped inference request required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.agent_inference_history(request_id,state,attempt) VALUES(q.id,'read',eventattempt);
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN
  RAISE EXCEPTION 'Inference read lease expired' USING ERRCODE='42501'; END IF;
 RETURN to_jsonb(q);
END $$;

CREATE FUNCTION public.agent_inference_begin(eventid bigint,token uuid,eventattempt integer,origin text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; e public.events%ROWTYPE; q public.agent_inference_requests%ROWTYPE;
 observation jsonb; recalled jsonb; sim integer;
BEGIN
 b:=public.agent_inference_scope(eventid,token,eventattempt);
 IF origin IS NULL OR origin !~ '^https://[a-z0-9-]+(\.a)?\.run\.app$' THEN
  RAISE EXCEPTION 'Cloud Run origin required' USING ERRCODE='22023'; END IF;
 SELECT * INTO e FROM public.events WHERE id=eventid;
 SELECT * INTO q FROM public.agent_inference_requests WHERE event_id=eventid FOR UPDATE;
 IF FOUND THEN
  IF q.run_id IS DISTINCT FROM b.run_id OR q.store IS DISTINCT FROM b.store
  OR q.definition_hash IS DISTINCT FROM b.definition_hash OR q.endpoint IS DISTINCT FROM origin
  OR q.event_payload IS DISTINCT FROM e.payload THEN
   RAISE EXCEPTION 'Inference identity changed' USING ERRCODE='42501'; END IF;
  -- A concurrent worker using the same live lease must leave its owner alone.
  IF q.state='in_flight' AND (q.dispatch_attempt IS DISTINCT FROM eventattempt OR q.dispatch_lease IS DISTINCT FROM token) THEN
   UPDATE public.agent_inference_requests SET state='unknown',error_code='InvocationOutcomeUnknown',
    result=jsonb_build_object('provider','gcp_ai','fallback','fail_closed','error','InvocationOutcomeUnknown'),
    result_at=clock_timestamp() WHERE id=q.id RETURNING * INTO q;
   UPDATE public.agent_model_calls SET status='unknown',detail=q.result
    WHERE event_id=eventid AND attempt=q.dispatch_attempt AND status='reserved';
   INSERT INTO public.agent_inference_history(request_id,state,attempt,code)
    VALUES(q.id,q.state,eventattempt,q.error_code);
  END IF;
  INSERT INTO public.agent_inference_history(request_id,state,attempt) VALUES(q.id,'read',eventattempt);
  RETURN to_jsonb(q);
 END IF;
 IF jsonb_typeof(e.payload) IS DISTINCT FROM 'object' OR e.payload->>'basket' IS NULL
 OR jsonb_typeof(e.payload->'attempt') IS DISTINCT FROM 'number'
 OR (e.payload->>'attempt')::numeric%1<>0 THEN
  RAISE EXCEPTION 'Authoritative failed-attempt payload required' USING ERRCODE='42501'; END IF;
 IF NOT public.agent_consume_tool(eventid,token,eventattempt,'judge.read') THEN
  RAISE EXCEPTION 'Judge observation ticket required' USING ERRCODE='42501'; END IF;
 observation:=public.judge_context(e.payload->>'basket',(e.payload->>'attempt')::integer);
 recalled:=public.agent_memory_recall(eventid,token,eventattempt,NULL,8);
 SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
 INSERT INTO public.agent_inference_requests(run_id,store,definition_hash,event_id,endpoint,
  event_payload,context,memory,sim_time,state,prepared_attempt)
 VALUES(b.run_id,b.store,b.definition_hash,eventid,origin,e.payload,observation,recalled,sim,'preparing',eventattempt)
 RETURNING * INTO q;
 INSERT INTO public.agent_inference_history(request_id,state,attempt) VALUES(q.id,'observed',eventattempt);
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN
  RAISE EXCEPTION 'Inference lease expired during preparation' USING ERRCODE='42501'; END IF;
 RETURN to_jsonb(q);
END $$;

CREATE FUNCTION public.agent_inference_seal(eventid bigint,token uuid,eventattempt integer,requestid uuid,
 localproposal jsonb,outbound jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; q public.agent_inference_requests%ROWTYPE;
 facts jsonb:='{}'; candidate jsonb; prop text; value jsonb; expected jsonb;
BEGIN
 b:=public.agent_inference_scope(eventid,token,eventattempt);
 SELECT * INTO q FROM public.agent_inference_requests WHERE id=requestid AND event_id=eventid
  AND run_id=b.run_id AND store=b.store AND definition_hash=b.definition_hash AND state='preparing' FOR UPDATE;
 IF NOT FOUND OR localproposal IS NULL OR jsonb_typeof(localproposal)<>'object'
 OR NOT(localproposal ?& ARRAY['courier','route','candidate']) OR EXISTS(
  SELECT 1 FROM jsonb_object_keys(localproposal) k WHERE k NOT IN ('courier','route','candidate'))
 OR octet_length(localproposal::text)>65536 THEN
  RAISE EXCEPTION 'Bounded scoped local proposal required' USING ERRCODE='42501'; END IF;
 FOREACH prop IN ARRAY ARRAY['attempt','retry_limit','deadline_sim','cost_eur'] LOOP
  value:=q.context->'job'->prop;
  IF jsonb_typeof(value)='number' THEN facts:=facts||jsonb_build_object(prop,value); END IF;
 END LOOP;
 facts:=facts||jsonb_build_object('sim_time',q.sim_time);
 candidate:=localproposal->'candidate';
 IF candidate<>'null'::jsonb THEN
  IF jsonb_typeof(candidate)<>'object' OR EXISTS(SELECT 1 FROM jsonb_each(candidate) p(k,v)
   WHERE k NOT IN ('estimated_seconds','remaining_seconds','route_nodes') OR jsonb_typeof(v)<>'number'
   OR (v#>>'{}')::numeric<0) THEN
   RAISE EXCEPTION 'Numeric proposal summary required' USING ERRCODE='22023'; END IF;
 END IF;
 expected:=jsonb_build_object('facts',facts,'candidate',candidate,'memory_entries',least(jsonb_array_length(q.memory),100));
 IF outbound IS DISTINCT FROM expected OR octet_length(outbound::text)>8192 THEN
  RAISE EXCEPTION 'Only allowlisted numeric inference facts may leave' USING ERRCODE='42501'; END IF;
 UPDATE public.agent_inference_requests SET proposal=localproposal,sanitized_request=outbound,state='prepared',
  request_hash=encode(sha256(convert_to(jsonb_build_object('run',run_id,'namespace',store,
   'role_hash',definition_hash,'endpoint',endpoint,'event',event_id,'payload',event_payload,
   'context',context,'memory',memory,'sim',sim_time,'proposal',localproposal,'outbound',outbound)::text,'UTF8')),'hex')
 WHERE id=q.id RETURNING * INTO q;
 INSERT INTO public.agent_inference_history(request_id,state,attempt) VALUES(q.id,q.state,eventattempt);
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN
  RAISE EXCEPTION 'Inference lease expired during sealing' USING ERRCODE='42501'; END IF;
 RETURN to_jsonb(q);
END $$;

CREATE FUNCTION public.agent_inference_dispatch(eventid bigint,token uuid,eventattempt integer,requestid uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; q public.agent_inference_requests%ROWTYPE; e public.events%ROWTYPE;
 currentcontext jsonb; currentmemory jsonb; sim integer; code text;
 legacy public.agent_model_calls%ROWTYPE;
BEGIN
 b:=public.agent_inference_scope(eventid,token,eventattempt);
 SELECT * INTO q FROM public.agent_inference_requests WHERE id=requestid AND event_id=eventid
  AND run_id=b.run_id AND store=b.store AND definition_hash=b.definition_hash FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Own inference request required' USING ERRCODE='42501'; END IF;
 IF q.state<>'prepared' THEN RETURN jsonb_build_object('dispatch',false,'request',to_jsonb(q)); END IF;
 SELECT * INTO e FROM public.events WHERE id=eventid;
 SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
 BEGIN currentcontext:=public.judge_context(e.payload->>'basket',(e.payload->>'attempt')::integer);
 EXCEPTION WHEN raise_exception OR insufficient_privilege THEN code:='PreconditionsChanged'; END;
 IF e.payload IS DISTINCT FROM q.event_payload OR currentcontext IS DISTINCT FROM q.context OR sim<>q.sim_time THEN
  code:='PreconditionsChanged';
 END IF;
 -- A legacy call has no immutable snapshot. Preserve its allowance; never resend.
 SELECT * INTO legacy FROM public.agent_model_calls WHERE event_id=eventid ORDER BY attempt LIMIT 1;
 IF FOUND THEN
  code:='LegacyInvocationOutcomeUnknown';
  UPDATE public.agent_model_calls SET status='unknown',
   detail=jsonb_build_object('provider','gcp_ai','fallback','fail_closed','error',code)
   WHERE event_id=eventid AND status='reserved';
 END IF;
 IF code IS NULL THEN
  -- Budget for a fresh recall plus the five application tools before spending.
  IF (SELECT slots-observed_tools FROM public.agent_event_budgets
   WHERE event_id=eventid AND attempt=eventattempt)<6 THEN code:='ToolBudgetInsufficientForApply';
  ELSE
   currentmemory:=public.agent_memory_recall(eventid,token,eventattempt,NULL,8);
   IF currentmemory IS DISTINCT FROM q.memory THEN code:='MemoryPreconditionsChanged'; END IF;
  END IF;
 END IF;
 IF code IS NULL THEN
  IF (SELECT count(*)>=least(6,(b.definition->'limits'->>'model_calls')::integer)
  OR coalesce(sum(reserved_tokens),0)+8448>least(50688,(b.definition->'limits'->>'model_tokens')::integer)
  FROM public.agent_model_calls WHERE run_id=b.run_id)
  THEN code:='ModelBudgetExceeded';
  ELSIF NOT public.agent_reserve_model(eventid,token,eventattempt) THEN code:='ModelBudgetExceeded'; END IF;
 END IF;
 IF code IS NOT NULL THEN
  UPDATE public.agent_inference_requests SET
   state=CASE WHEN code='LegacyInvocationOutcomeUnknown' THEN 'unknown' ELSE 'failed' END,
   dispatch_attempt=CASE WHEN code='LegacyInvocationOutcomeUnknown' THEN legacy.attempt ELSE NULL END,
   error_code=code,result_at=clock_timestamp(),
   result=jsonb_build_object('provider','gcp_ai','fallback','fail_closed','error',code)
   WHERE id=q.id RETURNING * INTO q;
 ELSE
  UPDATE public.agent_inference_requests SET state='in_flight',dispatch_attempt=eventattempt,
   dispatch_lease=token,dispatch_token=gen_random_uuid(),dispatched_at=clock_timestamp()
   WHERE id=q.id RETURNING * INTO q;
 END IF;
 INSERT INTO public.agent_inference_history(request_id,state,attempt,code) VALUES(q.id,q.state,eventattempt,q.error_code);
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN
  RAISE EXCEPTION 'Inference lease expired before dispatch commit' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('dispatch',q.state='in_flight','request',to_jsonb(q));
END $$;

CREATE FUNCTION public.agent_inference_save(eventid bigint,token uuid,eventattempt integer,requestid uuid,
 dispatchid uuid,outcome jsonb,errorclass text DEFAULT NULL) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; q public.agent_inference_requests%ROWTYPE; nextstate text;
BEGIN
 b:=public.agent_inference_scope(eventid,token,eventattempt);
 SELECT * INTO q FROM public.agent_inference_requests WHERE id=requestid AND event_id=eventid
  AND run_id=b.run_id AND store=b.store AND definition_hash=b.definition_hash FOR UPDATE;
 IF NOT FOUND OR q.state<>'in_flight' OR q.dispatch_token IS DISTINCT FROM dispatchid
 OR q.dispatch_attempt IS DISTINCT FROM eventattempt OR q.dispatch_lease IS DISTINCT FROM token THEN RETURN false; END IF;
 IF errorclass IS NOT NULL THEN
  IF errorclass !~ '^[A-Za-z][A-Za-z0-9_]{0,79}$' THEN errorclass:='ProviderError'; END IF;
  outcome:=jsonb_build_object('provider','gcp_ai','fallback','fail_closed','error',errorclass);
  nextstate:='unknown';
 ELSE
  IF outcome IS NULL OR jsonb_typeof(outcome)<>'object' OR octet_length(outcome::text)>4096
  OR NOT(outcome ?& ARRAY['decision','source','reason','model','input_tokens','output_tokens'])
  OR EXISTS(SELECT 1 FROM jsonb_object_keys(outcome) k WHERE k NOT IN
   ('decision','source','reason','model','input_tokens','output_tokens'))
  OR jsonb_typeof(outcome->'decision')<>'string' OR outcome->>'decision' NOT IN ('approve_retry','deny_retry')
  OR jsonb_typeof(outcome->'source')<>'string' OR outcome->>'source' NOT IN ('model','policy_gate')
  OR jsonb_typeof(outcome->'reason')<>'string' OR length(outcome->>'reason') NOT BETWEEN 1 AND 600
  OR jsonb_typeof(outcome->'model')<>'string' OR length(outcome->>'model') NOT BETWEEN 1 AND 200
  OR jsonb_typeof(outcome->'input_tokens')<>'number' OR (outcome->>'input_tokens')::numeric NOT BETWEEN 0 AND 8192
  OR (outcome->>'input_tokens')::numeric%1<>0
  OR jsonb_typeof(outcome->'output_tokens')<>'number' OR (outcome->>'output_tokens')::numeric NOT BETWEEN 0 AND 256
  OR (outcome->>'output_tokens')::numeric%1<>0
  OR (outcome->>'decision'='approve_retry' AND q.proposal->'candidate'='null'::jsonb) THEN
   RAISE EXCEPTION 'Validated bounded judgement required' USING ERRCODE='22023'; END IF;
  outcome:=outcome||jsonb_build_object('provider','gcp_ai','fallback',NULL);
  nextstate:='succeeded';
 END IF;
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN RETURN false; END IF;
 UPDATE public.agent_inference_requests SET state=nextstate,result=outcome,error_code=errorclass,
  result_at=clock_timestamp() WHERE id=q.id;
 UPDATE public.agent_model_calls SET status=CASE WHEN nextstate='succeeded' THEN 'completed' ELSE 'unknown' END,
  detail=outcome WHERE event_id=eventid AND attempt=q.dispatch_attempt AND status='reserved';
 INSERT INTO public.agent_inference_history(request_id,state,attempt,code) VALUES(q.id,nextstate,eventattempt,errorclass);
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN
  RAISE EXCEPTION 'Inference save lease expired' USING ERRCODE='42501'; END IF;
 RETURN true;
END $$;

CREATE FUNCTION public.agent_inference_applied(eventid bigint,token uuid,eventattempt integer,requestid uuid)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; q public.agent_inference_requests%ROWTYPE;
BEGIN
 b:=public.agent_inference_scope(eventid,token,eventattempt);
 SELECT * INTO q FROM public.agent_inference_requests WHERE id=requestid AND event_id=eventid
  AND run_id=b.run_id AND store=b.store AND definition_hash=b.definition_hash FOR UPDATE;
 IF NOT FOUND OR q.state NOT IN ('succeeded','failed','unknown') OR q.result IS NULL
 OR (q.dispatch_attempt IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.agent_model_calls m
  WHERE m.event_id=eventid AND m.attempt=q.dispatch_attempt AND m.run_id=b.run_id
  AND m.store=b.store AND m.status IN ('completed','unknown'))) THEN
  RAISE EXCEPTION 'Terminal inference receipt required' USING ERRCODE='42501'; END IF;
 UPDATE public.agent_inference_requests SET state='applied',applied_at=clock_timestamp() WHERE id=q.id;
 INSERT INTO public.agent_inference_history(request_id,state,attempt) VALUES(q.id,'applied',eventattempt);
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN
  RAISE EXCEPTION 'Inference apply lease expired' USING ERRCODE='42501'; END IF;
 RETURN true;
END $$;

REVOKE ALL ON FUNCTION public.agent_inference_scope(bigint,uuid,integer),
 public.agent_inference_read(bigint,uuid,integer),public.agent_inference_begin(bigint,uuid,integer,text),
 public.agent_inference_seal(bigint,uuid,integer,uuid,jsonb,jsonb),
 public.agent_inference_dispatch(bigint,uuid,integer,uuid),
 public.agent_inference_save(bigint,uuid,integer,uuid,uuid,jsonb,text),
 public.agent_inference_applied(bigint,uuid,integer,uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agent_inference_read(bigint,uuid,integer),
 public.agent_inference_begin(bigint,uuid,integer,text),public.agent_inference_seal(bigint,uuid,integer,uuid,jsonb,jsonb),
 public.agent_inference_dispatch(bigint,uuid,integer,uuid),public.agent_inference_save(bigint,uuid,integer,uuid,uuid,jsonb,text),
 public.agent_inference_applied(bigint,uuid,integer,uuid) TO lab_judge_executor;
-- Legacy reservation/audit APIs cannot manufacture or overwrite durable receipts.
REVOKE EXECUTE ON FUNCTION public.agent_reserve_model(bigint,uuid,integer),
 public.agent_record_model(bigint,integer,jsonb),public.agent_model_reserved(bigint,uuid,integer)
 FROM lab_judge_executor;
DO $$ DECLARE role_name text; BEGIN
 FOREACH role_name IN ARRAY ARRAY['lab_inventory_executor','lab_fulfillment_executor',
  'lab_dispatch_executor','lab_courier_executor','lab_judge_executor','lab_supply_executor'] LOOP
  EXECUTE format('REVOKE ALL ON public.agent_inference_requests,public.agent_inference_history FROM %I',role_name);
 END LOOP;
END $$;
