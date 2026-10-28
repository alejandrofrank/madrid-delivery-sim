-- ADK is a reasoning adapter. Database identity, lease fencing and atomic effects
-- remain the authority boundary. Offline is the only admitted provider in this slice.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='lab_restaurant_adk_executor') THEN
  CREATE ROLE lab_restaurant_adk_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
 END IF;
END $$;
GRANT USAGE ON SCHEMA public TO lab_restaurant_adk_executor;
GRANT SELECT ON public.agent_budgets,public.agent_event_budgets,public.events TO lab_restaurant_adk_executor;
GRANT INSERT ON public.decisions TO lab_restaurant_adk_executor;
GRANT USAGE ON SEQUENCE public.decisions_id_seq TO lab_restaurant_adk_executor;
CREATE POLICY adk_restaurant_budgets ON public.agent_budgets TO lab_restaurant_adk_executor
 USING(run_id=(public.agent_scope()->>'run_id')::uuid AND store=public.agent_scope()->>'store');
CREATE POLICY adk_restaurant_tickets ON public.agent_event_budgets TO lab_restaurant_adk_executor
 USING(run_id=(public.agent_scope()->>'run_id')::uuid AND store=public.agent_scope()->>'store');
CREATE POLICY adk_restaurant_events ON public.events FOR SELECT TO lab_restaurant_adk_executor
 USING(run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store'
  AND (public.agent_definition()->'accepts') ? topic);
CREATE POLICY adk_restaurant_decisions ON public.decisions FOR INSERT TO lab_restaurant_adk_executor
 WITH CHECK(run_id=(public.agent_scope()->>'run_id')::uuid AND agent=public.agent_scope()->>'agent_id');
GRANT EXECUTE ON FUNCTION public.agent_scope(),public.agent_definition(),public.agent_clock(),
 public.agent_reserve_budget(bigint,uuid,integer),public.agent_queue_claim(text,uuid,text[],double precision),
 public.agent_queue_lock(bigint,uuid,integer),public.agent_queue_ack(bigint,uuid,integer),
 public.agent_queue_fail(bigint,uuid,integer,text),public.agent_consume_tool(bigint,uuid,integer,text),
 public.agent_memory_record(bigint,uuid,integer,text,jsonb,integer),
 public.agent_memory_recall(bigint,uuid,integer,jsonb,integer) TO lab_restaurant_adk_executor;
CREATE TABLE public.restaurant_turns (
 event_id bigint PRIMARY KEY REFERENCES public.events(id) ON DELETE CASCADE,
 run_id uuid NOT NULL REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 store text NOT NULL, definition_hash text NOT NULL, event_payload jsonb NOT NULL,
 context jsonb NOT NULL, state text NOT NULL DEFAULT 'running'
 CHECK(state IN ('running','succeeded','failed','unknown','applied')),
 dispatch_lease uuid NOT NULL, dispatch_attempt integer NOT NULL,
 nonce uuid NOT NULL DEFAULT gen_random_uuid(), result jsonb, memory jsonb NOT NULL DEFAULT '[]',
 error_code text, created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 CHECK(result IS NULL OR octet_length(result::text)<=4096)
);
CREATE TABLE public.restaurant_model_calls (
 event_id bigint REFERENCES public.restaurant_turns(event_id) ON DELETE CASCADE,
 step integer NOT NULL, request_hash text NOT NULL, reserved_tokens integer NOT NULL,
 state text NOT NULL DEFAULT 'in_flight' CHECK(state IN ('in_flight','completed')),
 usage jsonb, PRIMARY KEY(event_id,step)
);
CREATE TABLE public.restaurant_tool_receipts (
 event_id bigint REFERENCES public.restaurant_turns(event_id) ON DELETE CASCADE,
 step integer GENERATED ALWAYS AS IDENTITY, tool text NOT NULL, result jsonb NOT NULL,
 PRIMARY KEY(event_id,step), CHECK(octet_length(result::text)<=16384)
);
REVOKE ALL ON public.restaurant_turns,public.restaurant_model_calls,
 public.restaurant_tool_receipts FROM PUBLIC;
CREATE INDEX restaurant_turn_owner ON public.restaurant_turns(run_id,store);

CREATE FUNCTION public.restaurant_scope(eventid bigint,token uuid,attempt integer)
RETURNS public.agent_bindings LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND OR b.definition->>'role' IS DISTINCT FROM 'restaurant'
 OR b.definition->>'policy' IS DISTINCT FROM 'adk'
 OR b.definition->'brain'->>'provider' IS DISTINCT FROM 'offline'
 OR current_setting('transaction_isolation')<>'read committed' THEN
  RAISE EXCEPTION 'Authenticated offline ADK restaurant required' USING ERRCODE='42501'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(b.run_id::text,0));
 IF NOT public.agent_queue_lock(eventid,token,attempt) OR NOT EXISTS(
  SELECT 1 FROM public.agent_event_budgets t WHERE t.event_id=eventid AND t.attempt=restaurant_scope.attempt
  AND t.run_id=b.run_id AND t.store=b.store) OR NOT EXISTS(
  SELECT 1 FROM public.events e JOIN public.supply_orders o ON o.run_id=e.run_id AND o.id=e.payload->>'order'
  WHERE e.id=eventid AND o.restaurant=b.store) THEN
  RAISE EXCEPTION 'Active own restaurant order lease and budget required' USING ERRCODE='42501'; END IF;
 RETURN b;
END $$;

