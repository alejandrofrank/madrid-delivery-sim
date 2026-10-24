-- Model allowances are separate from deterministic tool tickets and charged before I/O.
CREATE TABLE public.agent_model_calls (
 run_id uuid NOT NULL REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 store text NOT NULL, event_id bigint NOT NULL REFERENCES public.events(id) ON DELETE CASCADE, attempt integer NOT NULL,
 reserved_tokens integer NOT NULL DEFAULT 8448,
 status text NOT NULL DEFAULT 'reserved', detail jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), PRIMARY KEY(event_id,attempt)
);
REVOKE ALL ON public.agent_model_calls FROM PUBLIC;
CREATE FUNCTION public.agent_reserve_model(eventid bigint, token uuid, attemptid integer) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; calls integer; tokens bigint;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'judge' OR b.definition->>'policy' IS DISTINCT FROM 'gcp_ai' THEN
  RAISE EXCEPTION 'Cloud judge binding required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(b.run_id::text,0));
 IF NOT EXISTS(SELECT 1 FROM public.events e WHERE e.id=eventid AND e.run_id=b.run_id
  AND e.target_store=b.store AND e.topic='delivery.failed' AND e.state='leased'
  AND e.lease_token=token AND e.attempts=attemptid AND e.lease_until>clock_timestamp())
  OR NOT EXISTS(SELECT 1 FROM public.agent_event_budgets t WHERE t.event_id=eventid AND t.attempt=attemptid)
 THEN RAISE EXCEPTION 'Active scoped event ticket required' USING ERRCODE='42501'; END IF;
 -- A consumed ticket is never reused, even if a worker crashed after the request.
 IF EXISTS(SELECT 1 FROM public.agent_model_calls WHERE event_id=eventid AND attempt=attemptid) THEN RETURN false; END IF;
 SELECT count(*),coalesce(sum(reserved_tokens),0)
 INTO calls,tokens FROM public.agent_model_calls WHERE run_id=b.run_id;
 IF calls+1>least(100,(b.definition->'limits'->>'model_calls')::integer)
 OR tokens+8448>least(844800,(b.definition->'limits'->>'model_tokens')::integer) THEN RETURN false; END IF;
 INSERT INTO public.agent_model_calls(run_id,store,event_id,attempt) VALUES(b.run_id,b.store,eventid,attemptid);
 RETURN true;
END $$;
CREATE FUNCTION public.agent_record_model(eventid bigint, attemptid integer, outcome jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'judge' OR b.definition->>'policy' IS DISTINCT FROM 'gcp_ai'
 OR jsonb_typeof(outcome)<>'object' OR octet_length(outcome::text)>4096 THEN
 RAISE EXCEPTION 'Invalid cloud audit' USING ERRCODE='42501'; END IF;
 UPDATE public.agent_model_calls SET status='completed',detail=outcome WHERE event_id=eventid
 AND attempt=attemptid AND run_id=b.run_id AND store=b.store AND status='reserved';
 IF NOT FOUND THEN RAISE EXCEPTION 'Reserved cloud call required'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.agent_reserve_model(bigint,uuid,integer),public.agent_record_model(bigint,integer,jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agent_reserve_model(bigint,uuid,integer),public.agent_record_model(bigint,integer,jsonb) TO lab_judge_executor;
CREATE FUNCTION public.agent_model_reserved(eventid bigint, token uuid, attemptid integer) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT EXISTS(SELECT 1 FROM public.agent_model_calls m JOIN public.agent_bindings b
 ON b.run_id=m.run_id AND b.store=m.store JOIN public.events e ON e.id=m.event_id
 WHERE b.login_role=session_user AND b.definition->>'policy'='gcp_ai'
 AND m.event_id=eventid AND m.attempt=attemptid AND m.status='reserved'
 AND e.state='leased' AND e.lease_token=token AND e.lease_until>clock_timestamp())
$$;
REVOKE ALL ON FUNCTION public.agent_model_reserved(bigint,uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agent_model_reserved(bigint,uuid,integer) TO lab_judge_executor;
