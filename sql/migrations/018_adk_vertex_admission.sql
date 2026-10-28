-- Native Vertex is optional and never selected as an offline fallback. Monetary
-- admission is serialized and nonrefundable, using the frozen approved price profile.
ALTER TABLE public.restaurant_model_calls ADD COLUMN provider text NOT NULL DEFAULT 'offline'
 CHECK(provider IN ('offline','vertex'));
ALTER TABLE public.restaurant_model_calls ADD COLUMN reserved_usd numeric(18,8) NOT NULL DEFAULT 0
 CHECK(reserved_usd>=0);

CREATE OR REPLACE FUNCTION public.restaurant_scope(eventid bigint,token uuid,attempt integer)
RETURNS public.agent_bindings LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND OR b.definition->>'role' IS DISTINCT FROM 'restaurant'
 OR b.definition->>'policy' IS DISTINCT FROM 'adk'
 OR coalesce(b.definition->'brain'->>'provider','') NOT IN ('offline','vertex')
 OR current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Authenticated ADK restaurant required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(b.run_id::text,0));
 IF NOT public.agent_queue_lock(eventid,token,attempt) OR NOT EXISTS(
  SELECT 1 FROM public.agent_event_budgets t WHERE t.event_id=eventid AND t.attempt=restaurant_scope.attempt
  AND t.run_id=b.run_id AND t.store=b.store) OR NOT EXISTS(
  SELECT 1 FROM public.events e JOIN public.supply_orders o ON o.run_id=e.run_id AND o.id=e.payload->>'order'
  WHERE e.id=eventid AND o.restaurant=b.store) THEN
  RAISE EXCEPTION 'Active own restaurant order lease and budget required' USING ERRCODE='42501'; END IF;
 RETURN b;
END $$;

ALTER FUNCTION public.restaurant_model_admit(bigint,uuid,integer,uuid,integer,text)
 RENAME TO restaurant_model_admit_unpriced;
REVOKE ALL ON FUNCTION public.restaurant_model_admit_unpriced(bigint,uuid,integer,uuid,integer,text)
 FROM PUBLIC,lab_restaurant_adk_executor;

