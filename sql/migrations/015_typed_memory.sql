-- Typed observations are private capabilities, not a table agents can browse.
CREATE TABLE public.agent_memory_types (
 kind text PRIMARY KEY, role text NOT NULL, subject_type text NOT NULL,
 topics jsonb NOT NULL, body_schema jsonb NOT NULL
);
INSERT INTO public.agent_memory_types VALUES
('inventory.reservation','inventory','order','["basket.requested", "reservation.expire"]','{"additionalProperties": false, "properties": {"status": {"enum": ["reserved", "rejected", "expired", "cancelled", "fulfilled"], "title": "Status", "type": "string"}}, "required": ["status"], "title": "ReservationFact", "type": "object"}'),
('inventory.shipment','inventory','shipment','["shipment.delayed", "shipment.received"]','{"additionalProperties": false, "properties": {"expected_sim": {"anyOf": [{"maximum": 604800, "minimum": 0, "type": "integer"}, {"type": "null"}], "default": null, "title": "Expected Sim"}, "status": {"enum": ["delayed", "deferred", "received", "already_received"], "title": "Status", "type": "string"}}, "required": ["status"], "title": "ShipmentFact", "type": "object"}'),
('fulfillment.progress','fulfillment','order','["basket.reserved"]','{"additionalProperties": false, "properties": {"status": {"const": "picked", "title": "Status", "type": "string"}}, "required": ["status"], "title": "FulfillmentFact", "type": "object"}'),
('delivery.progress','dispatcher','order','["basket.ready", "dispatch.retry", "recovery.reviewed", "courier.accepted", "delivery.arrived"]','{"additionalProperties": false, "properties": {"attempt": {"anyOf": [{"maximum": 10, "minimum": 1, "type": "integer"}, {"type": "null"}], "default": null, "title": "Attempt"}, "courier": {"anyOf": [{"maxLength": 100, "minLength": 1, "type": "string"}, {"type": "null"}], "default": null, "title": "Courier"}, "eta_sim": {"anyOf": [{"maximum": 604800, "minimum": 0, "type": "integer"}, {"type": "null"}], "default": null, "title": "Eta Sim"}, "status": {"enum": ["ready", "assigned", "in_transit", "arrived", "delivered", "deferred", "awaiting_review", "abandoned", "briefing_acknowledged"], "title": "Status", "type": "string"}}, "required": ["status"], "title": "DeliveryFact", "type": "object"}'),
('courier.commitment','courier','order','["courier.briefed"]','{"additionalProperties": false, "properties": {"attempt": {"maximum": 10, "minimum": 1, "title": "Attempt", "type": "integer"}, "status": {"const": "accepted", "title": "Status", "type": "string"}}, "required": ["status", "attempt"], "title": "CourierFact", "type": "object"}'),
('recovery.verdict','judge','order','["delivery.failed"]','{"additionalProperties": false, "properties": {"attempt": {"maximum": 10, "minimum": 1, "title": "Attempt", "type": "integer"}, "estimated_seconds": {"anyOf": [{"maximum": 604800, "minimum": 0, "type": "integer"}, {"type": "null"}], "default": null, "title": "Estimated Seconds"}, "reason": {"maxLength": 240, "minLength": 1, "title": "Reason", "type": "string"}, "remaining_seconds": {"maximum": 604800, "minimum": -604800, "title": "Remaining Seconds", "type": "integer"}, "verdict": {"enum": ["approved", "denied"], "title": "Verdict", "type": "string"}}, "required": ["verdict", "attempt", "reason", "remaining_seconds"], "title": "RecoveryFact", "type": "object"}'),
('household.order','household','order','["household.intent", "household.offer", "household.status", "meal.delivery"]','{"additionalProperties": false, "properties": {"action": {"enum": ["calling", "restaurant_intake", "terminal_ignored", "deadline_expired", "late_ingredient_received", "unfulfillable", "substitution_offered", "stale_shortage_ignored", "household_approved", "household_declined", "stale_offer_ignored", "restaurant_approved", "ingredient_received", "meal_ready", "delivered", "delivery_failed", "awaiting_delivery", "status_observed"], "title": "Action", "type": "string"}, "reason": {"anyOf": [{"maxLength": 240, "type": "string"}, {"type": "null"}], "default": null, "title": "Reason"}, "status": {"enum": ["intent", "calling", "sourcing", "awaiting_approval", "cooking", "ready", "delivered", "failed"], "title": "Status", "type": "string"}}, "required": ["status", "action"], "title": "MealFact", "type": "object"}'),
('restaurant.order','restaurant','order','["household.call", "ingredient.shortage", "ingredient.arrived", "restaurant.approval", "restaurant.cook"]','{"additionalProperties": false, "properties": {"action": {"enum": ["calling", "restaurant_intake", "terminal_ignored", "deadline_expired", "late_ingredient_received", "unfulfillable", "substitution_offered", "stale_shortage_ignored", "household_approved", "household_declined", "stale_offer_ignored", "restaurant_approved", "ingredient_received", "meal_ready", "delivered", "delivery_failed", "awaiting_delivery", "status_observed"], "title": "Action", "type": "string"}, "reason": {"anyOf": [{"maxLength": 240, "type": "string"}, {"type": "null"}], "default": null, "title": "Reason"}, "status": {"enum": ["intent", "calling", "sourcing", "awaiting_approval", "cooking", "ready", "delivered", "failed"], "title": "Status", "type": "string"}}, "required": ["status", "action"], "title": "MealFact", "type": "object"}'),
('market.request','market','request','["market.request", "market.transfer"]','{"additionalProperties": false, "properties": {"ingredient": {"maxLength": 80, "minLength": 1, "title": "Ingredient", "type": "string"}, "outcome": {"enum": ["supplier_reserved", "supplier_shortage", "supplier_dispatched", "forwarded", "stale_request_ignored", "terminal_ignored", "deadline_expired"], "title": "Outcome", "type": "string"}, "quantity": {"exclusiveMinimum": 0, "maximum": 1000000, "title": "Quantity", "type": "number"}, "unit": {"enum": ["g", "ml", "piece"], "title": "Unit", "type": "string"}}, "required": ["ingredient", "quantity", "unit", "outcome"], "title": "SupplierFact", "type": "object"}');

