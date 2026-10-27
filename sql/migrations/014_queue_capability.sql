-- Agent logins cannot manufacture leases, reset tool charges, or inspect decisions.
-- All queue mutations derive their namespace and role from session_user.
REVOKE INSERT,UPDATE ON public.events FROM lab_inventory_executor,lab_fulfillment_executor,
 lab_dispatch_executor,lab_courier_executor,lab_judge_executor,lab_supply_executor;
REVOKE UPDATE(state,lease_token,lease_until,attempts,error,available_at,completed_at)
 ON public.events FROM lab_supply_executor;
REVOKE UPDATE(observed_tools) ON public.agent_event_budgets FROM lab_inventory_executor,
 lab_fulfillment_executor,lab_dispatch_executor,lab_courier_executor,lab_judge_executor,lab_supply_executor;
REVOKE SELECT ON public.decisions FROM lab_inventory_executor,lab_fulfillment_executor,
 lab_dispatch_executor,lab_courier_executor,lab_judge_executor,lab_supply_executor;

CREATE FUNCTION public.agent_queue_claim(rolename text,runid uuid,topics text[],leaseseconds double precision)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; e public.events%ROWTYPE; sim integer;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND OR b.run_id IS DISTINCT FROM runid OR b.definition->>'role' IS DISTINCT FROM rolename
 OR topics IS NULL OR cardinality(topics)=0 OR EXISTS(SELECT 1 FROM unnest(topics) t(topic)
  WHERE t.topic IS NULL OR NOT(coalesce(b.definition->'accepts','[]'::jsonb) ? t.topic))
 OR leaseseconds IS NULL OR NOT(leaseseconds>0 AND leaseseconds<=300) THEN
  RAISE EXCEPTION 'Queue claim exceeds authenticated role' USING ERRCODE='42501'; END IF;
 SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
 UPDATE public.events SET state='dead',error='lease_expired_after_max_attempts',lease_token=NULL,lease_until=NULL
 WHERE run_id=b.run_id AND target_store=b.store AND b.definition->'accepts' ? topic
 AND state='leased' AND lease_until<clock_timestamp() AND attempts>=max_attempts;
 WITH candidate AS (
  SELECT id FROM public.events WHERE run_id=b.run_id AND target_store=b.store AND topic=ANY(topics)
  AND b.definition->'accepts' ? topic AND due_sim<=sim AND available_at<=clock_timestamp()
  AND attempts<max_attempts AND (state='ready' OR (state='leased' AND lease_until<clock_timestamp()))
  ORDER BY priority DESC,due_sim,id FOR UPDATE SKIP LOCKED LIMIT 1
 ) UPDATE public.events q SET state='leased',lease_token=gen_random_uuid(),
  lease_until=clock_timestamp()+leaseseconds*interval '1 second',attempts=attempts+1
 FROM candidate c WHERE q.id=c.id RETURNING q.* INTO e;
 IF NOT FOUND THEN RETURN NULL; END IF;
 RETURN to_jsonb(e);
END $$;

CREATE FUNCTION public.agent_queue_lock(eventid bigint,token uuid,eventattempt integer)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; e public.events%ROWTYPE;
BEGIN
 IF eventid IS NULL OR token IS NULL OR eventattempt IS NULL OR eventattempt<1 THEN RETURN false; END IF;
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND THEN RETURN false; END IF;
 -- Validate the deadline after acquiring the row, including time spent waiting.
 SELECT * INTO e FROM public.events WHERE id=eventid AND run_id=b.run_id AND target_store=b.store
 AND coalesce(b.definition->'accepts','[]'::jsonb) ? topic FOR UPDATE;
 RETURN FOUND AND e.state='leased' AND e.lease_token IS NOT DISTINCT FROM token
  AND e.attempts=eventattempt AND e.lease_until IS NOT NULL AND e.lease_until>clock_timestamp();
END $$;