CREATE FUNCTION public.restaurant_model_admit(eventid bigint,token uuid,attempt integer,turnnonce uuid,
 requestbytes integer,requesthash text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE q public.restaurant_turns%ROWTYPE; cfg jsonb; inputprice numeric; outputprice numeric;
 reserve numeric:=0; spent numeric; runspent numeric; stepid integer; ceiling numeric;
BEGIN
 q:=public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 SELECT definition->'brain' INTO cfg FROM public.agent_bindings WHERE login_role=session_user;
 IF cfg->>'provider'='vertex' THEN
  inputprice:=(cfg->'vertex'->>'input_usd_per_million')::numeric;
  outputprice:=(cfg->'vertex'->>'output_usd_per_million')::numeric;
  ceiling:=(cfg->>'usd_limit')::numeric;
  IF inputprice IS NULL OR outputprice IS NULL OR ceiling IS NULL
   OR inputprice NOT BETWEEN 0.00000001 AND 1000 OR outputprice NOT BETWEEN 0.00000001 AND 1000
   OR ceiling NOT BETWEEN 0.00000001 AND 10 THEN
   RAISE EXCEPTION 'Approved Vertex price profile and monetary allowance required' USING ERRCODE='42501'; END IF;
  reserve:=ceil((requestbytes*inputprice+(cfg->>'output_tokens')::integer*outputprice)/1000000*100000000)/100000000;
  SELECT coalesce(sum(m.reserved_usd),0) INTO spent FROM public.restaurant_model_calls m
   JOIN public.restaurant_turns t USING(event_id) WHERE t.run_id=q.run_id AND t.store=q.store;
  SELECT coalesce(sum(m.reserved_usd),0) INTO runspent FROM public.restaurant_model_calls m
   JOIN public.restaurant_turns t USING(event_id) WHERE t.run_id=q.run_id;
  IF spent+reserve>ceiling OR runspent+reserve>10 THEN
   RAISE EXCEPTION 'Restaurant monetary allowance exhausted' USING ERRCODE='54000'; END IF;
 END IF;
 stepid:=public.restaurant_model_admit_unpriced(eventid,token,attempt,turnnonce,requestbytes,requesthash);
 UPDATE public.restaurant_model_calls SET provider=cfg->>'provider',reserved_usd=reserve
 WHERE event_id=eventid AND step=stepid;
 RETURN stepid;
END $$;
REVOKE ALL ON FUNCTION public.restaurant_model_admit(bigint,uuid,integer,uuid,integer,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.restaurant_model_admit(bigint,uuid,integer,uuid,integer,text)
 TO lab_restaurant_adk_executor;

CREATE OR REPLACE FUNCTION public.restaurant_apply(eventid bigint,token uuid,attempt integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; q public.restaurant_turns%ROWTYPE;
 result jsonb; topicname text; fact jsonb; expected text[];
BEGIN
 b:=public.restaurant_scope(eventid,token,attempt);
 SELECT * INTO q FROM public.restaurant_turns WHERE event_id=eventid AND run_id=b.run_id AND store=b.store
  AND definition_hash=b.definition_hash AND state='succeeded' FOR UPDATE;
 IF NOT FOUND OR q.event_payload IS DISTINCT FROM (SELECT payload FROM public.events WHERE id=eventid)
 OR q.context IS DISTINCT FROM public.supply_context(q.event_payload->>'order') THEN
  RAISE EXCEPTION 'Saved decision does not match current restaurant facts' USING ERRCODE='42501'; END IF;
 FOR fact IN SELECT value FROM jsonb_array_elements(q.memory) LOOP
  IF NOT EXISTS(SELECT 1 FROM public.agent_memory_current f JOIN public.runs r ON r.id=f.run_id
   WHERE f.id=(fact->>'fact_id')::bigint AND f.run_id=b.run_id AND f.store=b.store
   AND f.context_id=q.event_payload->>'order' AND f.expires_sim>r.sim_time
   AND f.version=(fact->>'version')::integer) THEN
   RAISE EXCEPTION 'Recalled memory became stale' USING ERRCODE='42501'; END IF;
 END LOOP;
 SELECT topic INTO topicname FROM public.events WHERE id=eventid;
 expected:=CASE topicname WHEN 'household.call' THEN ARRAY['source','confirm','decline']
  WHEN 'ingredient.shortage' THEN ARRAY['offer','decline']
  WHEN 'restaurant.approval' THEN ARRAY['source','decline']
  WHEN 'ingredient.arrived' THEN ARRAY['receive','decline']
  WHEN 'restaurant.cook' THEN ARRAY['cook','decline'] END;
 IF expected IS NULL OR NOT(q.result->>'action'=ANY(expected)) THEN
  RAISE EXCEPTION 'Action does not match the incoming event' USING ERRCODE='42501'; END IF;
 IF q.result->>'action'='decline' AND (jsonb_typeof(q.result->'reason')<>'string'
  OR length(q.result->>'reason') NOT BETWEEN 1 AND 240) THEN RAISE EXCEPTION 'Invalid decline reason'; END IF;
 result:=public.supply_transition(eventid,token,attempt,q.result);
 UPDATE public.restaurant_turns SET state='applied' WHERE event_id=eventid;
 RETURN result||jsonb_build_object('adk',jsonb_build_object('engine','google_adk','provider',b.definition->'brain'->>'provider',
  'definition_hash',q.definition_hash,'plan',q.result,
  'model_calls',(SELECT count(*) FROM public.restaurant_model_calls WHERE event_id=eventid),
  'reserved_tokens',(SELECT sum(reserved_tokens) FROM public.restaurant_model_calls WHERE event_id=eventid),
  'paid_calls',CASE WHEN b.definition->'brain'->>'provider'='offline' THEN 0 ELSE NULL END,
  'reserved_usd',(SELECT sum(reserved_usd) FROM public.restaurant_model_calls WHERE event_id=eventid),'memory',q.memory,
  'tools',coalesce((SELECT jsonb_agg(jsonb_build_object('tool',p.tool,'result',p.result) ORDER BY p.step)
    FROM public.restaurant_tool_receipts p WHERE p.event_id=eventid),'[]')));
END $$;
