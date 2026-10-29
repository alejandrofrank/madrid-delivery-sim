-- Correct only completed model proposals, never resend an uncertain dispatch.
-- Reuse the scoped receipt ledger; rejected tools perform no domain effects.
CREATE FUNCTION public.restaurant_contract_reject(eventid bigint, token uuid, attempt integer,
 turnnonce uuid, toolname text, errorcode text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE q public.restaurant_turns%ROWTYPE; used integer; result jsonb;
BEGIN
 q:=public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 IF toolname IS NULL OR toolname !~ '^[A-Za-z][A-Za-z0-9_]{0,79}$'
 OR errorcode IS NULL OR errorcode NOT IN ('unknown_tool','summary_length')
 OR (errorcode='summary_length' AND toolname<>'finish_decision')
 OR NOT EXISTS(SELECT 1 FROM public.restaurant_model_calls WHERE event_id=eventid AND state='completed')
 OR EXISTS(SELECT 1 FROM public.restaurant_model_calls WHERE event_id=eventid AND state<>'completed')
 OR EXISTS(SELECT 1 FROM public.restaurant_tool_receipts WHERE event_id=eventid AND tool='restaurant.finish') THEN
  RAISE EXCEPTION 'Current completed, unfinished model proposal required' USING ERRCODE='42501';
 END IF;
 SELECT count(*) INTO used FROM public.restaurant_tool_receipts
  WHERE event_id=eventid AND tool='restaurant.contract_rejected';
 IF used>=2 THEN RAISE EXCEPTION 'Contract correction allowance exhausted' USING ERRCODE='54000'; END IF;
 -- A rejection costs an ordinary tool slot in addition to the model-call budget.
 IF NOT public.agent_consume_tool(eventid,token,attempt,'restaurant.finish') THEN
  RAISE EXCEPTION 'Contract correction tool budget denied' USING ERRCODE='42501'; END IF;
 result:=jsonb_build_object('ok',false,'executed',false,'error','tool_contract',
  'code',errorcode,'rejected_tool',toolname,'corrections_remaining',1-used,
  'summary_min_characters',1,'summary_max_characters',500,'message',
  CASE errorcode WHEN 'unknown_tool' THEN
   'Use an exact declared function name. If an action is staged, call finish_decision; do not stage it again.'
  ELSE 'Rewrite the summary in 1 to 500 characters. Keep the staged action; do not stage it again.' END);
 INSERT INTO public.restaurant_tool_receipts(event_id,tool,result)
  VALUES(eventid,'restaurant.contract_rejected',result);
 RETURN result;
END $$;
REVOKE ALL ON FUNCTION public.restaurant_contract_reject(bigint,uuid,integer,uuid,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.restaurant_contract_reject(bigint,uuid,integer,uuid,text,text)
 TO lab_restaurant_adk_executor;
