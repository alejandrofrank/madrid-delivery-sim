-- Converge the two shipped 026 histories without changing their recorded checksums.
-- Google-stack 026 introduced otel_traceparent; otel-bigquery 026 introduced
-- traceparent and the lease-scoped helpers below. Preserve both external names.
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS traceparent text
 CHECK (traceparent IS NULL OR traceparent ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$');
ALTER TABLE public.events ADD COLUMN IF NOT EXISTS otel_traceparent text;
DROP TRIGGER IF EXISTS event_telemetry_context ON public.events;
DROP TRIGGER IF EXISTS events_traceparent ON public.events;
UPDATE public.events SET traceparent=coalesce(traceparent,otel_traceparent),
 otel_traceparent=coalesce(traceparent,otel_traceparent)
 WHERE traceparent IS DISTINCT FROM otel_traceparent;

CREATE OR REPLACE FUNCTION public.inherit_event_traceparent() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE candidate text;
BEGIN
 IF TG_OP='UPDATE' THEN
  IF NEW.traceparent IS DISTINCT FROM OLD.traceparent THEN
   NEW.otel_traceparent:=NEW.traceparent;
  ELSIF NEW.otel_traceparent IS DISTINCT FROM OLD.otel_traceparent THEN
   NEW.traceparent:=NEW.otel_traceparent;
  END IF;
  RETURN NEW;
 END IF;
 NEW.traceparent:=coalesce(NEW.traceparent,NEW.otel_traceparent);
 IF NEW.traceparent IS NULL AND NEW.parent_id IS NOT NULL THEN
  SELECT traceparent INTO NEW.traceparent FROM public.events
  WHERE id=NEW.parent_id AND run_id=NEW.run_id AND trace_id=NEW.trace_id;
 END IF;
 IF NEW.traceparent IS NULL THEN
  candidate:=current_setting('delivery.traceparent',true);
  IF candidate ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$'
  AND split_part(candidate,'-',2)<>repeat('0',32)
  AND split_part(candidate,'-',3)<>repeat('0',16) THEN NEW.traceparent:=candidate; END IF;
 END IF;
 NEW.otel_traceparent:=NEW.traceparent;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.inherit_event_traceparent() FROM PUBLIC;
CREATE TRIGGER events_traceparent BEFORE INSERT OR UPDATE OF traceparent,otel_traceparent
 ON public.events
 FOR EACH ROW EXECUTE FUNCTION public.inherit_event_traceparent();

CREATE OR REPLACE FUNCTION public.agent_trace_context(eventid bigint,token uuid,eventattempt integer,parent text)
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
CREATE OR REPLACE FUNCTION public.agent_order_telemetry(eventid bigint) RETURNS jsonb
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
