-- A courier cannot travel during time spent waiting for its queued briefing.
CREATE OR REPLACE FUNCTION public.courier_accept(basketid text,attemptid integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;j public.lab_delivery_jobs%ROWTYPE;sim integer;delay_seconds integer;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF b.definition->>'role' IS DISTINCT FROM 'courier' THEN RAISE EXCEPTION 'Forbidden role' USING ERRCODE='42501'; END IF;
 SELECT * INTO j FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=basketid AND attempt=attemptid AND 'courier:'||courier=b.store FOR UPDATE;
 IF NOT FOUND OR j.status<>'assigned' OR NOT EXISTS(SELECT 1 FROM public.lab_fleet WHERE run_id=b.run_id AND id=j.courier AND status='active' AND busy_basket=basketid) THEN RAISE EXCEPTION 'Current online assignment required'; END IF;
 IF NOT j.accepted THEN
  SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
  delay_seconds:=greatest(0,sim-j.depart_sim);
  UPDATE public.lab_delivery_jobs SET accepted=true,depart_sim=depart_sim+delay_seconds,
   pickup_sim=pickup_sim+delay_seconds,arrive_sim=arrive_sim+delay_seconds WHERE run_id=b.run_id AND basket=basketid;
  UPDATE public.lab_delivery_attempts SET accepted=true,depart_sim=depart_sim+delay_seconds,
   pickup_sim=pickup_sim+delay_seconds,arrive_sim=arrive_sim+delay_seconds
   WHERE run_id=b.run_id AND basket=basketid AND attempt=attemptid;
 END IF;
 RETURN jsonb_build_object('basket',basketid,'attempt',attemptid,'status','accepted');
END $$;