CREATE FUNCTION public.restaurant_turn_begin(eventid bigint,token uuid,attempt integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; q public.restaurant_turns%ROWTYPE; body jsonb; created boolean:=false;
BEGIN
 b:=public.restaurant_scope(eventid,token,attempt);
 SELECT payload INTO body FROM public.events WHERE id=eventid;
 SELECT * INTO q FROM public.restaurant_turns WHERE event_id=eventid FOR UPDATE;
 IF FOUND THEN
  IF q.run_id<>b.run_id OR q.store<>b.store OR q.definition_hash<>b.definition_hash
   OR q.event_payload<>body THEN RAISE EXCEPTION 'Incompatible restaurant turn' USING ERRCODE='42501'; END IF;
  IF q.state='running' AND (q.dispatch_lease<>token OR q.dispatch_attempt<>attempt) THEN
   UPDATE public.restaurant_turns SET state='unknown',error_code='InterruptedTurn' WHERE event_id=eventid RETURNING * INTO q;
  END IF;
 ELSE
  INSERT INTO public.restaurant_turns(event_id,run_id,store,definition_hash,event_payload,context,dispatch_lease,dispatch_attempt)
  VALUES(eventid,b.run_id,b.store,b.definition_hash,body,public.supply_context(body->>'order'),token,attempt) RETURNING * INTO q;
  created:=true;
 END IF;
 RETURN jsonb_build_object('state',q.state,'nonce',q.nonce,'result',q.result,'dispatch',created);
END $$;

CREATE FUNCTION public.restaurant_live_turn(eventid bigint,token uuid,attempt integer,turnnonce uuid)
RETURNS public.restaurant_turns LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; q public.restaurant_turns%ROWTYPE;
BEGIN
 b:=public.restaurant_scope(eventid,token,attempt);
 SELECT * INTO q FROM public.restaurant_turns WHERE event_id=eventid AND run_id=b.run_id AND store=b.store
 AND definition_hash=b.definition_hash AND nonce=turnnonce AND state='running'
 AND dispatch_lease=token AND dispatch_attempt=attempt FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Current restaurant reasoning turn required' USING ERRCODE='42501'; END IF;
 RETURN q;
END $$;

CREATE FUNCTION public.restaurant_model_admit(eventid bigint,token uuid,attempt integer,turnnonce uuid,
 requestbytes integer,requesthash text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; q public.restaurant_turns%ROWTYPE; cfg jsonb;
 eventcalls integer; agentcalls integer; totalcalls integer; agenttokens bigint; totaltokens bigint; reserve integer;
BEGIN
 q:=public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;cfg:=b.definition->'brain';
 IF requestbytes IS NULL OR requestbytes NOT BETWEEN 1 AND (cfg->>'request_bytes')::integer
 OR requesthash IS NULL OR requesthash !~ '^[a-f0-9]{64}$' THEN
  RAISE EXCEPTION 'Bounded model request required' USING ERRCODE='23514'; END IF;
 reserve:=requestbytes+(cfg->>'output_tokens')::integer;
 SELECT count(*) INTO eventcalls FROM public.restaurant_model_calls WHERE event_id=eventid;
 SELECT count(*),coalesce(sum(m.reserved_tokens),0) INTO agentcalls,agenttokens
 FROM public.restaurant_model_calls m JOIN public.restaurant_turns t USING(event_id)
 WHERE t.run_id=b.run_id AND t.store=b.store;
 SELECT count(*),coalesce(sum(m.reserved_tokens),0) INTO totalcalls,totaltokens
 FROM public.restaurant_model_calls m JOIN public.restaurant_turns t USING(event_id) WHERE t.run_id=b.run_id;
 IF eventcalls>=(cfg->>'model_calls_per_event')::integer OR agentcalls>=(cfg->>'model_calls_per_run')::integer
 OR agenttokens+reserve>(cfg->>'reserved_tokens_per_run')::integer OR totalcalls>=200 OR totaltokens+reserve>2097152
 OR EXISTS(SELECT 1 FROM public.restaurant_model_calls WHERE event_id=eventid AND state='in_flight') THEN
  RAISE EXCEPTION 'Restaurant model allowance exhausted or unfinished call' USING ERRCODE='54000'; END IF;
 INSERT INTO public.restaurant_model_calls(event_id,step,request_hash,reserved_tokens)
 VALUES(eventid,eventcalls+1,requesthash,reserve);
 RETURN eventcalls+1;
END $$;

CREATE FUNCTION public.restaurant_model_complete(eventid bigint,token uuid,attempt integer,turnnonce uuid,
 modelstep integer,usagebody jsonb) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 PERFORM public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 IF usagebody IS NULL OR jsonb_typeof(usagebody)<>'object' OR octet_length(usagebody::text)>1024 THEN
  RAISE EXCEPTION 'Invalid model receipt'; END IF;
 UPDATE public.restaurant_model_calls SET state='completed',usage=usagebody
 WHERE event_id=eventid AND step=modelstep AND state='in_flight';
 IF NOT FOUND THEN RAISE EXCEPTION 'Current model dispatch required' USING ERRCODE='42501'; END IF;
END $$;

CREATE FUNCTION public.restaurant_tool(eventid bigint,token uuid,attempt integer,turnnonce uuid,
 toolname text,arguments jsonb DEFAULT '{}') RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE q public.restaurant_turns%ROWTYPE; b public.agent_bindings%ROWTYPE; result jsonb;
 cfg jsonb; sim integer; rec jsonb;
BEGIN
 q:=public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF arguments IS NULL OR jsonb_typeof(arguments)<>'object' OR octet_length(arguments::text)>2048
 OR arguments ?| ARRAY['run','run_id','store','owner','namespace','agent_id','order','order_id'] THEN
  RAISE EXCEPTION 'Arguments cannot choose scope' USING ERRCODE='42501'; END IF;
 IF toolname='memory.read' THEN
  IF arguments<>'{}' THEN RAISE EXCEPTION 'Recall derives the current order' USING ERRCODE='42501'; END IF;
  result:=public.agent_memory_recall(eventid,token,attempt,NULL,8);
  q.memory:=result;
  UPDATE public.restaurant_turns SET memory=q.memory WHERE event_id=eventid;
 ELSE
  IF NOT public.agent_consume_tool(eventid,token,attempt,toolname) THEN
   RAISE EXCEPTION 'Restaurant capability or tool budget denied' USING ERRCODE='42501'; END IF;
  SELECT config INTO cfg FROM public.supply_sessions WHERE run_id=b.run_id;
  SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
  IF toolname IN ('restaurant.order','restaurant.pantry','restaurant.recipe','restaurant.suppliers') AND arguments<>'{}' THEN
   RAISE EXCEPTION 'Read tools accept no scope arguments' USING ERRCODE='42501'; END IF;
  IF toolname='restaurant.order' THEN
   SELECT r INTO rec FROM jsonb_array_elements(cfg->'recipes') r WHERE r->>'id'=q.context->'order'->>'meal';
   SELECT jsonb_build_object('order',o.id,'meal',o.meal,'quantity',o.quantity,'status',o.status,'deadline',o.deadline,
    'event',e.topic,'request',e.payload->>'request','sim_time',sim,
    'safe_alternative',public.supply_alternative(r.ingredient)) INTO result
   FROM public.events e JOIN public.supply_orders o ON o.run_id=b.run_id AND o.id=e.payload->>'order'
   LEFT JOIN public.supply_requests r ON r.run_id=b.run_id AND r.order_id=o.id AND r.id=e.payload->>'request'
   WHERE e.id=eventid;
  ELSIF toolname='restaurant.pantry' THEN result:=public.supply_context(q.event_payload->>'order')->'stock';
  ELSIF toolname='restaurant.recipe' THEN
   SELECT r INTO result FROM jsonb_array_elements(cfg->'recipes') r WHERE r->>'id'=q.context->'order'->>'meal';
  ELSIF toolname='restaurant.suppliers' THEN
   SELECT coalesce(jsonb_agg(x.body ORDER BY x.id),'[]') INTO result FROM (
    SELECT m.id,jsonb_build_object('id',m.id,'name',m.name,
     'procurement_fee_cents',coalesce((m.definition->>'procurement_fee_cents')::integer,100),
     'estimated_seconds',(cfg->>'supplier_delay_seconds')::integer+30*(abs(m.node%32-o.node%32)+abs(m.node/32-o.node/32))) body
    FROM public.supply_entities m JOIN public.supply_entities o ON o.run_id=m.run_id AND o.id=b.store
    CROSS JOIN LATERAL(SELECT (sim+(cfg->>'start_hour')::integer*3600)%86400 nowsec,
     coalesce((m.definition->'opening_hours'->>'start')::integer,0)*3600 startsec,
     coalesce((m.definition->'opening_hours'->>'end')::integer,24)*3600 endsec) h
    WHERE m.run_id=b.run_id AND m.kind='market' AND
    ((h.startsec<h.endsec AND h.nowsec>=h.startsec AND h.nowsec<h.endsec)
     OR(h.startsec>h.endsec AND(h.nowsec>=h.startsec OR h.nowsec<h.endsec)))
   ) x;
  ELSIF toolname IN ('restaurant.request_supply','restaurant.confirm','restaurant.receive',
   'restaurant.cook','restaurant.offer','restaurant.decline','restaurant.finish') THEN
   result:=jsonb_build_object('staged',true,'tool',toolname,'arguments',arguments);
  ELSE RAISE EXCEPTION 'Unknown restaurant tool' USING ERRCODE='42501'; END IF;
 END IF;
 IF result IS NULL OR octet_length(result::text)>16384 THEN RAISE EXCEPTION 'Invalid or oversized tool result'; END IF;
 INSERT INTO public.restaurant_tool_receipts(event_id,tool,result) VALUES(eventid,toolname,result);
 RETURN result;
END $$;

CREATE FUNCTION public.restaurant_turn_save(eventid bigint,token uuid,attempt integer,turnnonce uuid,
 plan jsonb,errorcode text DEFAULT NULL) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 PERFORM public.restaurant_live_turn(eventid,token,attempt,turnnonce);
 IF errorcode IS NOT NULL THEN
  UPDATE public.restaurant_turns SET state='failed',error_code=left(errorcode,80) WHERE event_id=eventid;RETURN;
 END IF;
 IF plan IS NULL OR jsonb_typeof(plan)<>'object' OR octet_length(plan::text)>4096
 OR NOT(plan ?& ARRAY['action','supplier','substitute','reason','summary'])
 OR EXISTS(SELECT 1 FROM jsonb_object_keys(plan) k WHERE k NOT IN ('action','supplier','substitute','reason','summary'))
 OR NOT EXISTS(SELECT 1 FROM public.restaurant_model_calls WHERE event_id=eventid)
 OR EXISTS(SELECT 1 FROM public.restaurant_model_calls WHERE event_id=eventid AND state<>'completed')
 OR jsonb_typeof(plan->'summary')<>'string' OR length(plan->>'summary') NOT BETWEEN 1 AND 500
 OR NOT EXISTS(SELECT 1 FROM public.restaurant_tool_receipts WHERE event_id=eventid AND tool='restaurant.finish'
  AND result->'arguments'->>'summary'=plan->>'summary')
 OR NOT EXISTS(SELECT 1 FROM public.restaurant_tool_receipts WHERE event_id=eventid AND tool=
  CASE plan->>'action' WHEN 'source' THEN 'restaurant.request_supply' WHEN 'confirm' THEN 'restaurant.confirm'
   WHEN 'receive' THEN 'restaurant.receive' WHEN 'cook' THEN 'restaurant.cook'
   WHEN 'offer' THEN 'restaurant.offer' WHEN 'decline' THEN 'restaurant.decline' END
  AND CASE plan->>'action' WHEN 'source' THEN result->'arguments'->>'supplier'=plan->>'supplier'
   WHEN 'offer' THEN result->'arguments'->>'substitute'=plan->>'substitute'
   WHEN 'decline' THEN result->'arguments'->>'reason'=plan->>'reason' ELSE true END) THEN
  RAISE EXCEPTION 'Completed bounded restaurant decision required' USING ERRCODE='23514'; END IF;
 UPDATE public.restaurant_turns SET state='succeeded',result=plan WHERE event_id=eventid;
END $$;

CREATE FUNCTION public.restaurant_supplier(runid uuid,restaurantid text,supplier text) RETURNS text
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE chosen text;
BEGIN
 -- Use the same open-market rule as the baseline; no stock from other stores is exposed.
 SELECT public.supply_nearest(runid,restaurantid,coalesce(jsonb_agg(m.id),'[]')) INTO chosen
 FROM public.supply_entities m WHERE m.run_id=runid AND m.kind='market' AND m.id IS DISTINCT FROM supplier;
 IF supplier IS NULL OR chosen IS DISTINCT FROM supplier THEN
  RAISE EXCEPTION 'A valid open supplier is required' USING ERRCODE='42501'; END IF;
 RETURN chosen;
END $$;

-- Preserve the existing atomic domain transition, with explicit sourcing choices.
CREATE FUNCTION public.supply_transition(eventid bigint,token uuid,attempt integer,intent jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; e public.events%ROWTYPE; o public.supply_orders%ROWTYPE;
 q public.supply_requests%ROWTYPE; a public.supply_allocations%ROWTYPE; s public.supply_stock%ROWTYPE;
 cfg jsonb; prefs jsonb; rest jsonb; line jsonb; recipebody jsonb; projection jsonb; detail jsonb;
 outbox jsonb:='[]'::jsonb; factbody jsonb; prior public.supply_facts%ROWTYPE; parenthash text; facthash text; seq bigint;
 oid text; rid text; ingredientid text; candidate text; nextmarket text; sim integer; latency integer;
 delayseconds integer; cookseconds integer; required numeric; taken numeric;
 roletext text; maxhops integer; resultstatus text; jobstatus text; startseconds integer; endseconds integer; entitydef jsonb; localsecond integer;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND OR b.definition->>'role' NOT IN ('household','restaurant','market') THEN
  RAISE EXCEPTION 'Forbidden supply role' USING ERRCODE='42501'; END IF;
 SELECT * INTO e FROM public.events WHERE id=eventid AND run_id=b.run_id AND target_store=b.store
 AND state='leased' AND lease_token=token AND attempts=attempt AND lease_until>clock_timestamp()
 AND b.definition->'accepts' ? topic FOR UPDATE;
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM public.agent_event_budgets WHERE event_id=eventid AND agent_event_budgets.attempt=supply_transition.attempt) THEN
  RAISE EXCEPTION 'Active own supply event lease and budget required' USING ERRCODE='42501'; END IF;
 -- Serializes supply projections and the per-run fact hash chain.
 SELECT config INTO cfg FROM public.supply_sessions WHERE run_id=b.run_id FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown supply session'; END IF;
 SELECT * INTO prior FROM public.supply_facts WHERE run_id=b.run_id AND event_id=eventid;
 IF FOUND THEN RETURN prior.payload->'detail'||jsonb_build_object('outbox',prior.payload->'outbox','fact_sequence',prior.sequence,'idempotent',true); END IF;
 SELECT sim_time INTO sim FROM public.runs WHERE id=b.run_id;
 oid:=e.payload->>'order'; roletext:=b.definition->>'role'; rid:=e.payload->>'request';
 SELECT * INTO o FROM public.supply_orders WHERE run_id=b.run_id AND id=oid FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown scoped supply order' USING ERRCODE='42501'; END IF;
 IF (roletext='household' AND o.household<>b.store) OR (roletext='restaurant' AND o.restaurant<>b.store) OR
 (roletext='market' AND NOT EXISTS(SELECT 1 FROM public.supply_requests WHERE run_id=b.run_id AND id=rid AND order_id=oid AND market=b.store)) THEN
  RAISE EXCEPTION 'Supply event exceeds bound entity' USING ERRCODE='42501'; END IF;
 SELECT definition INTO prefs FROM public.supply_entities WHERE run_id=b.run_id AND id=o.household AND kind='household';
 SELECT definition INTO rest FROM public.supply_entities WHERE run_id=b.run_id AND id=o.restaurant AND kind='restaurant';
 SELECT definition INTO entitydef FROM public.supply_entities WHERE run_id=b.run_id AND id=b.store AND kind=roletext;
 IF prefs IS NULL OR rest IS NULL OR entitydef IS NULL THEN RAISE EXCEPTION 'Invalid order entity kind'; END IF;
 latency:=greatest(0,least(coalesce((cfg->>'communication_latency_seconds')::integer,(cfg->>'message_latency_seconds')::integer,5)
  +coalesce((entitydef->'agent'->>'latency_seconds')::integer,(cfg->'agents'->roletext->>'latency_seconds')::integer,0),7200));
 delayseconds:=greatest(1,least(coalesce((cfg->>'supplier_delay_seconds')::integer,(cfg->>'transfer_seconds')::integer,60),86400));
 cookseconds:=greatest(1,least(coalesce((cfg->>'cook_seconds')::integer,60),3600));
 maxhops:=greatest(1,least(coalesce((cfg->>'max_market_hops')::integer,3),10));
 localsecond:=(sim+coalesce((cfg->>'start_hour')::integer,0)*3600)%86400;
 IF intent->>'action'='decline' THEN
  PERFORM public.supply_fail(b.run_id,oid,intent->>'reason',sim);resultstatus:='unfulfillable';
 ELSIF e.topic='ingredient.arrived' AND roletext='restaurant' AND (o.status IN ('failed','delivered') OR sim>o.deadline) THEN
  IF o.status NOT IN ('failed','delivered') THEN PERFORM public.supply_fail(b.run_id,oid,'Meal deadline expired',sim); END IF;
  SELECT * INTO q FROM public.supply_requests WHERE run_id=b.run_id AND id=rid AND order_id=oid FOR UPDATE;
  IF q.status='transit' THEN
   INSERT INTO public.supply_stock(run_id,owner,ingredient,unit,on_hand,version)
   VALUES(b.run_id,o.restaurant,q.ingredient,q.unit,q.quantity,1)
   ON CONFLICT(run_id,owner,ingredient) DO UPDATE SET on_hand=supply_stock.on_hand+excluded.on_hand,
    version=supply_stock.version+1 WHERE supply_stock.unit=excluded.unit;
   IF NOT FOUND THEN RAISE EXCEPTION 'Canonical ingredient unit mismatch'; END IF;
   UPDATE public.supply_requests SET status='arrived' WHERE run_id=b.run_id AND id=rid;
  END IF; resultstatus:='late_ingredient_received';
 ELSIF o.status IN ('failed','delivered') THEN resultstatus:='terminal_ignored';
 ELSIF sim>o.deadline AND NOT(e.topic='meal.delivery' AND EXISTS(
  SELECT 1 FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=oid AND status='delivered' AND arrive_sim<=o.deadline)) THEN
  PERFORM public.supply_fail(b.run_id,oid,'Meal deadline expired',sim); resultstatus:='deadline_expired';
 ELSIF e.topic='household.intent' AND roletext='household' THEN
  IF o.status='intent' THEN
   UPDATE public.supply_orders SET status='calling',updated_sim=sim WHERE run_id=b.run_id AND id=oid;
   outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'household.call',o.restaurant,jsonb_build_object('order',oid),sim+latency));
  END IF; resultstatus:='calling';
 ELSIF e.topic='household.call' AND roletext='restaurant' THEN
  IF o.status='calling' THEN
   SELECT r INTO recipebody FROM jsonb_array_elements(cfg->'recipes') r WHERE r->>'id'=o.meal LIMIT 1;
   startseconds:=coalesce((rest->'opening_hours'->>'start')::integer,0)*3600;
   endseconds:=coalesce((rest->'opening_hours'->>'end')::integer,24)*3600;
   IF recipebody IS NULL OR NOT(coalesce(rest->'recipe_ids',rest->'menu','[]'::jsonb) ? o.meal) THEN
    PERFORM public.supply_fail(b.run_id,oid,'Meal is not offered by this restaurant',sim);
   ELSIF (startseconds<endseconds AND (localsecond<startseconds OR localsecond>=endseconds)) OR
         (startseconds>endseconds AND localsecond<startseconds AND localsecond>=endseconds) OR startseconds=endseconds THEN
    PERFORM public.supply_fail(b.run_id,oid,'Restaurant is closed',sim);
   ELSE
    UPDATE public.supply_orders SET recipe=recipebody->'ingredients',status='sourcing',updated_sim=sim WHERE run_id=b.run_id AND id=oid;
    FOR line IN SELECT value FROM jsonb_array_elements(recipebody->'ingredients') LOOP
     ingredientid:=line->>'id'; required:=(line->>'quantity')::numeric*o.quantity;
     IF required<=0 OR required>1000000 THEN RAISE EXCEPTION 'Invalid canonical ingredient quantity'; END IF;
     taken:=0;
     IF public.supply_allowed(ingredientid,prefs) THEN
      SELECT * INTO s FROM public.supply_stock WHERE run_id=b.run_id AND owner=o.restaurant AND ingredient=ingredientid FOR UPDATE;
      IF FOUND THEN
       IF s.unit<>line->>'unit' THEN RAISE EXCEPTION 'Canonical ingredient unit mismatch'; END IF;
       taken:=least(required,s.on_hand-s.reserved);
       IF taken>0 THEN
        UPDATE public.supply_stock SET reserved=reserved+taken,version=version+1 WHERE run_id=b.run_id AND owner=o.restaurant AND ingredient=ingredientid;
        INSERT INTO public.supply_allocations(run_id,order_id,ingredient,unit,quantity) VALUES(b.run_id,oid,ingredientid,line->>'unit',taken);
       END IF;
      END IF;
     END IF;
     IF taken<required THEN
      rid:=oid||':'||ingredientid;
      IF NOT public.supply_allowed(ingredientid,prefs) THEN
       candidate:=public.supply_alternative(ingredientid);
       IF candidate IS NULL OR NOT public.supply_allowed(candidate,prefs) THEN
        PERFORM public.supply_fail(b.run_id,oid,'No safe ingredient substitution',sim); EXIT;
       END IF;
       INSERT INTO public.supply_requests(run_id,id,order_id,restaurant,original_ingredient,ingredient,unit,quantity,status,proposed)
       VALUES(b.run_id,rid,oid,o.restaurant,ingredientid,ingredientid,line->>'unit',required-taken,'awaiting_approval',candidate);
       outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'household.offer',o.household,jsonb_build_object('order',oid,'request',rid,'ingredient',ingredientid,'proposed',candidate),sim+latency));
      ELSE
       IF intent IS NULL THEN nextmarket:=public.supply_nearest(b.run_id,o.restaurant,'[]'::jsonb); ELSE nextmarket:=public.restaurant_supplier(b.run_id,o.restaurant,intent->>'supplier'); END IF;
       INSERT INTO public.supply_requests(run_id,id,order_id,restaurant,original_ingredient,ingredient,unit,quantity,market)
       VALUES(b.run_id,rid,oid,o.restaurant,ingredientid,ingredientid,line->>'unit',required-taken,nextmarket);
       IF nextmarket IS NULL THEN
        PERFORM public.supply_fail(b.run_id,oid,'No supplier available',sim); EXIT;
       END IF;
       outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'market.request',nextmarket,jsonb_build_object('order',oid,'request',rid),sim+latency));
      END IF;
     END IF;
    END LOOP;
    IF NOT EXISTS(SELECT 1 FROM public.supply_requests WHERE run_id=b.run_id AND order_id=oid) AND
       EXISTS(SELECT 1 FROM public.supply_orders WHERE run_id=b.run_id AND id=oid AND status<>'failed') THEN
     UPDATE public.supply_orders SET status='cooking',updated_sim=sim WHERE run_id=b.run_id AND id=oid;
     outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'restaurant.cook',o.restaurant,jsonb_build_object('order',oid),sim+cookseconds));
    END IF;
   END IF;
  END IF; resultstatus:='restaurant_intake';
 ELSIF e.topic='market.request' AND roletext='market' THEN
  SELECT * INTO q FROM public.supply_requests WHERE run_id=b.run_id AND id=rid AND order_id=oid AND market=b.store FOR UPDATE;
  IF q.status='seeking' THEN
   startseconds:=coalesce((entitydef->'opening_hours'->>'start')::integer,0)*3600;
   endseconds:=coalesce((entitydef->'opening_hours'->>'end')::integer,24)*3600;
   SELECT * INTO s FROM public.supply_stock WHERE run_id=b.run_id AND owner=b.store AND ingredient=q.ingredient FOR UPDATE;
   IF FOUND AND s.unit=q.unit AND s.on_hand-s.reserved>=q.quantity AND
    ((startseconds<endseconds AND localsecond>=startseconds AND localsecond<endseconds) OR
     (startseconds>endseconds AND (localsecond>=startseconds OR localsecond<endseconds))) THEN
    UPDATE public.supply_stock SET reserved=reserved+q.quantity,version=version+1 WHERE run_id=b.run_id AND owner=b.store AND ingredient=q.ingredient;
    UPDATE public.supply_requests SET status='reserved',visited=visited||jsonb_build_array(b.store) WHERE run_id=b.run_id AND id=rid;
    outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'market.transfer',b.store,jsonb_build_object('order',oid,'request',rid),sim+delayseconds));
    resultstatus:='supplier_reserved';
   ELSE
    q.visited:=q.visited||jsonb_build_array(b.store);
    nextmarket:=CASE WHEN jsonb_array_length(q.visited)<maxhops THEN public.supply_nearest(b.run_id,b.store,q.visited) END;
    IF nextmarket IS NOT NULL THEN
     UPDATE public.supply_requests SET visited=q.visited,market=nextmarket WHERE run_id=b.run_id AND id=rid;
     outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'market.request',nextmarket,jsonb_build_object('order',oid,'request',rid),sim+latency));
     resultstatus:='forwarded';
    ELSE
     UPDATE public.supply_requests SET status='shortage',visited=q.visited WHERE run_id=b.run_id AND id=rid;
     outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'ingredient.shortage',o.restaurant,jsonb_build_object('order',oid,'request',rid),sim+latency));
     resultstatus:='supplier_shortage';
    END IF;
   END IF;
  ELSE resultstatus:='stale_request_ignored'; END IF;
 ELSIF e.topic='market.transfer' AND roletext='market' THEN
  SELECT * INTO q FROM public.supply_requests WHERE run_id=b.run_id AND id=rid AND order_id=oid AND market=b.store FOR UPDATE;
  IF q.status='reserved' THEN
   UPDATE public.supply_stock SET on_hand=on_hand-q.quantity,reserved=reserved-q.quantity,version=version+1
    WHERE run_id=b.run_id AND owner=b.store AND ingredient=q.ingredient AND unit=q.unit AND reserved>=q.quantity AND on_hand>=q.quantity;
   IF NOT FOUND THEN RAISE EXCEPTION 'Supplier reservation invariant failed'; END IF;
   UPDATE public.supply_requests SET status='transit' WHERE run_id=b.run_id AND id=rid;
   outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'ingredient.arrived',o.restaurant,jsonb_build_object('order',oid,'request',rid),sim+latency));
  END IF; resultstatus:='supplier_dispatched';
 ELSIF e.topic='ingredient.shortage' AND roletext='restaurant' THEN
  SELECT * INTO q FROM public.supply_requests WHERE run_id=b.run_id AND id=rid AND order_id=oid FOR UPDATE;
  IF q.status='shortage' THEN
   candidate:=CASE WHEN intent IS NULL THEN public.supply_alternative(q.ingredient) ELSE intent->>'substitute' END;
   IF intent IS NOT NULL AND candidate IS DISTINCT FROM public.supply_alternative(q.ingredient) THEN RAISE EXCEPTION 'Unsafe substitution proposal' USING ERRCODE='42501'; END IF;
   IF q.household_approved OR candidate IS NULL OR NOT public.supply_allowed(candidate,prefs) THEN
    PERFORM public.supply_fail(b.run_id,oid,'No safe available ingredient substitution',sim); resultstatus:='unfulfillable';
   ELSE
    UPDATE public.supply_requests SET status='awaiting_approval',proposed=candidate WHERE run_id=b.run_id AND id=rid;
    UPDATE public.supply_orders SET status='awaiting_approval',updated_sim=sim WHERE run_id=b.run_id AND id=oid;
    outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'household.offer',o.household,jsonb_build_object('order',oid,'request',rid,'ingredient',q.original_ingredient,'proposed',candidate),sim+latency));
    resultstatus:='substitution_offered';
   END IF;
  ELSE resultstatus:='stale_shortage_ignored'; END IF;
 ELSIF e.topic='household.offer' AND roletext='household' THEN
  SELECT * INTO q FROM public.supply_requests WHERE run_id=b.run_id AND id=rid AND order_id=oid FOR UPDATE;
  IF q.status='awaiting_approval' THEN
   IF coalesce((prefs->>'allow_substitutions')::boolean,(prefs->>'accept_substitutions')::boolean,true)
    AND public.supply_allowed(q.proposed,prefs) THEN
    UPDATE public.supply_requests SET household_approved=true WHERE run_id=b.run_id AND id=rid;
    outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'restaurant.approval',o.restaurant,jsonb_build_object('order',oid,'request',rid),sim+latency));
    resultstatus:='household_approved';
   ELSE PERFORM public.supply_fail(b.run_id,oid,'Household declined substitution',sim);resultstatus:='household_declined'; END IF;
  ELSE resultstatus:='stale_offer_ignored'; END IF;
 ELSIF e.topic='restaurant.approval' AND roletext='restaurant' THEN
  SELECT * INTO q FROM public.supply_requests WHERE run_id=b.run_id AND id=rid AND order_id=oid FOR UPDATE;
  IF q.status='awaiting_approval' AND q.household_approved AND q.proposed IS NOT NULL THEN
   IF NOT public.supply_allowed(q.proposed,prefs) OR q.proposed IS DISTINCT FROM public.supply_alternative(q.ingredient) THEN
    RAISE EXCEPTION 'Unapproved or unsafe substitution' USING ERRCODE='42501'; END IF;
   IF intent IS NULL THEN nextmarket:=public.supply_nearest(b.run_id,o.restaurant,'[]'::jsonb); ELSE nextmarket:=public.restaurant_supplier(b.run_id,o.restaurant,intent->>'supplier'); END IF;
   UPDATE public.supply_requests SET ingredient=proposed,status='seeking',market=nextmarket,visited='[]'::jsonb WHERE run_id=b.run_id AND id=rid;
   UPDATE public.supply_orders SET status='sourcing',substitutions=substitutions||jsonb_build_object(q.original_ingredient,q.proposed),updated_sim=sim WHERE run_id=b.run_id AND id=oid;
   IF nextmarket IS NULL THEN PERFORM public.supply_fail(b.run_id,oid,'No supplier available',sim);
   ELSE outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'market.request',nextmarket,jsonb_build_object('order',oid,'request',rid),sim+latency)); END IF;
  END IF; resultstatus:='restaurant_approved';
 ELSIF e.topic='ingredient.arrived' AND roletext='restaurant' THEN
  SELECT * INTO q FROM public.supply_requests WHERE run_id=b.run_id AND id=rid AND order_id=oid FOR UPDATE;
  IF q.status='transit' THEN
   IF NOT public.supply_allowed(q.ingredient,prefs) THEN RAISE EXCEPTION 'Unsafe ingredient arrival'; END IF;
   INSERT INTO public.supply_stock(run_id,owner,ingredient,unit,on_hand,reserved,version)
   VALUES(b.run_id,o.restaurant,q.ingredient,q.unit,q.quantity,q.quantity,1)
   ON CONFLICT(run_id,owner,ingredient) DO UPDATE SET on_hand=supply_stock.on_hand+excluded.on_hand,
    reserved=supply_stock.reserved+excluded.reserved,version=supply_stock.version+1
   WHERE supply_stock.unit=excluded.unit;
   IF NOT FOUND THEN RAISE EXCEPTION 'Canonical ingredient unit mismatch'; END IF;
   INSERT INTO public.supply_allocations(run_id,order_id,ingredient,unit,quantity) VALUES(b.run_id,oid,q.ingredient,q.unit,q.quantity)
   ON CONFLICT(run_id,order_id,ingredient) DO UPDATE SET quantity=supply_allocations.quantity+excluded.quantity
    WHERE supply_allocations.unit=excluded.unit AND NOT supply_allocations.consumed AND NOT supply_allocations.released;
   IF NOT FOUND THEN RAISE EXCEPTION 'Supply allocation invariant failed'; END IF;
   UPDATE public.supply_requests SET status='arrived' WHERE run_id=b.run_id AND id=rid;
   IF NOT EXISTS(SELECT 1 FROM public.supply_requests WHERE run_id=b.run_id AND order_id=oid AND status<>'arrived') THEN
    UPDATE public.supply_orders SET status='cooking',updated_sim=sim WHERE run_id=b.run_id AND id=oid;
    outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'restaurant.cook',o.restaurant,jsonb_build_object('order',oid),sim+cookseconds));
   END IF;
  END IF; resultstatus:='ingredient_received';
 ELSIF e.topic='restaurant.cook' AND roletext='restaurant' THEN
  IF o.status='cooking' THEN
   IF EXISTS(SELECT 1 FROM public.supply_requests WHERE run_id=b.run_id AND order_id=oid AND status<>'arrived') THEN RAISE EXCEPTION 'All ingredients must arrive'; END IF;
   FOR a IN SELECT * FROM public.supply_allocations WHERE run_id=b.run_id AND order_id=oid ORDER BY ingredient FOR UPDATE LOOP
    IF a.consumed OR a.released OR NOT public.supply_allowed(a.ingredient,prefs) THEN RAISE EXCEPTION 'Invalid cooking allocation'; END IF;
    UPDATE public.supply_stock SET on_hand=on_hand-a.quantity,reserved=reserved-a.quantity,version=version+1
    WHERE run_id=b.run_id AND owner=o.restaurant AND ingredient=a.ingredient AND unit=a.unit AND reserved>=a.quantity AND on_hand>=a.quantity;
    IF NOT FOUND THEN RAISE EXCEPTION 'Cooking stock invariant failed'; END IF;
   END LOOP;
   UPDATE public.supply_allocations SET consumed=true WHERE run_id=b.run_id AND order_id=oid;
   UPDATE public.supply_orders SET status='ready',updated_sim=sim WHERE run_id=b.run_id AND id=oid;
   INSERT INTO public.lab_delivery_jobs(run_id,basket,store,pickup_node,customer_node,deadline_sim)
   SELECT b.run_id,oid,o.restaurant,r.node,h.node,o.deadline FROM public.supply_entities r,public.supply_entities h
   WHERE r.run_id=b.run_id AND r.id=o.restaurant AND h.run_id=b.run_id AND h.id=o.household;
   outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'basket.ready','dispatcher:fleet',jsonb_build_object('basket',oid),sim+latency));
   outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'meal.delivery',o.household,jsonb_build_object('order',oid),sim+greatest(60,latency)));
  END IF; resultstatus:='meal_ready';
 ELSIF e.topic='meal.delivery' AND roletext='household' THEN
  SELECT status INTO jobstatus FROM public.lab_delivery_jobs WHERE run_id=b.run_id AND basket=oid;
  IF jobstatus='delivered' THEN
   UPDATE public.supply_orders SET status='delivered',updated_sim=sim WHERE run_id=b.run_id AND id=oid; resultstatus:='delivered';
  ELSIF jobstatus='abandoned' THEN
   PERFORM public.supply_fail(b.run_id,oid,'Courier delivery abandoned',sim); resultstatus:='delivery_failed';
  ELSE
   outbox:=outbox||jsonb_build_array(public.supply_send(b.run_id,eventid,'meal.delivery',o.household,jsonb_build_object('order',oid),least(o.deadline+1,sim+600)));
   resultstatus:='awaiting_delivery';
  END IF;
 ELSIF e.topic='household.status' AND roletext='household' THEN resultstatus:='status_observed';
 ELSE RAISE EXCEPTION 'Unsupported supply event for bound role' USING ERRCODE='42501'; END IF;
 SELECT * INTO o FROM public.supply_orders WHERE run_id=b.run_id AND id=oid;
 detail:=jsonb_build_object('order',oid,'status',o.status,'action',resultstatus,'reason',o.reason,'actor',b.store,'sim_time',sim);
 -- Mutable after-images are for operator replay only, never returned to agents.
 projection:=jsonb_build_object('orders',jsonb_build_array(to_jsonb(o)),
  'requests',coalesce((SELECT jsonb_agg(to_jsonb(r) ORDER BY r.id) FROM public.supply_requests r WHERE r.run_id=b.run_id AND r.order_id=oid),'[]'::jsonb),
  'allocations',coalesce((SELECT jsonb_agg(to_jsonb(x) ORDER BY x.ingredient) FROM public.supply_allocations x WHERE x.run_id=b.run_id AND x.order_id=oid),'[]'::jsonb),
  'stock',coalesce((SELECT jsonb_agg(to_jsonb(x) ORDER BY x.owner,x.ingredient) FROM public.supply_stock x WHERE x.run_id=b.run_id AND
   (x.owner=o.restaurant OR x.owner IN (SELECT r.market FROM public.supply_requests r WHERE r.run_id=b.run_id AND r.order_id=oid))),'[]'::jsonb),
  'delivery_jobs',coalesce((SELECT jsonb_agg(to_jsonb(j)) FROM public.lab_delivery_jobs j WHERE j.run_id=b.run_id AND j.basket=oid),'[]'::jsonb));
 factbody:=jsonb_build_object('detail',detail,'outbox',outbox,'projection',projection);
 SELECT * INTO prior FROM public.supply_facts WHERE run_id=b.run_id ORDER BY sequence DESC LIMIT 1;
 seq:=coalesce(prior.sequence,0)+1;parenthash:=coalesce(prior.hash,repeat('0',64));
 facthash:=encode(sha256(convert_to(parenthash||factbody::text,'UTF8')),'hex');
 INSERT INTO public.supply_facts(run_id,sequence,event_id,order_id,actor,kind,sim_time,parent_hash,hash,payload)
 VALUES(b.run_id,seq,eventid,oid,b.store,e.topic,sim,parenthash,facthash,factbody);
 RETURN detail||jsonb_build_object('outbox',outbox,'fact_sequence',seq);
