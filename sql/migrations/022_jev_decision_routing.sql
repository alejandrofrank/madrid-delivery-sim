-- One durable router receipt per leased restaurant event. No model grants authority.
CREATE TABLE public.restaurant_routes (
 event_id bigint PRIMARY KEY REFERENCES public.restaurant_turns(event_id) ON DELETE CASCADE,
 state text NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','completed')),
 executor text CHECK(executor IN ('rules','jev','gemini')),
 request_body jsonb NOT NULL, response_body jsonb, decision jsonb,
 model text, reserved_input_tokens integer NOT NULL DEFAULT 0 CHECK(reserved_input_tokens>=0),
 reserved_usd numeric(18,8) NOT NULL DEFAULT 0 CHECK(reserved_usd>=0),
 input_tokens integer CHECK(input_tokens>=0), output_tokens integer CHECK(output_tokens>=0),
 confidence numeric CHECK(confidence BETWEEN 0 AND 1), margin numeric CHECK(margin BETWEEN 0 AND 1),
 reason text, error_code text, latency_ms integer CHECK(latency_ms BETWEEN 0 AND 60000),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), completed_at timestamptz,
 CHECK(octet_length(request_body::text)<=32768),
 CHECK(response_body IS NULL OR octet_length(response_body::text)<=65536),
 CHECK(decision IS NULL OR octet_length(decision::text)<=4096)
);
REVOKE ALL ON public.restaurant_routes FROM PUBLIC,lab_restaurant_adk_executor;

CREATE FUNCTION public.restaurant_route_begin(eventid bigint,token uuid,attempt integer,turnnonce uuid,
 body jsonb,rules boolean) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE q public.restaurant_turns%ROWTYPE; cfg jsonb; calls integer; tokens bigint; dollars numeric;
 reserve integer:=0; money numeric:=0; topicname text;
BEGIN
 q:=public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 SELECT definition->'brain'->'routing' INTO cfg FROM public.agent_bindings WHERE login_role=session_user;
 IF cfg->>'strategy' IS DISTINCT FROM 'jev_first' OR cfg->>'model' IS DISTINCT FROM 'jev-1.14.0'
 OR body IS NULL OR jsonb_typeof(body)<>'object' OR octet_length(body::text)>32768 THEN
  RAISE EXCEPTION 'Approved bounded router required' USING ERRCODE='42501'; END IF;
 IF rules THEN
  SELECT topic INTO topicname FROM public.events WHERE id=eventid;
  IF body<>'{}' OR topicname NOT IN ('ingredient.arrived','restaurant.cook') THEN
   RAISE EXCEPTION 'Rules route requires an unambiguous protocol event' USING ERRCODE='42501'; END IF;
 ELSE
  reserve:=octet_length(body::text)+2048;
  money:=ceil(reserve*0.042/1000000*100000000)/100000000;
  SELECT count(*),coalesce(sum(r.reserved_input_tokens),0),coalesce(sum(r.reserved_usd),0)
   INTO calls,tokens,dollars FROM public.restaurant_routes r JOIN public.restaurant_turns t USING(event_id)
   WHERE t.run_id=q.run_id AND t.store=q.store AND r.model IS NOT NULL;
  IF calls>=least((cfg->>'calls_per_run')::integer,64)
   OR tokens+reserve>least((cfg->>'input_tokens_per_run')::integer,128000)
   OR dollars+money>least((cfg->>'usd_limit')::numeric,0.10)
   OR cfg->>'calls_per_run' IS NULL OR cfg->>'input_tokens_per_run' IS NULL OR cfg->>'usd_limit' IS NULL THEN
   RAISE EXCEPTION 'Router allowance exhausted' USING ERRCODE='54000'; END IF;
 END IF;
 INSERT INTO public.restaurant_routes(event_id,request_body,model,reserved_input_tokens,reserved_usd)
 VALUES(eventid,body,CASE WHEN rules THEN NULL ELSE 'jev-1.14.0' END,reserve,money);
END $$;

