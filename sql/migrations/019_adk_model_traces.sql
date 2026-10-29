-- Operator evidence is private. Agents can only append to their admitted live turn.
ALTER TABLE public.restaurant_model_calls
 ADD COLUMN request_body jsonb,
 ADD COLUMN response_body jsonb,
 ADD COLUMN started_at timestamptz,
 ADD COLUMN completed_at timestamptz,
 ADD COLUMN latency_ms integer CHECK(latency_ms BETWEEN 0 AND 300000),
 ADD CHECK(request_body IS NULL OR octet_length(request_body::text)<=65536),
 ADD CHECK(response_body IS NULL OR octet_length(response_body::text)<=65536);
ALTER TABLE public.restaurant_tool_receipts ADD COLUMN created_at timestamptz NOT NULL DEFAULT clock_timestamp();

CREATE FUNCTION public.restaurant_model_trace(eventid bigint,token uuid,attempt integer,turnnonce uuid,
 modelstep integer,requestbody jsonb,responsebody jsonb,latency integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 PERFORM public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 IF requestbody IS NOT NULL AND responsebody IS NULL AND latency IS NULL
 AND jsonb_typeof(requestbody)='object' THEN
  UPDATE public.restaurant_model_calls SET request_body=requestbody,started_at=clock_timestamp()
   WHERE event_id=eventid AND step=modelstep AND state='in_flight' AND request_body IS NULL;
 ELSIF requestbody IS NULL AND responsebody IS NOT NULL AND jsonb_typeof(responsebody)='object'
 AND latency BETWEEN 0 AND 300000 THEN
  UPDATE public.restaurant_model_calls SET response_body=responsebody,latency_ms=latency,completed_at=clock_timestamp()
   WHERE event_id=eventid AND step=modelstep AND state='in_flight' AND request_body IS NOT NULL AND response_body IS NULL;
 ELSE RAISE EXCEPTION 'Invalid trace phase' USING ERRCODE='42501'; END IF;
 IF NOT FOUND THEN RAISE EXCEPTION 'Current admitted dispatch required' USING ERRCODE='42501'; END IF;
END $$;
REVOKE ALL ON FUNCTION public.restaurant_model_trace(bigint,uuid,integer,uuid,integer,jsonb,jsonb,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.restaurant_model_trace(bigint,uuid,integer,uuid,integer,jsonb,jsonb,integer)
 TO lab_restaurant_adk_executor;
