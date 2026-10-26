-- Relevance search uses the same authenticated namespace as domain commands.
-- Provider reservations commit before network I/O and are never refunded.
ALTER TABLE public.supply_orders
 DROP CONSTRAINT supply_orders_run_id_household_fkey,
 DROP CONSTRAINT supply_orders_run_id_restaurant_fkey,
 ADD FOREIGN KEY(run_id,household) REFERENCES public.supply_entities(run_id,id) ON DELETE CASCADE,
 ADD FOREIGN KEY(run_id,restaurant) REFERENCES public.supply_entities(run_id,id) ON DELETE CASCADE;
ALTER TABLE public.supply_requests
 DROP CONSTRAINT supply_requests_run_id_restaurant_fkey,
 DROP CONSTRAINT supply_requests_run_id_market_fkey,
 ADD FOREIGN KEY(run_id,restaurant) REFERENCES public.supply_entities(run_id,id) ON DELETE CASCADE,
 ADD FOREIGN KEY(run_id,market) REFERENCES public.supply_entities(run_id,id) ON DELETE CASCADE;
ALTER TABLE public.supply_facts DROP CONSTRAINT supply_facts_event_id_fkey,
 ADD FOREIGN KEY(event_id) REFERENCES public.events(id) ON DELETE CASCADE;

CREATE TABLE public.supply_search_tickets (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id uuid NOT NULL REFERENCES public.supply_sessions(run_id) ON DELETE CASCADE,
 owner text NOT NULL, event_id bigint NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
 attempt integer NOT NULL, lease_token uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(run_id,owner) REFERENCES public.supply_entities(run_id,id) ON DELETE CASCADE
);
CREATE TABLE public.supply_search_budgets (
 run_id uuid NOT NULL, owner text NOT NULL, calls_reserved integer NOT NULL DEFAULT 0 CHECK(calls_reserved>=0),
 input_tokens_reserved bigint NOT NULL DEFAULT 0 CHECK(input_tokens_reserved>=0),
 input_tokens_overrun bigint NOT NULL DEFAULT 0 CHECK(input_tokens_overrun>=0), PRIMARY KEY(run_id,owner),
 FOREIGN KEY(run_id,owner) REFERENCES public.supply_entities(run_id,id) ON DELETE CASCADE
);
CREATE TABLE public.supply_search_calls (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 search_id bigint NOT NULL REFERENCES public.supply_search_tickets(id) ON DELETE CASCADE,
 run_id uuid NOT NULL, owner text NOT NULL, event_id bigint NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
 model text NOT NULL, reserved_input_tokens integer NOT NULL CHECK(reserved_input_tokens BETWEEN 1 AND 51200),
 status text NOT NULL DEFAULT 'reserved' CHECK(status IN ('reserved','ok','error')),
 actual_input_tokens bigint, actual_output_tokens bigint, charged_input_tokens bigint NOT NULL,
 error text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(), completed_at timestamptz,
 FOREIGN KEY(run_id,owner) REFERENCES public.supply_entities(run_id,id) ON DELETE CASCADE
);
CREATE TABLE public.supply_search_cache (
 run_id uuid NOT NULL, owner text NOT NULL, key text NOT NULL,
 body jsonb NOT NULL, expires_at timestamptz NOT NULL, PRIMARY KEY(run_id,owner,key),
 FOREIGN KEY(run_id,owner) REFERENCES public.supply_entities(run_id,id) ON DELETE CASCADE
);
CREATE TABLE public.supply_search_audits (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 search_id bigint NOT NULL UNIQUE REFERENCES public.supply_search_tickets(id) ON DELETE CASCADE,
 run_id uuid NOT NULL, owner text NOT NULL, event_id bigint NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
 query text NOT NULL, mode text NOT NULL CHECK(mode IN ('local','jev')), model text,
 detail jsonb NOT NULL, duration_ms numeric NOT NULL CHECK(duration_ms>=0),
 reserved_calls integer NOT NULL, reserved_input_tokens bigint NOT NULL, charged_input_tokens bigint NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 FOREIGN KEY(run_id,owner) REFERENCES public.supply_entities(run_id,id) ON DELETE CASCADE
);
CREATE INDEX supply_search_calls_scope ON public.supply_search_calls(run_id,owner,search_id);
REVOKE ALL ON public.supply_search_tickets,public.supply_search_budgets,public.supply_search_calls,
 public.supply_search_cache,public.supply_search_audits FROM PUBLIC,lab_supply_executor;