CREATE FUNCTION public.agent_consume_tool(eventid bigint,token uuid,eventattempt integer,toolname text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; charged integer;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND OR toolname IS NULL OR NOT(coalesce(b.definition->'tools','[]'::jsonb) ? toolname)
 OR NOT public.agent_queue_lock(eventid,token,eventattempt) THEN RETURN false; END IF;
 UPDATE public.agent_event_budgets SET observed_tools=observed_tools+1
 WHERE event_id=eventid AND attempt=eventattempt AND run_id=b.run_id AND store=b.store AND observed_tools<slots
 RETURNING observed_tools INTO charged;
 RETURN FOUND AND public.agent_queue_lock(eventid,token,eventattempt);
END $$;

CREATE FUNCTION public.agent_queue_ack(eventid bigint,token uuid,eventattempt integer)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN RETURN false; END IF;
 UPDATE public.events SET state='done',completed_at=now(),lease_token=NULL,lease_until=NULL
 WHERE id=eventid AND state='leased' AND lease_token=token AND attempts=eventattempt
 AND lease_until>clock_timestamp();
 RETURN FOUND;
END $$;

CREATE FUNCTION public.agent_queue_fail(eventid bigint,token uuid,eventattempt integer,errorcode text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN RETURN false; END IF;
 UPDATE public.events SET state=CASE WHEN attempts>=max_attempts THEN 'dead' ELSE 'ready' END,
  error=left(coalesce(errorcode,'WorkerError'),80),lease_token=NULL,lease_until=NULL,
  available_at=clock_timestamp()+least(30,power(2,least(5,
   greatest(0,attempts-greatest(0,max_attempts-3)-1))))*interval '1 second'
 WHERE id=eventid AND state='leased' AND lease_token=token AND attempts=eventattempt
 AND lease_until>clock_timestamp();
 RETURN FOUND;
END $$;

CREATE FUNCTION public.agent_queue_publish(eventid bigint,token uuid,eventattempt integer,topicname text,
 body jsonb,dedupe text,due integer,eventpriority integer,capacity integer)
RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; e public.events%ROWTYPE; prior public.events%ROWTYPE;
 destination text; newid bigint; contextid text;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND OR topicname IS NULL OR NOT(coalesce(b.definition->'emits','[]'::jsonb) ? topicname) THEN
  RAISE EXCEPTION 'Publishing exceeds authenticated role' USING ERRCODE='42501'; END IF;
 -- Match Queue.process lock order even for direct authenticated SQL calls.
 PERFORM pg_advisory_xact_lock(hashtextextended(b.run_id::text,0));
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN
  RAISE EXCEPTION 'Publishing requires an active own incoming lease' USING ERRCODE='42501'; END IF;
 IF body IS NULL OR jsonb_typeof(body)<>'object' OR octet_length(body::text)>65536
 OR dedupe IS NULL OR length(dedupe) NOT BETWEEN 1 AND 512 OR due IS NULL OR due<0
 OR eventpriority IS NULL OR eventpriority NOT BETWEEN -1000 AND 1000 THEN
  RAISE EXCEPTION 'Invalid queue message' USING ERRCODE='22023'; END IF;
 IF body ?| ARRAY['run','run_id','store','owner','namespace','agent_id'] THEN
  RAISE EXCEPTION 'Outgoing scope is authenticated' USING ERRCODE='42501'; END IF;
 IF NOT public.agent_consume_tool(eventid,token,eventattempt,'queue.publish') THEN
  RAISE EXCEPTION 'Reserved publish tool slot required' USING ERRCODE='42501'; END IF;
 SELECT * INTO e FROM public.events WHERE id=eventid;
 contextid:=coalesce(e.payload->>'order',e.payload->>'basket');
 IF (body ? 'basket' AND body->>'basket' IS DISTINCT FROM contextid)
 OR (body ? 'order' AND body->>'order' IS DISTINCT FROM contextid) THEN
  RAISE EXCEPTION 'Outgoing order differs from incoming lease' USING ERRCODE='42501'; END IF;
 IF body ? 'shipment' AND body->>'shipment' IS DISTINCT FROM e.payload->>'shipment' THEN
  RAISE EXCEPTION 'Outgoing shipment differs from incoming lease' USING ERRCODE='42501'; END IF;
 destination:=public.agent_destination(topicname,body);
 IF destination IS NULL THEN RAISE EXCEPTION 'Invalid queue destination' USING ERRCODE='42501'; END IF;
 IF NOT public.agent_queue_lock(eventid,token,eventattempt) THEN
  RAISE EXCEPTION 'Publish lease expired while waiting' USING ERRCODE='42501'; END IF;
 SELECT * INTO prior FROM public.events WHERE run_id=b.run_id AND topic=topicname AND dedupe_key=dedupe;
 IF FOUND THEN
  IF prior.target_store IS DISTINCT FROM destination OR prior.producer IS DISTINCT FROM b.definition->>'role' THEN
   RAISE EXCEPTION 'Dedupe key belongs to another queue scope' USING ERRCODE='42501'; END IF;
  RETURN prior.id;
 END IF;
 IF (SELECT count(*) FROM public.events WHERE run_id=b.run_id AND state IN ('ready','leased'))
 >=greatest(1,least(coalesce(capacity,1),10000)) THEN
  RAISE EXCEPTION 'Queue capacity reached' USING ERRCODE='54000'; END IF;
 INSERT INTO public.events(run_id,producer,topic,payload,dedupe_key,trace_id,due_sim,priority,
  parent_id,target_store,available_at)
 VALUES(b.run_id,b.definition->>'role',topicname,body,dedupe,e.trace_id,due,eventpriority,
  eventid,destination,'1970-01-01 UTC') RETURNING id INTO newid;
 RETURN newid;
END $$;

REVOKE ALL ON FUNCTION public.agent_queue_claim(text,uuid,text[],double precision),
 public.agent_queue_lock(bigint,uuid,integer),public.agent_consume_tool(bigint,uuid,integer,text),
 public.agent_queue_ack(bigint,uuid,integer),public.agent_queue_fail(bigint,uuid,integer,text),
 public.agent_queue_publish(bigint,uuid,integer,text,jsonb,text,integer,integer,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agent_queue_claim(text,uuid,text[],double precision),
 public.agent_queue_lock(bigint,uuid,integer),public.agent_consume_tool(bigint,uuid,integer,text),
 public.agent_queue_ack(bigint,uuid,integer),public.agent_queue_fail(bigint,uuid,integer,text),
 public.agent_queue_publish(bigint,uuid,integer,text,jsonb,text,integer,integer,integer)
 TO lab_inventory_executor,lab_fulfillment_executor,lab_dispatch_executor,lab_courier_executor,
 lab_judge_executor,lab_supply_executor;
