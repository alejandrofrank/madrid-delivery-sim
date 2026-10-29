-- Memory modes are bounded recall policies over the same typed audit ledger.
-- They never replace canonical facts or grant tools, namespaces or authority.
CREATE FUNCTION public.agent_memory_profile_valid(profile jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public AS $$
DECLARE key text; value text;
BEGIN
 IF profile IS NULL OR profile='null'::jsonb THEN RETURN true; END IF;
 IF jsonb_typeof(profile)<>'object' THEN RETURN false; END IF;
 IF NOT(profile ?& ARRAY['mode','max_facts','max_bytes','ttl_seconds'])
 OR (SELECT count(*) FROM jsonb_object_keys(profile))<>4
 OR jsonb_typeof(profile->'mode')<>'string'
 OR profile->>'mode' NOT IN ('none','text','json','typed') THEN RETURN false; END IF;
 FOREACH key IN ARRAY ARRAY['max_facts','max_bytes','ttl_seconds'] LOOP
  value:=profile->>key;
  IF jsonb_typeof(profile->key)<>'number' OR value IS NULL OR value !~ '^[0-9]+$'
  OR length(value)>5 THEN RETURN false; END IF;
 END LOOP;
 RETURN (profile->>'max_facts')::integer BETWEEN 1 AND 8
  AND (profile->>'max_bytes')::integer BETWEEN 256 AND 8192
  AND (profile->>'ttl_seconds')::integer BETWEEN 60 AND 86400;
END $$;
ALTER TABLE public.agent_bindings ADD CONSTRAINT agent_memory_profile_bounds
 CHECK(public.agent_memory_profile_valid(definition->'memory'));

-- Clone the existing implementations, preserving all canonical checks without
-- maintaining a second copy. Keep the original function OIDs for cached plans.
DO $$ BEGIN
 EXECUTE replace(pg_get_functiondef(
  'public.agent_memory_record(bigint,uuid,integer,text,jsonb,integer)'::regprocedure),
  'FUNCTION public.agent_memory_record(', 'FUNCTION public.agent_memory_record_typed(');
 EXECUTE replace(pg_get_functiondef(
  'public.agent_memory_recall(bigint,uuid,integer,jsonb,integer)'::regprocedure),
  'FUNCTION public.agent_memory_recall(', 'FUNCTION public.agent_memory_recall_typed(');
END $$;

CREATE OR REPLACE FUNCTION public.agent_memory_record(eventid bigint,token uuid,attempt integer,
 factkind text,body jsonb,ttl integer DEFAULT 3600) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE profile jsonb;
BEGIN
 SELECT definition->'memory' INTO profile FROM public.agent_bindings WHERE login_role=session_user;
 -- Preserve the original validation of invalid TTLs, rather than masking them.
 IF profile IS NOT NULL AND profile<>'null'::jsonb AND ttl BETWEEN 1 AND 86400 THEN
  ttl:=least(ttl,(profile->>'ttl_seconds')::integer);
 END IF;
 RETURN public.agent_memory_record_typed(eventid,token,attempt,factkind,body,ttl);
END $$;

CREATE OR REPLACE FUNCTION public.agent_memory_recall(eventid bigint,token uuid,attempt integer,
 kinds jsonb DEFAULT NULL,maximum integer DEFAULT 8) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE profile jsonb; facts jsonb; fact jsonb; result jsonb:='[]'::jsonb;
 bytes integer:=2; sim integer; allowed integer;
BEGIN
 SELECT definition->'memory' INTO profile FROM public.agent_bindings WHERE login_role=session_user;
 -- Validate the caller's original maximum even when the profile would clamp it.
 IF maximum IS NULL OR maximum NOT BETWEEN 1 AND 16 THEN
  RETURN public.agent_memory_recall_typed(eventid,token,attempt,kinds,maximum);
 END IF;
 allowed:=CASE WHEN profile IS NULL OR profile='null'::jsonb THEN maximum
  ELSE least(maximum,(profile->>'max_facts')::integer) END;
 facts:=public.agent_memory_recall_typed(eventid,token,attempt,kinds,allowed);
 IF profile IS NULL OR profile='null'::jsonb THEN RETURN facts; END IF;
 IF profile->>'mode'='none' THEN RETURN '[]'::jsonb; END IF;
 SELECT r.sim_time INTO sim FROM public.runs r JOIN public.agent_bindings b ON b.run_id=r.id
  WHERE b.login_role=session_user;
 FOR fact IN SELECT * FROM jsonb_array_elements(facts) LOOP
  IF (fact->>'observed_sim')::integer+(profile->>'ttl_seconds')::integer<=sim THEN CONTINUE; END IF;
  IF bytes+octet_length(fact::text)+(CASE WHEN jsonb_array_length(result)>0 THEN 2 ELSE 0 END)
   >(profile->>'max_bytes')::integer THEN EXIT; END IF;
  result:=result||jsonb_build_array(fact);
  bytes:=octet_length(result::text);
 END LOOP;
 -- Keep arrays and complete references for restaurant_turns stale-fact fencing.
 RETURN result;
END $$;

REVOKE ALL ON FUNCTION public.agent_memory_profile_valid(jsonb),
 public.agent_memory_record_typed(bigint,uuid,integer,text,jsonb,integer),
 public.agent_memory_recall_typed(bigint,uuid,integer,jsonb,integer),
 public.agent_memory_record(bigint,uuid,integer,text,jsonb,integer),
 public.agent_memory_recall(bigint,uuid,integer,jsonb,integer) FROM PUBLIC;
DO $$ DECLARE role_name text; BEGIN
 FOREACH role_name IN ARRAY ARRAY['lab_inventory_executor','lab_fulfillment_executor',
  'lab_dispatch_executor','lab_courier_executor','lab_judge_executor','lab_supply_executor',
  'lab_restaurant_adk_executor'] LOOP
  EXECUTE format('REVOKE ALL ON FUNCTION public.agent_memory_record_typed(bigint,uuid,integer,text,jsonb,integer),public.agent_memory_recall_typed(bigint,uuid,integer,jsonb,integer) FROM %I',role_name);
  EXECUTE format('GRANT EXECUTE ON FUNCTION public.agent_memory_record(bigint,uuid,integer,text,jsonb,integer),public.agent_memory_recall(bigint,uuid,integer,jsonb,integer) TO %I',role_name);
 END LOOP;
END $$;