CREATE FUNCTION public.supply_search_scope(eventid bigint,token uuid,eventattempt integer,
 searchid bigint DEFAULT NULL,live boolean DEFAULT true) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; e public.events%ROWTYPE; entity jsonb; cfg jsonb; sim integer;
BEGIN
 IF eventid IS NULL OR token IS NULL OR eventattempt IS NULL OR eventattempt<1 THEN
  RAISE EXCEPTION 'A complete search event lease is required' USING ERRCODE='42501'; END IF;
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND OR b.definition->>'role' NOT IN ('restaurant','market') OR
 NOT(coalesce(b.definition->'tools','[]'::jsonb) ? 'supply.search') THEN
  RAISE EXCEPTION 'Forbidden supply search role' USING ERRCODE='42501'; END IF;
 SELECT * INTO e FROM public.events WHERE id=eventid AND run_id=b.run_id AND target_store=b.store
  AND b.definition->'accepts' ? topic;
 IF NOT FOUND OR (live AND (e.state<>'leased' OR e.lease_token IS DISTINCT FROM token
  OR e.attempts<>eventattempt OR e.lease_until IS NULL OR e.lease_until<=clock_timestamp())) THEN
  RAISE EXCEPTION 'Active own search event lease required' USING ERRCODE='42501'; END IF;
 IF searchid IS NOT NULL AND NOT EXISTS(SELECT 1 FROM public.supply_search_tickets t
  WHERE t.id=searchid AND t.run_id=b.run_id AND t.owner=b.store AND t.event_id=eventid
  AND t.attempt=eventattempt AND t.lease_token=token) THEN
  RAISE EXCEPTION 'Unknown scoped search ticket' USING ERRCODE='42501'; END IF;
 SELECT definition INTO entity FROM public.supply_entities WHERE run_id=b.run_id AND id=b.store AND kind=b.definition->>'role';
 SELECT config INTO cfg FROM public.supply_sessions WHERE run_id=b.run_id;
 SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
 IF entity IS NULL OR cfg IS NULL THEN RAISE EXCEPTION 'Unknown search entity' USING ERRCODE='42501'; END IF;
 RETURN jsonb_build_object('run_id',b.run_id,'owner',b.store,'sim',sim,'settings',
  coalesce((coalesce(nullif(entity->'agent','null'::jsonb),cfg->'agents'->(b.definition->>'role')))->'search',
  '{"provider":"local","calls_limit":0,"input_tokens_limit":0}'::jsonb));
END $$;

