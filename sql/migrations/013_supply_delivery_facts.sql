-- World motion and dispatcher transitions can outlive a failed household order.
-- Capture each changed delivery job in the same transaction as its mutation.
ALTER TABLE public.supply_facts ALTER COLUMN event_id DROP NOT NULL;

CREATE FUNCTION public.supply_record_delivery_job() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE seq bigint; parenthash text; facthash text; actorname text; sim integer; factbody jsonb;
BEGIN
 IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
 -- Shared with supply_command: one session lock serializes the complete chain.
 -- Existing world/queue writers acquire the run advisory lock before job writes.
 PERFORM 1 FROM public.supply_sessions WHERE run_id=NEW.run_id FOR UPDATE;
 IF NOT FOUND THEN RETURN NEW; END IF;
 SELECT agent_id INTO actorname FROM public.agent_bindings
 WHERE login_role=session_user AND run_id=NEW.run_id;
 actorname:=coalesce(actorname,'lab_world');
 SELECT sim_time INTO sim FROM public.runs WHERE id=NEW.run_id;
 factbody:=jsonb_build_object('detail',jsonb_build_object(
  'order',NEW.basket,'status',NEW.status,'action','delivery_job_after_image',
  'actor',actorname,'sim_time',sim),'outbox','[]'::jsonb,
  'projection',jsonb_build_object('delivery_jobs',jsonb_build_array(to_jsonb(NEW))));
 SELECT sequence+1,hash INTO seq,parenthash FROM public.supply_facts
 WHERE run_id=NEW.run_id ORDER BY sequence DESC LIMIT 1;
 seq:=coalesce(seq,1);parenthash:=coalesce(parenthash,repeat('0',64));
 facthash:=encode(sha256(convert_to(parenthash||factbody::text,'UTF8')),'hex');
 INSERT INTO public.supply_facts(run_id,sequence,event_id,order_id,actor,kind,sim_time,parent_hash,hash,payload)
 VALUES(NEW.run_id,seq,NULL,NEW.basket,actorname,'delivery.job.changed',sim,parenthash,facthash,factbody);
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.supply_record_delivery_job() FROM PUBLIC,
 lab_supply_executor,lab_inventory_executor,lab_fulfillment_executor,
 lab_dispatch_executor,lab_courier_executor,lab_judge_executor;
CREATE TRIGGER supply_delivery_job_fact AFTER INSERT OR UPDATE ON public.lab_delivery_jobs
 FOR EACH ROW EXECUTE FUNCTION public.supply_record_delivery_job();