CREATE FUNCTION public.restaurant_route_complete(eventid bigint,token uuid,attempt integer,turnnonce uuid,
 executorname text,plan jsonb,response jsonb,conf numeric,gap numeric,why text,errorcode text,duration integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE q public.restaurant_turns%ROWTYPE; r public.restaurant_routes%ROWTYPE; cfg jsonb; topicname text;
BEGIN
 q:=public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 SELECT * INTO r FROM public.restaurant_routes WHERE event_id=eventid AND state='pending' FOR UPDATE;
 IF NOT FOUND OR executorname NOT IN ('rules','jev','gemini') OR why IS NULL OR length(why)>240
 OR duration IS NULL OR duration NOT BETWEEN 0 AND 60000 THEN
  RAISE EXCEPTION 'Current bounded route completion required' USING ERRCODE='42501'; END IF;
 SELECT definition->'brain'->'routing' INTO cfg FROM public.agent_bindings WHERE login_role=session_user;
 IF executorname='rules' THEN
  SELECT topic INTO topicname FROM public.events WHERE id=eventid;
  IF r.model IS NOT NULL OR plan->>'action' IS DISTINCT FROM
   (CASE topicname WHEN 'ingredient.arrived' THEN 'receive' WHEN 'restaurant.cook' THEN 'cook' END) THEN
   RAISE EXCEPTION 'Rules cannot choose a judgment action' USING ERRCODE='42501'; END IF;
 ELSIF r.model IS NULL THEN RAISE EXCEPTION 'A committed Jev admission is required' USING ERRCODE='42501';
 END IF;
 IF executorname='jev' AND (errorcode IS NOT NULL OR conf IS NULL OR gap IS NULL
  OR conf<(cfg->>'confidence_threshold')::numeric OR gap<(cfg->>'margin_threshold')::numeric
  OR response IS NULL OR plan IS NULL) THEN
  RAISE EXCEPTION 'Uncertain route cannot bypass Gemini' USING ERRCODE='42501'; END IF;
 IF executorname='gemini' AND plan IS NOT NULL THEN
  RAISE EXCEPTION 'Escalation cannot precommit a plan' USING ERRCODE='42501'; END IF;
 UPDATE public.restaurant_routes SET state='completed',executor=executorname,decision=plan,
  response_body=response,confidence=conf,margin=gap,reason=why,error_code=errorcode,latency_ms=duration,
  input_tokens=CASE WHEN response->'usage'->>'input_tokens' ~ '^[0-9]{1,8}$'
   THEN (response->'usage'->>'input_tokens')::integer END,
  output_tokens=CASE WHEN response->'usage'->>'output_tokens' ~ '^[0-9]{1,8}$'
   THEN (response->'usage'->>'output_tokens')::integer END,completed_at=clock_timestamp()
  WHERE event_id=eventid;
END $$;
REVOKE ALL ON FUNCTION public.restaurant_route_begin(bigint,uuid,integer,uuid,jsonb,boolean),
 public.restaurant_route_complete(bigint,uuid,integer,uuid,text,jsonb,jsonb,numeric,numeric,text,text,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.restaurant_route_begin(bigint,uuid,integer,uuid,jsonb,boolean),
 public.restaurant_route_complete(bigint,uuid,integer,uuid,text,jsonb,jsonb,numeric,numeric,text,text,integer)
 TO lab_restaurant_adk_executor;

ALTER FUNCTION public.restaurant_model_admit(bigint,uuid,integer,uuid,integer,text)
 RENAME TO restaurant_model_admit_preroute;
REVOKE ALL ON FUNCTION public.restaurant_model_admit_preroute(bigint,uuid,integer,uuid,integer,text)
 FROM PUBLIC,lab_restaurant_adk_executor;
CREATE FUNCTION public.restaurant_model_admit(eventid bigint,token uuid,attempt integer,turnnonce uuid,
 requestbytes integer,requesthash text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE cfg jsonb;
BEGIN
 PERFORM public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 SELECT definition->'brain'->'routing' INTO cfg FROM public.agent_bindings WHERE login_role=session_user;
 IF cfg IS NOT NULL AND cfg<>'null' AND NOT EXISTS(SELECT 1 FROM public.restaurant_routes
  WHERE event_id=eventid AND state='completed' AND executor='gemini') THEN
  RAISE EXCEPTION 'Gemini requires an admitted uncertain route' USING ERRCODE='42501'; END IF;
 RETURN public.restaurant_model_admit_preroute(eventid,token,attempt,turnnonce,requestbytes,requesthash);
END $$;
REVOKE ALL ON FUNCTION public.restaurant_model_admit(bigint,uuid,integer,uuid,integer,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.restaurant_model_admit(bigint,uuid,integer,uuid,integer,text)
 TO lab_restaurant_adk_executor;

CREATE OR REPLACE FUNCTION public.restaurant_turn_save(eventid bigint,token uuid,attempt integer,turnnonce uuid,
 plan jsonb,errorcode text DEFAULT NULL) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 PERFORM public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 IF errorcode IS NOT NULL THEN
  UPDATE public.restaurant_turns SET state='failed',error_code=left(errorcode,80) WHERE event_id=eventid;RETURN;
 END IF;
 IF plan IS NULL OR jsonb_typeof(plan)<>'object' OR octet_length(plan::text)>4096
 OR NOT(plan ?& ARRAY['action','supplier','substitute','reason','summary'])
 OR EXISTS(SELECT 1 FROM jsonb_object_keys(plan) k WHERE k NOT IN ('action','supplier','substitute','reason','summary'))
 OR (NOT EXISTS(SELECT 1 FROM public.restaurant_model_calls WHERE event_id=eventid) AND NOT EXISTS(SELECT 1 FROM public.restaurant_routes r WHERE r.event_id=eventid AND r.state='completed' AND r.executor IN ('rules','jev') AND r.decision=plan))
 OR EXISTS(SELECT 1 FROM public.restaurant_model_calls WHERE event_id=eventid AND state<>'completed')
 OR jsonb_typeof(plan->'summary')<>'string' OR length(plan->>'summary') NOT BETWEEN 1 AND 500
 OR NOT EXISTS(SELECT 1 FROM public.restaurant_tool_receipts WHERE event_id=eventid AND tool='restaurant.finish'
  AND result->'arguments'->>'summary'=plan->>'summary')
 OR NOT EXISTS(SELECT 1 FROM public.restaurant_tool_receipts WHERE event_id=eventid AND tool=
  CASE plan->>'action' WHEN 'source' THEN 'restaurant.request_supply' WHEN 'confirm' THEN 'restaurant.confirm'
   WHEN 'receive' THEN 'restaurant.receive' WHEN 'cook' THEN 'restaurant.cook'
   WHEN 'offer' THEN 'restaurant.offer' WHEN 'decline' THEN 'restaurant.decline' END
  AND CASE plan->>'action' WHEN 'source' THEN result->'arguments'->>'supplier'=plan->>'supplier'
   WHEN 'offer' THEN result->'arguments'->>'substitute'=plan->>'substitute'
   WHEN 'decline' THEN result->'arguments'->>'reason'=plan->>'reason' ELSE true END) THEN
  RAISE EXCEPTION 'Completed bounded restaurant decision required' USING ERRCODE='23514'; END IF;
 UPDATE public.restaurant_turns SET state='succeeded',result=plan WHERE event_id=eventid;
END $$;

