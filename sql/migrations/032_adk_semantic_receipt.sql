-- ADK has a separate nonce-fenced capability path; preserve its immutable receipts.
CREATE FUNCTION public.restaurant_semantic_recall(eventid bigint,token uuid,attempt integer,
 turnnonce uuid, ranked_ids jsonb, audit jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE q public.restaurant_turns%ROWTYPE; fresh jsonb; selected jsonb;
BEGIN
 q:=public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 IF NOT EXISTS(SELECT 1 FROM public.agent_bindings WHERE login_role=session_user
               AND definition->'memory'->>'mode'='semantic')
 OR jsonb_typeof(ranked_ids)<>'array' OR jsonb_array_length(ranked_ids)>8
 OR jsonb_typeof(audit)<>'object' OR octet_length(audit::text)>2048
 OR EXISTS(SELECT 1 FROM jsonb_object_keys(audit) k WHERE k NOT IN
   ('backend','model','query_sha256','candidate_count','ranked_fact_ids','embedding_paid_calls')) THEN
  RAISE EXCEPTION 'Invalid semantic receipt' USING ERRCODE='42501'; END IF;
 fresh:=public.agent_memory_recall(eventid,token,attempt,NULL,8);
 SELECT coalesce(jsonb_agg(fact ORDER BY rank),'[]') INTO selected FROM (
  SELECT DISTINCT ON (fact->>'fact_id') fact, rank
  FROM jsonb_array_elements(fresh) fact
  JOIN jsonb_array_elements_text(ranked_ids) WITH ORDINALITY ids(id,rank)
    ON fact->>'fact_id'=ids.id ORDER BY fact->>'fact_id',rank
 ) authorized;
 UPDATE public.restaurant_turns SET memory=selected WHERE event_id=eventid;
 INSERT INTO public.restaurant_tool_receipts(event_id,tool,result)
 VALUES(eventid,'memory.semantic',jsonb_build_object('facts',selected,'audit',audit));
 RETURN selected;
END $$;
REVOKE ALL ON FUNCTION public.restaurant_semantic_recall(bigint,uuid,integer,uuid,jsonb,jsonb)
 FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.restaurant_semantic_recall(bigint,uuid,integer,uuid,jsonb,jsonb)
 TO lab_restaurant_adk_executor;
