-- Operator identities remain trusted even when different from the function owner.
CREATE OR REPLACE FUNCTION public.agent_memory_capacity() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE ab public.agent_budgets%ROWTYPE; entries bigint; bytes bigint;
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=session_user AND (rolsuper OR rolbypassrls))
 AND (public.agent_scope() IS NULL OR NEW.run_id<>(public.agent_scope()->>'run_id')::uuid
 OR NEW.store<>public.agent_scope()->>'store') THEN
 RAISE EXCEPTION 'memory write exceeds agent scope' USING ERRCODE='42501'; END IF;
 SELECT * INTO ab FROM public.agent_budgets WHERE run_id=NEW.run_id AND store=NEW.store FOR UPDATE;
 IF NOT FOUND THEN RETURN NEW; END IF;
 SELECT count(*),coalesce(sum(octet_length(body::text)),0) INTO entries,bytes
 FROM public.agent_memories WHERE run_id=NEW.run_id AND store=NEW.store AND key<>NEW.key;
 IF entries+1>ab.memory_entries_limit OR bytes+octet_length(NEW.body::text)>ab.memory_bytes_limit THEN
 RAISE EXCEPTION 'agent memory capacity exceeded' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
