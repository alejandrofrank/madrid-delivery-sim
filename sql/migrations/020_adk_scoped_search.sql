-- Reuse the existing owner/lease-bound read-only search ledger. No legacy
-- command/context access and no raw table privileges are granted to ADK.
CREATE FUNCTION public.supply_search_settings(eventid bigint,token uuid,attempt integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb;
BEGIN
 scope:=public.supply_search_scope(eventid,token,attempt);
 RETURN scope->'settings';
END $$;
REVOKE ALL ON FUNCTION public.supply_search_settings(bigint,uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.supply_search_settings(bigint,uuid,integer),
 public.supply_search_begin(bigint,uuid,integer),public.supply_search_admit(bigint,bigint,uuid,integer,text,integer),
 public.supply_search_record(bigint,bigint,bigint,uuid,integer,jsonb),public.supply_search_cache_get(bigint,bigint,uuid,integer,text),
 public.supply_search_cache_put(bigint,bigint,uuid,integer,text,jsonb),public.supply_search_stock(bigint,bigint,uuid,integer),
 public.supply_search_finish(bigint,bigint,uuid,integer,text,text,text,jsonb,numeric) TO lab_restaurant_adk_executor;
