-- Observability metadata carries no queue authority. Only a current lease may
-- update its parent, and SQL-created descendants inherit the same order context.
ALTER TABLE public.events ADD COLUMN traceparent text
 CHECK (traceparent IS NULL OR traceparent ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$');

CREATE FUNCTION public.inherit_event_traceparent() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF NEW.traceparent IS NULL AND NEW.parent_id IS NOT NULL THEN
  SELECT traceparent INTO NEW.traceparent FROM public.events
  WHERE id=NEW.parent_id AND run_id=NEW.run_id AND trace_id=NEW.trace_id;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.inherit_event_traceparent() FROM PUBLIC;
CREATE TRIGGER events_traceparent BEFORE INSERT ON public.events
 FOR EACH ROW EXECUTE FUNCTION public.inherit_event_traceparent();

CREATE FUNCTION public.agent_trace_context(eventid bigint,token uuid,eventattempt integer,parent text)
RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF parent IS NULL OR parent !~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$'
 OR NOT public.agent_queue_lock(eventid,token,eventattempt) THEN RETURN false; END IF;
 UPDATE public.events SET traceparent=parent
 WHERE id=eventid AND lease_token=token AND attempts=eventattempt;
 RETURN FOUND;
END $$;
REVOKE ALL ON FUNCTION public.agent_trace_context(bigint,uuid,integer,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agent_trace_context(bigint,uuid,integer,text)
 TO lab_inventory_executor,lab_fulfillment_executor,lab_dispatch_executor,
 lab_courier_executor,lab_judge_executor,lab_supply_executor,lab_restaurant_adk_executor;

-- A worker can observe only terminal telemetry for an event it already owns.
-- No order body, memory, tool arguments, or other agent's state is returned.
CREATE FUNCTION public.agent_order_telemetry(eventid bigint) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; e public.events%ROWTYPE; resultstatus text;
 started timestamptz;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND THEN RETURN NULL; END IF;
 SELECT * INTO e FROM public.events WHERE id=eventid AND run_id=b.run_id
 AND target_store=b.store AND coalesce(b.definition->'accepts','[]'::jsonb) ? topic;
 IF NOT FOUND OR e.state<>'done' THEN RETURN NULL; END IF;
 SELECT status INTO resultstatus FROM public.supply_orders WHERE run_id=e.run_id AND id=e.trace_id;
 IF resultstatus IS NULL THEN
  SELECT status INTO resultstatus FROM public.lab_delivery_jobs
  WHERE run_id=e.run_id AND basket=e.trace_id;
 END IF;
 IF resultstatus IS NULL OR resultstatus NOT IN ('delivered','failed','abandoned') THEN RETURN NULL; END IF;
 SELECT min(created_at) INTO started FROM public.events
 WHERE run_id=e.run_id AND trace_id=e.trace_id;
 RETURN jsonb_build_object('status',resultstatus,'latency',
  greatest(0,extract(epoch FROM (clock_timestamp()-started))*1000));
END $$;
REVOKE ALL ON FUNCTION public.agent_order_telemetry(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agent_order_telemetry(bigint)
 TO lab_inventory_executor,lab_fulfillment_executor,lab_dispatch_executor,
 lab_courier_executor,lab_judge_executor,lab_supply_executor,lab_restaurant_adk_executor;