CREATE FUNCTION public.supply_search_begin(eventid bigint,token uuid,eventattempt integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; searchid bigint; stock jsonb; candidates jsonb;
BEGIN
 scope:=public.supply_search_scope(eventid,token,eventattempt);
 UPDATE public.agent_event_budgets SET observed_tools=observed_tools+1
 WHERE event_id=eventid AND attempt=eventattempt AND run_id=(scope->>'run_id')::uuid
 AND store=scope->>'owner' AND observed_tools<slots;
 IF NOT FOUND THEN RAISE EXCEPTION 'Reserved search tool slot required' USING ERRCODE='42501'; END IF;
 INSERT INTO public.supply_search_tickets(run_id,owner,event_id,attempt,lease_token)
 VALUES((scope->>'run_id')::uuid,scope->>'owner',eventid,eventattempt,token) RETURNING id INTO searchid;
 SELECT coalesce(jsonb_agg(jsonb_build_object('id',ingredient,'name',initcap(replace(ingredient,'-',' ')),'unit',unit)
  ORDER BY ingredient),'[]'::jsonb),coalesce(jsonb_object_agg(ingredient,
  jsonb_build_object('available',on_hand-reserved,'version',version,'unit',unit)),'{}'::jsonb)
 INTO candidates,stock FROM public.supply_stock WHERE run_id=(scope->>'run_id')::uuid AND owner=scope->>'owner';
 RETURN scope-'owner'-'run_id'||jsonb_build_object('search_id',searchid,'candidates',candidates,'stock_by_id',stock);
END $$;

CREATE FUNCTION public.supply_search_admit(searchid bigint,eventid bigint,token uuid,eventattempt integer,
 modelname text,inputbound integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; budget public.supply_search_budgets%ROWTYPE; callid bigint; callcap integer; tokencap integer;
BEGIN
 scope:=public.supply_search_scope(eventid,token,eventattempt,searchid,true);
 IF scope->'settings'->>'provider' IS DISTINCT FROM 'jev' OR modelname IS NULL
 OR modelname !~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$' OR inputbound IS NULL OR inputbound NOT BETWEEN 1 AND 51200 THEN
  RAISE EXCEPTION 'Search provider admission denied' USING ERRCODE='42501'; END IF;
 callcap:=greatest(0,least(coalesce((scope->'settings'->>'calls_limit')::integer,0),8));
 tokencap:=greatest(0,least(coalesce((scope->'settings'->>'input_tokens_limit')::integer,0),51200));
 INSERT INTO public.supply_search_budgets(run_id,owner) VALUES((scope->>'run_id')::uuid,scope->>'owner') ON CONFLICT DO NOTHING;
 SELECT * INTO budget FROM public.supply_search_budgets WHERE run_id=(scope->>'run_id')::uuid AND owner=scope->>'owner' FOR UPDATE;
 IF budget.calls_reserved>=callcap OR budget.input_tokens_reserved+budget.input_tokens_overrun+inputbound>tokencap THEN
  RETURN jsonb_build_object('admitted',false); END IF;
 UPDATE public.supply_search_budgets SET calls_reserved=calls_reserved+1,input_tokens_reserved=input_tokens_reserved+inputbound
 WHERE run_id=budget.run_id AND owner=budget.owner;
 INSERT INTO public.supply_search_calls(search_id,run_id,owner,event_id,model,reserved_input_tokens,charged_input_tokens)
 VALUES(searchid,budget.run_id,budget.owner,eventid,modelname,inputbound,inputbound) RETURNING id INTO callid;
 RETURN jsonb_build_object('admitted',true,'admission_id',callid,'reserved_input_tokens',inputbound);
END $$;

CREATE FUNCTION public.supply_search_record(searchid bigint,callid bigint,eventid bigint,token uuid,
 eventattempt integer,usage jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; callrow public.supply_search_calls%ROWTYPE; actualin bigint; actualout bigint;
 statusname text; errorcode text; charge bigint;
BEGIN
 scope:=public.supply_search_scope(eventid,token,eventattempt,searchid,false);
 SELECT * INTO callrow FROM public.supply_search_calls WHERE id=callid AND search_id=searchid
 AND run_id=(scope->>'run_id')::uuid AND owner=scope->>'owner' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown scoped admission' USING ERRCODE='42501'; END IF;
 IF callrow.status<>'reserved' THEN RETURN jsonb_build_object('recorded',true,'status',callrow.status); END IF;
 IF usage->>'model' IS DISTINCT FROM callrow.model OR usage->>'status' NOT IN ('ok','error') THEN
  RAISE EXCEPTION 'Invalid search accounting'; END IF;
 IF usage->>'input_tokens' IS NOT NULL THEN
  IF jsonb_typeof(usage->'input_tokens')<>'number' OR usage->>'input_tokens' !~ '^[0-9]{1,10}$' THEN RAISE EXCEPTION 'Invalid actual input usage'; END IF;
  actualin:=(usage->>'input_tokens')::bigint;
  IF actualin>1000000000 THEN RAISE EXCEPTION 'Invalid actual input usage'; END IF;
 END IF;
 IF usage->>'output_tokens' IS NOT NULL THEN
  IF jsonb_typeof(usage->'output_tokens')<>'number' OR usage->>'output_tokens' !~ '^[0-9]{1,10}$' THEN RAISE EXCEPTION 'Invalid actual output usage'; END IF;
  actualout:=(usage->>'output_tokens')::bigint;
  IF actualout>1000000000 THEN RAISE EXCEPTION 'Invalid actual output usage'; END IF;
 END IF;
 statusname:=CASE WHEN usage->>'status'='ok' AND actualin IS NOT NULL AND actualin<=callrow.reserved_input_tokens THEN 'ok' ELSE 'error' END;
 errorcode:=CASE WHEN usage->>'error' IN ('provider_timeout','provider_schema_invalid','provider_error','provider_http_error',
 'provider_network','provider_content_type','provider_response_too_large','provider_json_invalid','provider_answer_ids_or_model_invalid',
 'provider_answer_ids_invalid','model_mismatch','usage_exceeds_reservation','query_deadline_exceeded','budget_record_failed') THEN usage->>'error'
 WHEN statusname='error' THEN 'provider_error' ELSE NULL END;
 charge:=CASE WHEN statusname='ok' THEN actualin ELSE greatest(callrow.reserved_input_tokens,coalesce(actualin,0)) END;
 UPDATE public.supply_search_calls SET status=statusname,actual_input_tokens=actualin,actual_output_tokens=actualout,
 charged_input_tokens=charge,error=errorcode,completed_at=clock_timestamp() WHERE id=callid;
 UPDATE public.supply_search_budgets SET input_tokens_overrun=input_tokens_overrun+greatest(0,coalesce(actualin,0)-callrow.reserved_input_tokens)
 WHERE run_id=callrow.run_id AND owner=callrow.owner;
 RETURN jsonb_build_object('recorded',true,'status',statusname,'charged_input_tokens',charge);
END $$;

CREATE FUNCTION public.supply_search_cache_get(searchid bigint,eventid bigint,token uuid,eventattempt integer,cachekey text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; result jsonb;
BEGIN
 scope:=public.supply_search_scope(eventid,token,eventattempt,searchid,true);
 SELECT body INTO result FROM public.supply_search_cache WHERE run_id=(scope->>'run_id')::uuid
 AND owner=scope->>'owner' AND key=cachekey AND expires_at>clock_timestamp();
 RETURN result;
END $$;
CREATE FUNCTION public.supply_search_cache_put(searchid bigint,eventid bigint,token uuid,eventattempt integer,cachekey text,body jsonb)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; expiry timestamptz;
BEGIN
 scope:=public.supply_search_scope(eventid,token,eventattempt,searchid,true);
 IF cachekey IS NULL OR cachekey !~ '^supply-search:v1:[a-f0-9]{64}$' OR jsonb_typeof(body)<>'object'
 OR NOT(body ?& ARRAY['choice','confidence','model','expires_at'])
 OR body-ARRAY['choice','confidence','model','expires_at']<>'{}'::jsonb OR coalesce(body->>'choice','') NOT IN ('yes','no')
 OR jsonb_typeof(body->'confidence')<>'number' OR jsonb_typeof(body->'expires_at')<>'number' THEN
  RAISE EXCEPTION 'Invalid relevance cache value'; END IF;
 IF (body->>'confidence')::numeric NOT BETWEEN 0 AND 1 THEN RAISE EXCEPTION 'Invalid relevance confidence'; END IF;
 expiry:=to_timestamp((body->>'expires_at')::double precision);
 IF expiry<=clock_timestamp() OR expiry>clock_timestamp()+interval '1 day' OR NOT EXISTS(
  SELECT 1 FROM public.supply_search_calls WHERE search_id=searchid AND status='ok' AND model=body->>'model') THEN
  RAISE EXCEPTION 'Cache requires a successful scoped relevance review'; END IF;
 INSERT INTO public.supply_search_cache(run_id,owner,key,body,expires_at)
 VALUES((scope->>'run_id')::uuid,scope->>'owner',cachekey,body,expiry)
 ON CONFLICT(run_id,owner,key) DO UPDATE SET body=excluded.body,expires_at=excluded.expires_at;
 RETURN true;
END $$;

CREATE FUNCTION public.supply_search_stock(searchid bigint,eventid bigint,token uuid,eventattempt integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; stock jsonb;
BEGIN
 scope:=public.supply_search_scope(eventid,token,eventattempt,searchid,true);
 SELECT coalesce(jsonb_object_agg(ingredient,jsonb_build_object('available',on_hand-reserved,'version',version,'unit',unit)),'{}'::jsonb)
 INTO stock FROM public.supply_stock WHERE run_id=(scope->>'run_id')::uuid AND owner=scope->>'owner';
 RETURN jsonb_build_object('sim',scope->'sim','stock_by_id',stock,'observed_at',clock_timestamp());
END $$;

CREATE FUNCTION public.supply_search_finish(searchid bigint,eventid bigint,token uuid,eventattempt integer,
 querytext text,modename text,modelname text,result jsonb,duration numeric) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; auditid bigint; calls integer; reserved bigint; charged bigint;
BEGIN
 scope:=public.supply_search_scope(eventid,token,eventattempt,searchid,false);
 IF querytext IS NULL OR length(querytext) NOT BETWEEN 1 AND 80 OR modename NOT IN ('local','jev')
 OR jsonb_typeof(result)<>'object' OR octet_length(result::text)>65536 OR duration IS NULL OR duration NOT BETWEEN 0 AND 60000 THEN
  RAISE EXCEPTION 'Invalid search audit'; END IF;
 SELECT count(*),coalesce(sum(reserved_input_tokens),0),coalesce(sum(charged_input_tokens),0)
 INTO calls,reserved,charged FROM public.supply_search_calls WHERE search_id=searchid;
 INSERT INTO public.supply_search_audits(search_id,run_id,owner,event_id,query,mode,model,detail,duration_ms,
 reserved_calls,reserved_input_tokens,charged_input_tokens)
 VALUES(searchid,(scope->>'run_id')::uuid,scope->>'owner',eventid,querytext,modename,modelname,result,duration,calls,reserved,charged)
 ON CONFLICT(search_id) DO NOTHING RETURNING id INTO auditid;
 IF NOT FOUND THEN SELECT id INTO auditid FROM public.supply_search_audits WHERE search_id=searchid; END IF;
 RETURN auditid;
END $$;

REVOKE ALL ON FUNCTION public.supply_search_scope(bigint,uuid,integer,bigint,boolean),
 public.supply_search_begin(bigint,uuid,integer),public.supply_search_admit(bigint,bigint,uuid,integer,text,integer),
 public.supply_search_record(bigint,bigint,bigint,uuid,integer,jsonb),public.supply_search_cache_get(bigint,bigint,uuid,integer,text),
 public.supply_search_cache_put(bigint,bigint,uuid,integer,text,jsonb),public.supply_search_stock(bigint,bigint,uuid,integer),
 public.supply_search_finish(bigint,bigint,uuid,integer,text,text,text,jsonb,numeric) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.supply_search_begin(bigint,uuid,integer),
 public.supply_search_admit(bigint,bigint,uuid,integer,text,integer),public.supply_search_record(bigint,bigint,bigint,uuid,integer,jsonb),
 public.supply_search_cache_get(bigint,bigint,uuid,integer,text),public.supply_search_cache_put(bigint,bigint,uuid,integer,text,jsonb),
 public.supply_search_stock(bigint,bigint,uuid,integer),public.supply_search_finish(bigint,bigint,uuid,integer,text,text,text,jsonb,numeric)
 TO lab_supply_executor;
