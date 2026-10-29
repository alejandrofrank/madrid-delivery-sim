-- Business trace_id remains an order correlation key; OTel is separate metadata.
ALTER TABLE public.events ADD COLUMN otel_traceparent text;

CREATE FUNCTION public.event_telemetry_context() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE candidate text;
BEGIN
 candidate := current_setting('delivery.traceparent',true);
 IF candidate ~ '^00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$'
 AND split_part(candidate,'-',2) <> repeat('0',32)
 AND split_part(candidate,'-',3) <> repeat('0',16) THEN
  NEW.otel_traceparent := candidate;
 ELSIF NEW.parent_id IS NOT NULL THEN
  SELECT otel_traceparent INTO NEW.otel_traceparent FROM public.events
  WHERE id=NEW.parent_id AND run_id=NEW.run_id;
 ELSE
  NEW.otel_traceparent := NULL;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.event_telemetry_context() FROM PUBLIC;
CREATE TRIGGER event_telemetry_context BEFORE INSERT ON public.events
FOR EACH ROW EXECUTE FUNCTION public.event_telemetry_context();