CREATE FUNCTION public.memory_json_valid(instance jsonb,schema jsonb) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE SET search_path=pg_catalog,public AS $$
DECLARE prop text; child jsonb; typ text;
BEGIN
 IF schema ? 'anyOf' THEN
  RETURN EXISTS(SELECT 1 FROM jsonb_array_elements(schema->'anyOf') AS candidates(subschema)
   WHERE public.memory_json_valid(instance,subschema));
 END IF;
 typ:=schema->>'type';
 IF typ IS NULL OR jsonb_typeof(instance) IS DISTINCT FROM
  (CASE WHEN typ IN ('integer','number') THEN 'number' ELSE typ END) THEN RETURN false; END IF;
 IF schema ? 'enum' AND NOT(schema->'enum' @> jsonb_build_array(instance)) THEN RETURN false; END IF;
 IF schema ? 'const' AND instance IS DISTINCT FROM schema->'const' THEN RETURN false; END IF;
 IF typ='object' THEN
  IF EXISTS(SELECT 1 FROM jsonb_array_elements_text(coalesce(schema->'required','[]')) k
   WHERE NOT(instance ? k)) THEN RETURN false; END IF;
  FOR prop,child IN SELECT * FROM jsonb_each(instance) LOOP
   IF NOT(schema->'properties' ? prop) OR
    NOT public.memory_json_valid(child,schema->'properties'->prop) THEN RETURN false; END IF;
  END LOOP;
 ELSIF typ='string' THEN
  IF length(instance#>>'{}')<coalesce((schema->>'minLength')::integer,0) OR
   length(instance#>>'{}')>coalesce((schema->>'maxLength')::integer,2048) THEN RETURN false; END IF;
 ELSIF typ IN ('integer','number') THEN
  IF typ='integer' AND (instance#>>'{}')::numeric%1<>0 THEN RETURN false; END IF;
  IF (schema ? 'minimum' AND (instance#>>'{}')::numeric<(schema->>'minimum')::numeric) OR
   (schema ? 'maximum' AND (instance#>>'{}')::numeric>(schema->>'maximum')::numeric) OR
   (schema ? 'exclusiveMinimum' AND (instance#>>'{}')::numeric<=(schema->>'exclusiveMinimum')::numeric)
   THEN RETURN false; END IF;
 ELSIF typ NOT IN ('null','boolean') THEN RETURN false;
 END IF;
 RETURN true;
END $$;

CREATE TABLE public.agent_memory_facts (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id uuid NOT NULL REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 store text NOT NULL, owner_role text NOT NULL,
 context_type text NOT NULL CHECK(context_type IN ('order','shipment')),
 context_id text NOT NULL CHECK(length(context_id) BETWEEN 1 AND 200),
 kind text NOT NULL REFERENCES public.agent_memory_types(kind),
 subject text NOT NULL CHECK(length(subject) BETWEEN 1 AND 300),
 version integer NOT NULL CHECK(version>0),
 body jsonb NOT NULL CHECK(jsonb_typeof(body)='object' AND octet_length(body::text)<=2048),
 observed_sim integer NOT NULL CHECK(observed_sim>=0),
 expires_sim integer NOT NULL CHECK(expires_sim>observed_sim AND expires_sim<=observed_sim+86400),
 event_id bigint NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
 previous_id bigint REFERENCES public.agent_memory_facts(id) ON DELETE SET NULL,
 UNIQUE(run_id,store,context_type,context_id,kind,subject,version),
 UNIQUE(event_id,kind,subject)
);
CREATE INDEX agent_memory_recall ON public.agent_memory_facts
 (run_id,store,context_type,context_id,kind,subject,version DESC);
CREATE INDEX agent_memory_source ON public.agent_memory_facts(run_id,event_id);
ALTER TABLE public.agent_memory_facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_memory_facts FORCE ROW LEVEL SECURITY;
CREATE VIEW public.agent_memory_current AS
 SELECT DISTINCT ON (run_id,store,context_type,context_id,kind,subject) *
 FROM public.agent_memory_facts
 ORDER BY run_id,store,context_type,context_id,kind,subject,version DESC;

-- Helpers are not executable by agents. Scope is reconstructed from session_user
-- and the authoritative, fenced incoming envelope, never policy-supplied IDs.
CREATE FUNCTION public.agent_memory_context(eventid bigint,token uuid,attempt integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; e public.events%ROWTYPE;
 contextid text; contexttype text; subjectid text; sim integer;
BEGIN
 IF current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Memory capabilities require current READ COMMITTED state' USING ERRCODE='42501'; END IF;
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 SELECT * INTO e FROM public.events WHERE id=eventid AND run_id=b.run_id
  AND target_store=b.store FOR UPDATE;
 IF NOT FOUND OR e.state<>'leased' OR e.lease_token IS DISTINCT FROM token
  OR e.attempts<>attempt OR e.lease_until<=clock_timestamp()
  OR NOT(b.definition->'accepts' ? e.topic) THEN
  RAISE EXCEPTION 'Memory requires this agent active incoming lease' USING ERRCODE='42501'; END IF;
 contextid:=coalesce(e.payload->>'order',e.payload->>'basket',e.payload->>'shipment');
 contexttype:=CASE WHEN e.payload ? 'order' OR e.payload ? 'basket' THEN 'order' ELSE 'shipment' END;
 IF contextid IS NULL OR length(contextid) NOT BETWEEN 1 AND 200 OR
  num_nonnulls(e.payload->>'order',e.payload->>'basket',e.payload->>'shipment')<>1 OR
  e.trace_id IS DISTINCT FROM contextid THEN
  RAISE EXCEPTION 'Memory context must match authoritative order trace' USING ERRCODE='42501'; END IF;
 subjectid:=CASE WHEN b.definition->>'role'='market' THEN e.payload->>'request' ELSE contextid END;
 IF subjectid IS NULL OR length(subjectid) NOT BETWEEN 1 AND 300 THEN
  RAISE EXCEPTION 'Memory requires an addressed subject' USING ERRCODE='42501'; END IF;
 IF b.definition->>'role'='market' AND NOT EXISTS(SELECT 1 FROM public.supply_requests
  WHERE run_id=b.run_id AND id=subjectid AND order_id=contextid) THEN
  RAISE EXCEPTION 'Memory request does not belong to this order' USING ERRCODE='42501'; END IF;
 SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
 RETURN jsonb_build_object('run',b.run_id,'store',b.store,'role',b.definition->>'role',
  'context_type',contexttype,'context',contextid,'subject',subjectid,'sim',sim,
  'topic',e.topic,'attempt',e.payload->'attempt');
END $$;

CREATE FUNCTION public.agent_memory_record(eventid bigint,token uuid,attempt integer,
 factkind text,body jsonb,ttl integer DEFAULT 3600) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; contract public.agent_memory_types%ROWTYPE;
 prior public.agent_memory_facts%ROWTYPE; written public.agent_memory_facts%ROWTYPE;
 existing public.agent_memory_facts%ROWTYPE; budget public.agent_budgets%ROWTYPE;
 entries bigint; bytes bigint; sim integer; result jsonb;
BEGIN
 IF NOT public.agent_consume_tool(eventid,token,attempt,'memory.write') THEN
  RAISE EXCEPTION 'Memory write budget or lease denied' USING ERRCODE='42501'; END IF;
 scope:=public.agent_memory_context(eventid,token,attempt); sim:=(scope->>'sim')::integer;
 SELECT * INTO contract FROM public.agent_memory_types WHERE kind=factkind
  AND role=scope->>'role' AND topics ? (scope->>'topic');
 IF NOT FOUND OR NOT public.memory_json_valid(body,contract.body_schema) OR
  (contract.subject_type='shipment') IS DISTINCT FROM (scope->>'context_type'='shipment') OR
  ttl IS NULL OR ttl NOT BETWEEN 1 AND 86400 OR octet_length(body::text)>2048 THEN
  RAISE EXCEPTION 'Invalid typed memory fact, role, topic or expiry' USING ERRCODE='23514'; END IF;
 IF factkind='courier.commitment' AND body->'attempt' IS DISTINCT FROM scope->'attempt' THEN
  RAISE EXCEPTION 'Courier memory must match the assigned attempt' USING ERRCODE='42501'; END IF;
 SELECT * INTO budget FROM public.agent_budgets
  WHERE run_id=(scope->>'run')::uuid AND store=scope->>'store' FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Memory budget required' USING ERRCODE='42501'; END IF;
 -- The budget lock serializes first writes, revisions and capacity across keys.
 SELECT * INTO existing FROM public.agent_memory_facts
  WHERE event_id=eventid AND kind=factkind AND subject=scope->>'subject';
 IF FOUND THEN
  IF existing.body<>body OR existing.expires_sim-existing.observed_sim<>ttl THEN
   RAISE EXCEPTION 'Memory source event reused with different content' USING ERRCODE='23505'; END IF;
  written:=existing;
  SELECT * INTO prior FROM public.agent_memory_facts WHERE id=written.previous_id;
 ELSE
  SELECT * INTO prior FROM public.agent_memory_current
   WHERE run_id=(scope->>'run')::uuid AND store=scope->>'store'
   AND context_type=scope->>'context_type' AND context_id=scope->>'context'
   AND kind=factkind AND subject=scope->>'subject';
  SELECT count(*),coalesce(sum(octet_length(f.body::text)),0) INTO entries,bytes
   FROM public.agent_memory_current f WHERE f.run_id=(scope->>'run')::uuid
   AND f.store=scope->>'store' AND f.expires_sim>sim
   AND (prior.id IS NULL OR f.id<>prior.id);
  IF entries+1>budget.memory_entries_limit OR bytes+octet_length(body::text)>budget.memory_bytes_limit THEN
   RAISE EXCEPTION 'Typed memory capacity exceeded' USING ERRCODE='23514'; END IF;
  INSERT INTO public.agent_memory_facts(run_id,store,owner_role,context_type,context_id,
   kind,subject,version,body,observed_sim,expires_sim,event_id,previous_id)
  VALUES((scope->>'run')::uuid,scope->>'store',scope->>'role',scope->>'context_type',
   scope->>'context',factkind,scope->>'subject',coalesce(prior.version,0)+1,body,sim,sim+ttl,eventid,prior.id)
  RETURNING * INTO written;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM public.events WHERE id=eventid AND lease_token=token
  AND attempts=attempt AND state='leased' AND lease_until>clock_timestamp()) THEN
  RAISE EXCEPTION 'Memory lease expired while waiting' USING ERRCODE='42501'; END IF;
 result:=to_jsonb(written)-'run_id'-'store';
 -- A write receipt must not become a backdoor to expired or superseded bodies.
 -- The operator reconstructs diffs from the immutable revision table.
 RETURN result||jsonb_build_object('fact_id',written.id,'key',factkind||':'||written.subject);
END $$;

CREATE FUNCTION public.agent_memory_recall(eventid bigint,token uuid,attempt integer,
 kinds jsonb DEFAULT NULL,maximum integer DEFAULT 8) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE scope jsonb; f record; entry jsonb; result jsonb:='[]'::jsonb;
 bytes integer:=2; sim integer;
BEGIN
 IF NOT public.agent_consume_tool(eventid,token,attempt,'memory.read') THEN
  RAISE EXCEPTION 'Memory recall budget or lease denied' USING ERRCODE='42501'; END IF;
 scope:=public.agent_memory_context(eventid,token,attempt); sim:=(scope->>'sim')::integer;
 IF maximum IS NULL OR maximum NOT BETWEEN 1 AND 16 OR (kinds IS NOT NULL AND
  (jsonb_typeof(kinds)<>'array' OR jsonb_array_length(kinds)>9 OR
   EXISTS(SELECT 1 FROM jsonb_array_elements(kinds) k WHERE jsonb_typeof(k)<>'string') OR
   EXISTS(SELECT 1 FROM jsonb_array_elements_text(kinds) k WHERE NOT EXISTS(
    SELECT 1 FROM public.agent_memory_types t WHERE t.kind=k AND t.role=scope->>'role')))) THEN
  RAISE EXCEPTION 'Invalid recall types or result limit' USING ERRCODE='23514'; END IF;
 FOR f IN SELECT m.* FROM public.agent_memory_current m
  JOIN public.agent_memory_types t ON t.kind=m.kind AND t.role=m.owner_role
  WHERE m.run_id=(scope->>'run')::uuid AND m.store=scope->>'store'
  AND m.owner_role=scope->>'role' AND m.context_type=scope->>'context_type'
  AND m.context_id=scope->>'context' AND m.expires_sim>sim AND m.observed_sim<=sim
  AND (scope->>'role'<>'market' OR m.subject=scope->>'subject')
  AND (scope->>'role'<>'courier' OR m.body->'attempt'=scope->'attempt')
  AND (kinds IS NULL OR kinds ? m.kind)
  ORDER BY m.observed_sim DESC,m.id DESC LIMIT maximum LOOP
  entry:=(to_jsonb(f)-'run_id'-'store')||jsonb_build_object('fact_id',f.id,'key',f.kind||':'||f.subject);
  IF bytes+octet_length(entry::text)+2>8192 THEN EXIT; END IF;
  result:=result||jsonb_build_array(entry); bytes:=bytes+octet_length(entry::text)+2;
 END LOOP;
 IF NOT EXISTS(SELECT 1 FROM public.events WHERE id=eventid AND lease_token=token
  AND attempts=attempt AND state='leased' AND lease_until>clock_timestamp()) THEN
  RAISE EXCEPTION 'Memory lease expired while waiting' USING ERRCODE='42501'; END IF;
 RETURN result;
END $$;

REVOKE ALL ON public.agent_memory_types,public.agent_memory_facts,public.agent_memory_current FROM PUBLIC;
REVOKE ALL ON FUNCTION public.memory_json_valid(jsonb,jsonb),
 public.agent_memory_context(bigint,uuid,integer),
 public.agent_memory_record(bigint,uuid,integer,text,jsonb,integer),
 public.agent_memory_recall(bigint,uuid,integer,jsonb,integer) FROM PUBLIC;
DO $$ DECLARE role_name text; BEGIN
 FOREACH role_name IN ARRAY ARRAY['lab_inventory_executor','lab_fulfillment_executor',
  'lab_dispatch_executor','lab_courier_executor','lab_judge_executor','lab_supply_executor'] LOOP
  EXECUTE format('REVOKE ALL ON public.agent_memories,public.agent_memory_types,public.agent_memory_facts,public.agent_memory_current FROM %I',role_name);
  EXECUTE format('GRANT EXECUTE ON FUNCTION public.agent_memory_record(bigint,uuid,integer,text,jsonb,integer),public.agent_memory_recall(bigint,uuid,integer,jsonb,integer) TO %I',role_name);
 END LOOP;
END $$;