END $$;

CREATE OR REPLACE FUNCTION public.supply_command(eventid bigint,token uuid,attempt integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM public.agent_bindings WHERE login_role=session_user AND definition->>'policy'='adk') THEN
  RAISE EXCEPTION 'ADK restaurants use granular tools and saved plans' USING ERRCODE='42501'; END IF;
 RETURN public.supply_transition(eventid,token,attempt,NULL);
END $$;

CREATE FUNCTION public.restaurant_apply(eventid bigint,token uuid,attempt integer) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; q public.restaurant_turns%ROWTYPE;
 result jsonb; topicname text; fact jsonb; expected text[];
BEGIN
 b:=public.restaurant_scope(eventid,token,attempt);
 SELECT * INTO q FROM public.restaurant_turns WHERE event_id=eventid AND run_id=b.run_id AND store=b.store
  AND definition_hash=b.definition_hash AND state='succeeded' FOR UPDATE;
 IF NOT FOUND OR q.event_payload IS DISTINCT FROM (SELECT payload FROM public.events WHERE id=eventid)
 OR q.context IS DISTINCT FROM public.supply_context(q.event_payload->>'order') THEN
  RAISE EXCEPTION 'Saved decision does not match current restaurant facts' USING ERRCODE='42501'; END IF;
 FOR fact IN SELECT value FROM jsonb_array_elements(q.memory) LOOP
  IF NOT EXISTS(SELECT 1 FROM public.agent_memory_current f JOIN public.runs r ON r.id=f.run_id
   WHERE f.id=(fact->>'fact_id')::bigint AND f.run_id=b.run_id AND f.store=b.store
   AND f.context_id=q.event_payload->>'order' AND f.expires_sim>r.sim_time
   AND f.version=(fact->>'version')::integer) THEN
   RAISE EXCEPTION 'Recalled memory became stale' USING ERRCODE='42501'; END IF;
 END LOOP;
 SELECT topic INTO topicname FROM public.events WHERE id=eventid;
 expected:=CASE topicname WHEN 'household.call' THEN ARRAY['source','confirm','decline']
  WHEN 'ingredient.shortage' THEN ARRAY['offer','decline']
  WHEN 'restaurant.approval' THEN ARRAY['source','decline']
  WHEN 'ingredient.arrived' THEN ARRAY['receive','decline']
  WHEN 'restaurant.cook' THEN ARRAY['cook','decline'] END;
 IF expected IS NULL OR NOT(q.result->>'action'=ANY(expected)) THEN
  RAISE EXCEPTION 'Action does not match the incoming event' USING ERRCODE='42501'; END IF;
 IF q.result->>'action'='decline' AND (jsonb_typeof(q.result->'reason')<>'string'
  OR length(q.result->>'reason') NOT BETWEEN 1 AND 240) THEN RAISE EXCEPTION 'Invalid decline reason'; END IF;
 result:=public.supply_transition(eventid,token,attempt,q.result);
 UPDATE public.restaurant_turns SET state='applied' WHERE event_id=eventid;
 RETURN result||jsonb_build_object('adk',jsonb_build_object('engine','google_adk','provider','offline',
  'definition_hash',q.definition_hash,'plan',q.result,
  'model_calls',(SELECT count(*) FROM public.restaurant_model_calls WHERE event_id=eventid),
  'reserved_tokens',(SELECT sum(reserved_tokens) FROM public.restaurant_model_calls WHERE event_id=eventid),
  'paid_calls',0,'memory',q.memory,
  'tools',coalesce((SELECT jsonb_agg(jsonb_build_object('tool',p.tool,'result',p.result) ORDER BY p.step)
    FROM public.restaurant_tool_receipts p WHERE p.event_id=eventid),'[]')));
END $$;

REVOKE ALL ON FUNCTION public.restaurant_scope(bigint,uuid,integer),
 public.restaurant_live_turn(bigint,uuid,integer,uuid),
 public.restaurant_supplier(uuid,text,text),public.supply_transition(bigint,uuid,integer,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.restaurant_turn_begin(bigint,uuid,integer),
 public.restaurant_model_admit(bigint,uuid,integer,uuid,integer,text),
 public.restaurant_model_complete(bigint,uuid,integer,uuid,integer,jsonb),
 public.restaurant_tool(bigint,uuid,integer,uuid,text,jsonb),
 public.restaurant_turn_save(bigint,uuid,integer,uuid,jsonb,text),public.restaurant_apply(bigint,uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.restaurant_turn_begin(bigint,uuid,integer),
 public.restaurant_model_admit(bigint,uuid,integer,uuid,integer,text),
 public.restaurant_model_complete(bigint,uuid,integer,uuid,integer,jsonb),
 public.restaurant_tool(bigint,uuid,integer,uuid,text,jsonb),
 public.restaurant_turn_save(bigint,uuid,integer,uuid,jsonb,text),public.restaurant_apply(bigint,uuid,integer)
 TO lab_restaurant_adk_executor;
