-- Semantic ranking is a projection of current typed facts, never a new authority.
-- The extension is optional on existing installations; semantic mode fails closed
-- without it. The local Postgres build and Cloud SQL setup install pgvector.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_available_extensions WHERE name='vector') THEN
  CREATE EXTENSION IF NOT EXISTS vector;
 END IF;
 EXECUTE replace(pg_get_functiondef('public.agent_memory_profile_valid(jsonb)'::regprocedure),
  '(''none'',''text'',''json'',''typed'')', '(''none'',''text'',''json'',''typed'',''semantic'')');
END $$;

CREATE TABLE public.agent_semantic_vectors (
 fact_id bigint NOT NULL REFERENCES public.agent_memory_facts(id) ON DELETE CASCADE,
 model text NOT NULL CHECK(length(model) BETWEEN 1 AND 150),
 embedding jsonb NOT NULL CHECK(jsonb_typeof(embedding)='array' AND jsonb_array_length(embedding)=384),
 PRIMARY KEY(fact_id,model)
);
REVOKE ALL ON public.agent_semantic_vectors FROM PUBLIC;

CREATE FUNCTION public.agent_semantic_allowed(scope jsonb, factid bigint) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT EXISTS(SELECT 1 FROM public.agent_memory_current m
 JOIN public.agent_memory_types t ON t.kind=m.kind AND t.role=m.owner_role
 JOIN public.agent_bindings b ON b.login_role=session_user
 WHERE m.id=factid AND b.definition->'memory'->>'mode'='semantic'
 AND b.definition->'tools' ? 'memory.read'
 AND m.run_id=(scope->>'run')::uuid AND m.store=scope->>'store'
 AND m.owner_role=scope->>'role' AND m.context_type=scope->>'context_type'
 AND m.context_id=scope->>'context' AND m.expires_sim>(scope->>'sim')::integer
 AND m.observed_sim<=(scope->>'sim')::integer
 AND m.observed_sim+(b.definition->'memory'->>'ttl_seconds')::integer>(scope->>'sim')::integer
 AND (scope->>'role'<>'market' OR m.subject=scope->>'subject')
 AND (scope->>'role'<>'courier' OR m.body->'attempt'=scope->'attempt'));
$$;

CREATE FUNCTION public.agent_semantic_cache(eventid bigint,token uuid,attempt integer,
 modelid text, entries jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; entry jsonb;
BEGIN
 scope:=public.agent_memory_context(eventid,token,attempt);
 IF length(modelid) NOT BETWEEN 1 AND 150 OR jsonb_typeof(entries)<>'array'
 OR jsonb_array_length(entries)>8 THEN
  RAISE EXCEPTION 'Invalid embedding batch' USING ERRCODE='23514'; END IF;
 FOR entry IN SELECT * FROM jsonb_array_elements(entries) LOOP
  IF NOT public.agent_semantic_allowed(scope,(entry->>'fact_id')::bigint)
  OR jsonb_typeof(entry->'embedding')<>'array' OR jsonb_array_length(entry->'embedding')<>384
  OR EXISTS(SELECT 1 FROM jsonb_array_elements(entry->'embedding') n
            WHERE jsonb_typeof(n)<>'number') THEN
   RAISE EXCEPTION 'Embedding outside active memory scope' USING ERRCODE='42501'; END IF;
  INSERT INTO public.agent_semantic_vectors VALUES
   ((entry->>'fact_id')::bigint,modelid,entry->'embedding') ON CONFLICT DO NOTHING;
 END LOOP;
END $$;

CREATE FUNCTION public.agent_semantic_neighbors(eventid bigint,token uuid,attempt integer,
 modelid text, query_vector jsonb, maximum integer DEFAULT 8) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; result jsonb;
BEGIN
 scope:=public.agent_memory_context(eventid,token,attempt);
 IF maximum NOT BETWEEN 1 AND 8 OR jsonb_typeof(query_vector)<>'array'
 OR jsonb_array_length(query_vector)<>384 OR NOT EXISTS(
  SELECT 1 FROM pg_extension WHERE extname='vector') THEN
  RAISE EXCEPTION 'Semantic mode requires pgvector and a 384-dimensional query'
  USING ERRCODE='23514'; END IF;
 -- Exact search over the small authorized set, not global ANN followed by a filter.
 EXECUTE 'SELECT coalesce(jsonb_agg(fact_id ORDER BY distance,fact_id),''[]''::jsonb)
 FROM (SELECT v.fact_id,(v.embedding::text::public.vector <=> $1::text::public.vector) distance
 FROM public.agent_semantic_vectors v WHERE v.model=$2
 AND public.agent_semantic_allowed($3,v.fact_id) ORDER BY distance,v.fact_id LIMIT $4) ranked'
 INTO result USING query_vector,modelid,scope,maximum;
 RETURN result;
END $$;

REVOKE ALL ON FUNCTION public.agent_semantic_allowed(jsonb,bigint),
 public.agent_semantic_cache(bigint,uuid,integer,text,jsonb),
 public.agent_semantic_neighbors(bigint,uuid,integer,text,jsonb,integer) FROM PUBLIC;
DO $$ DECLARE role_name text; BEGIN
 FOREACH role_name IN ARRAY ARRAY['lab_inventory_executor','lab_fulfillment_executor',
  'lab_dispatch_executor','lab_courier_executor','lab_judge_executor','lab_supply_executor',
  'lab_restaurant_adk_executor'] LOOP
  EXECUTE format('GRANT EXECUTE ON FUNCTION public.agent_semantic_cache(bigint,uuid,integer,text,jsonb),public.agent_semantic_neighbors(bigint,uuid,integer,text,jsonb,integer) TO %I',role_name);
 END LOOP;
END $$;
