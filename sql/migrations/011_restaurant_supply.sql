-- Supply agents have exact entity namespaces and no direct domain table grants.
DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='lab_supply_executor') THEN
  CREATE ROLE lab_supply_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
 END IF;
END $$;

CREATE TABLE public.supply_blueprints(id text PRIMARY KEY,revision text NOT NULL,config jsonb NOT NULL);
CREATE TABLE public.supply_sessions (
 run_id uuid PRIMARY KEY REFERENCES public.lab_worlds(run_id) ON DELETE CASCADE,
 config jsonb NOT NULL, opening jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE TABLE public.supply_entities (
 run_id uuid REFERENCES public.supply_sessions(run_id) ON DELETE CASCADE,
 id text NOT NULL, kind text NOT NULL CHECK(kind IN ('household','restaurant','market')),
 name text NOT NULL, node integer NOT NULL, definition jsonb NOT NULL DEFAULT '{}'::jsonb,
 PRIMARY KEY(run_id,id)
);
CREATE TABLE public.supply_stock (
 run_id uuid NOT NULL, owner text NOT NULL, ingredient text NOT NULL, unit text NOT NULL,
 on_hand numeric NOT NULL CHECK(on_hand>=0), reserved numeric NOT NULL DEFAULT 0
 CHECK(reserved>=0 AND reserved<=on_hand), version integer NOT NULL DEFAULT 0,
 PRIMARY KEY(run_id,owner,ingredient),
 FOREIGN KEY(run_id,owner) REFERENCES public.supply_entities(run_id,id) ON DELETE CASCADE
);
CREATE TABLE public.supply_orders (
 run_id uuid REFERENCES public.supply_sessions(run_id) ON DELETE CASCADE,
 id text NOT NULL, household text NOT NULL, restaurant text NOT NULL, meal text NOT NULL,
 quantity integer NOT NULL DEFAULT 1 CHECK(quantity BETWEEN 1 AND 100),
 deadline integer NOT NULL CHECK(deadline>=0),
 status text NOT NULL DEFAULT 'intent' CHECK(status IN
 ('intent','calling','sourcing','awaiting_approval','cooking','ready','delivered','failed')),
 recipe jsonb NOT NULL DEFAULT '[]'::jsonb, substitutions jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_sim integer NOT NULL DEFAULT 0, updated_sim integer NOT NULL DEFAULT 0,
 reason text, PRIMARY KEY(run_id,id),
 FOREIGN KEY(run_id,household) REFERENCES public.supply_entities(run_id,id),
 FOREIGN KEY(run_id,restaurant) REFERENCES public.supply_entities(run_id,id)
);
CREATE TABLE public.supply_requests (
 run_id uuid NOT NULL, id text NOT NULL, order_id text NOT NULL, restaurant text NOT NULL,
 original_ingredient text NOT NULL, ingredient text NOT NULL, unit text NOT NULL,
 quantity numeric NOT NULL CHECK(quantity>0), market text,
 status text NOT NULL DEFAULT 'seeking' CHECK(status IN
 ('seeking','reserved','transit','arrived','shortage','awaiting_approval','cancelled')),
 visited jsonb NOT NULL DEFAULT '[]'::jsonb, proposed text, household_approved boolean NOT NULL DEFAULT false,
 PRIMARY KEY(run_id,id), FOREIGN KEY(run_id,order_id) REFERENCES public.supply_orders(run_id,id) ON DELETE CASCADE,
 FOREIGN KEY(run_id,restaurant) REFERENCES public.supply_entities(run_id,id),
 FOREIGN KEY(run_id,market) REFERENCES public.supply_entities(run_id,id)
);
CREATE TABLE public.supply_allocations (
 run_id uuid NOT NULL, order_id text NOT NULL, ingredient text NOT NULL, unit text NOT NULL,
 quantity numeric NOT NULL CHECK(quantity>0), consumed boolean NOT NULL DEFAULT false,
 released boolean NOT NULL DEFAULT false, CHECK(NOT(consumed AND released)),
 PRIMARY KEY(run_id,order_id,ingredient),
 FOREIGN KEY(run_id,order_id) REFERENCES public.supply_orders(run_id,id) ON DELETE CASCADE
);
CREATE TABLE public.supply_facts (
 run_id uuid REFERENCES public.supply_sessions(run_id) ON DELETE CASCADE,
 sequence bigint NOT NULL, event_id bigint NOT NULL REFERENCES public.events(id),
 order_id text NOT NULL, actor text NOT NULL, kind text NOT NULL, sim_time integer NOT NULL,
 parent_hash text NOT NULL, hash text NOT NULL, payload jsonb NOT NULL,
 PRIMARY KEY(run_id,sequence), UNIQUE(run_id,event_id)
);
CREATE INDEX supply_orders_household ON public.supply_orders(run_id,household,status);
CREATE INDEX supply_orders_restaurant ON public.supply_orders(run_id,restaurant,status);
CREATE INDEX supply_requests_market ON public.supply_requests(run_id,market,status);
CREATE INDEX supply_requests_order ON public.supply_requests(run_id,order_id);
REVOKE ALL ON public.supply_blueprints,public.supply_sessions,public.supply_entities,public.supply_stock,public.supply_orders,
 public.supply_requests,public.supply_allocations,public.supply_facts FROM PUBLIC;

-- Owner-only helpers. No login or executor receives execute privilege.
CREATE FUNCTION public.supply_allowed(ingredient text, preferences jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public AS $$
 SELECT ingredient IS NOT NULL AND NOT(coalesce(preferences->'excluded_ingredients','[]'::jsonb) ? ingredient)
 AND NOT EXISTS(SELECT 1 FROM jsonb_array_elements_text(
  coalesce(preferences->'allergens','[]'::jsonb)||coalesce(preferences->'excluded_ingredients','[]'::jsonb)) a(value)
 WHERE (a.value IN ('gluten','wheat') AND ingredient IN ('flour','flatbread','burger-bun'))
 OR (a.value IN ('milk','dairy') AND ingredient='mozzarella')
 OR (a.value='fish' AND ingredient='salmon') OR (a.value='soy' AND ingredient='tofu'))
$$;
CREATE FUNCTION public.supply_alternative(ingredient text) RETURNS text
LANGUAGE sql IMMUTABLE SET search_path=pg_catalog,public AS $$
 SELECT CASE ingredient WHEN 'beef' THEN 'chicken' WHEN 'chicken' THEN 'tofu'
 WHEN 'salmon' THEN 'tofu' WHEN 'mozzarella' THEN 'tofu' WHEN 'potato' THEN 'carrot'
 WHEN 'carrot' THEN 'potato' WHEN 'lettuce' THEN 'cucumber' WHEN 'cucumber' THEN 'lettuce'
 WHEN 'onion' THEN 'carrot' WHEN 'flour' THEN 'rice-flour' WHEN 'flatbread' THEN 'gluten-free-flatbread'
 WHEN 'burger-bun' THEN 'gluten-free-bun' ELSE NULL END
$$;
CREATE FUNCTION public.supply_nearest(runid uuid, origin text, visited jsonb) RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
 SELECT m.id FROM public.supply_entities m
 JOIN public.supply_entities o ON o.run_id=m.run_id AND o.id=origin
 JOIN public.lab_worlds w ON w.run_id=m.run_id
 JOIN public.supply_sessions ss ON ss.run_id=m.run_id
 JOIN public.runs r ON r.id=m.run_id
 CROSS JOIN LATERAL (SELECT (r.sim_time+coalesce((ss.config->>'start_hour')::integer,0)*3600)%86400 AS current_second,
  coalesce((m.definition->'opening_hours'->>'start')::integer,0)*3600 AS start_second,
  coalesce((m.definition->'opening_hours'->>'end')::integer,24)*3600 AS end_second) hours
 LEFT JOIN LATERAL (SELECT n FROM jsonb_array_elements(w.city->'nodes') n WHERE (n->>'id')::integer=m.node LIMIT 1) mn ON true
 LEFT JOIN LATERAL (SELECT n FROM jsonb_array_elements(w.city->'nodes') n WHERE (n->>'id')::integer=o.node LIMIT 1) own ON true
 WHERE m.run_id=runid AND m.kind='market' AND NOT(visited ? m.id)
 AND ((hours.start_second<hours.end_second AND hours.current_second>=hours.start_second AND hours.current_second<hours.end_second)
 OR (hours.start_second>hours.end_second AND (hours.current_second>=hours.start_second OR hours.current_second<hours.end_second)))
 ORDER BY coalesce((SELECT min(idx) FROM jsonb_array_elements_text(coalesce(o.definition->'market_order','[]'::jsonb))
 WITH ORDINALITY v(id,idx) WHERE v.id=m.id),999),
 coalesce((mn.n->>'x')::numeric-(own.n->>'x')::numeric,0)^2+
 coalesce((mn.n->>'y')::numeric-(own.n->>'y')::numeric,0)^2,m.id LIMIT 1
$$;
CREATE FUNCTION public.supply_send(runid uuid,parent bigint,topicname text,destination text,body jsonb,due integer)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; e public.events%ROWTYPE; newid bigint; capacity integer; key text;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 SELECT * INTO e FROM public.events WHERE id=parent AND run_id=runid;
 IF b.run_id IS DISTINCT FROM runid OR e.target_store IS DISTINCT FROM b.store OR
 NOT(coalesce(b.definition->'emits','[]'::jsonb) ? topicname) THEN
  RAISE EXCEPTION 'Supply outgoing topic exceeds bound role' USING ERRCODE='42501'; END IF;
 IF octet_length(body::text)>4096 OR due<0 OR due>604800 THEN RAISE EXCEPTION 'Invalid supply outgoing message'; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.agent_bindings a WHERE a.run_id=runid AND a.store=destination
 AND a.definition->'accepts' ? topicname) THEN RAISE EXCEPTION 'Supply destination has no accepting agent'; END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(runid::text,0));
 SELECT greatest(1,least(coalesce((config->>'queue_capacity')::integer,10000),10000)) INTO capacity
 FROM public.supply_sessions WHERE run_id=runid;
 key:='supply:'||parent||':'||destination||':'||coalesce(body->>'request',body->>'order',body->>'basket','');
 SELECT id INTO newid FROM public.events WHERE run_id=runid AND topic=topicname AND dedupe_key=key;
 IF NOT FOUND THEN
  IF (SELECT count(*) FROM public.events WHERE run_id=runid AND state IN ('ready','leased'))>=capacity THEN
   RAISE EXCEPTION 'Supply queue capacity reached' USING ERRCODE='54000'; END IF;
  INSERT INTO public.events(run_id,producer,topic,payload,dedupe_key,trace_id,parent_id,target_store,due_sim,available_at)
  VALUES(runid,b.definition->>'role',topicname,body,key,e.trace_id,parent,destination,due,'1970-01-01 UTC') RETURNING id INTO newid;
 END IF;
 RETURN jsonb_build_object('event_id',newid,'topic',topicname,'target_store',destination,'payload',body,'due_sim',due);
END $$;
CREATE FUNCTION public.supply_fail(runid uuid,orderid text,why text,sim integer) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE o public.supply_orders%ROWTYPE; a public.supply_allocations%ROWTYPE; q public.supply_requests%ROWTYPE;
BEGIN
 SELECT * INTO o FROM public.supply_orders WHERE run_id=runid AND id=orderid FOR UPDATE;
 IF o.status IN ('delivered','failed') THEN RETURN; END IF;
 FOR a IN SELECT * FROM public.supply_allocations WHERE run_id=runid AND order_id=orderid AND NOT consumed AND NOT released ORDER BY ingredient FOR UPDATE LOOP
  UPDATE public.supply_stock SET reserved=reserved-a.quantity,version=version+1
   WHERE run_id=runid AND owner=o.restaurant AND ingredient=a.ingredient AND reserved>=a.quantity;
  IF NOT FOUND THEN RAISE EXCEPTION 'Supply allocation invariant failed'; END IF;
 END LOOP;
 UPDATE public.supply_allocations SET released=true WHERE run_id=runid AND order_id=orderid AND NOT consumed;
 FOR q IN SELECT * FROM public.supply_requests WHERE run_id=runid AND order_id=orderid AND status='reserved' ORDER BY id FOR UPDATE LOOP
  UPDATE public.supply_stock SET reserved=reserved-q.quantity,version=version+1
   WHERE run_id=runid AND owner=q.market AND ingredient=q.ingredient AND reserved>=q.quantity;
  IF NOT FOUND THEN RAISE EXCEPTION 'Supply market reservation invariant failed'; END IF;
 END LOOP;
 -- Goods already dispatched remain in transit until their authoritative arrival;
 -- failed demand cannot make physical inventory disappear.
 UPDATE public.supply_requests SET status='cancelled' WHERE run_id=runid AND order_id=orderid AND status NOT IN ('arrived','transit','cancelled');
 UPDATE public.supply_orders SET status='failed',reason=why,updated_sim=sim WHERE run_id=runid AND id=orderid;
END $$;

CREATE FUNCTION public.supply_context(orderid text) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,public AS $$
DECLARE b public.agent_bindings%ROWTYPE; o public.supply_orders%ROWTYPE; result jsonb;
BEGIN
 SELECT * INTO b FROM public.agent_bindings WHERE login_role=session_user;
 IF NOT FOUND OR b.definition->>'role' NOT IN ('household','restaurant','market') THEN
  RAISE EXCEPTION 'Forbidden supply role' USING ERRCODE='42501'; END IF;
 SELECT * INTO o FROM public.supply_orders WHERE run_id=b.run_id AND id=orderid;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown scoped supply order' USING ERRCODE='42501'; END IF;
 IF b.definition->>'role'='market' THEN
  -- A supplier cannot inspect household identity, preferences, menu or recipe.
  IF NOT EXISTS(SELECT 1 FROM public.supply_requests WHERE run_id=b.run_id AND order_id=orderid AND market=b.store) THEN
   RAISE EXCEPTION 'Unknown scoped supply request' USING ERRCODE='42501'; END IF;
  SELECT jsonb_build_object('order',orderid,'requests',coalesce((SELECT jsonb_agg(
   to_jsonb(q)-'run_id'-'proposed'-'household_approved') FROM public.supply_requests q
   WHERE q.run_id=b.run_id AND q.order_id=orderid AND q.market=b.store),'[]'::jsonb),
   'stock',coalesce((SELECT jsonb_agg(to_jsonb(s)-'run_id') FROM public.supply_stock s WHERE s.run_id=b.run_id AND s.owner=b.store),'[]'::jsonb)) INTO result;
 ELSIF (b.definition->>'role'='household' AND o.household=b.store) OR
       (b.definition->>'role'='restaurant' AND o.restaurant=b.store) THEN
  SELECT jsonb_build_object('order',to_jsonb(o)-'run_id',
   'requests',coalesce((SELECT jsonb_agg(to_jsonb(q)-'run_id') FROM public.supply_requests q WHERE q.run_id=b.run_id AND q.order_id=orderid),'[]'::jsonb),
   'stock',CASE WHEN b.definition->>'role'='restaurant' THEN coalesce((SELECT jsonb_agg(to_jsonb(s)-'run_id') FROM public.supply_stock s WHERE s.run_id=b.run_id AND s.owner=b.store),'[]'::jsonb) ELSE '[]'::jsonb END) INTO result;
 ELSE RAISE EXCEPTION 'Unknown scoped supply order' USING ERRCODE='42501'; END IF;
 RETURN result;
END $$;

CREATE FUNCTION public.supply_command(eventid bigint,token uuid,attempt integer) RETURNS jsonb
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
 IF NOT FOUND OR NOT EXISTS(SELECT 1 FROM public.agent_event_budgets WHERE event_id=eventid AND agent_event_budgets.attempt=supply_command.attempt) THEN
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
 IF e.topic='ingredient.arrived' AND roletext='restaurant' AND (o.status IN ('failed','delivered') OR sim>o.deadline) THEN
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
       nextmarket:=public.supply_nearest(b.run_id,o.restaurant,'[]'::jsonb);
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
   candidate:=public.supply_alternative(q.ingredient);
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
   nextmarket:=public.supply_nearest(b.run_id,o.restaurant,'[]'::jsonb);
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
GRANT USAGE ON SCHEMA public TO lab_supply_executor;
GRANT SELECT ON public.agent_budgets,public.agent_event_budgets TO lab_supply_executor;
GRANT UPDATE(observed_tools) ON public.agent_event_budgets TO lab_supply_executor;
GRANT SELECT,INSERT,UPDATE,DELETE ON public.agent_memories TO lab_supply_executor;
GRANT SELECT ON public.events TO lab_supply_executor;
GRANT UPDATE(state,lease_token,lease_until,attempts,error,available_at,completed_at) ON public.events TO lab_supply_executor;
GRANT SELECT,INSERT ON public.decisions TO lab_supply_executor;
GRANT USAGE ON SEQUENCE public.decisions_id_seq TO lab_supply_executor;
DO $$ DECLARE tbl text; BEGIN
 FOREACH tbl IN ARRAY ARRAY['agent_memories','agent_budgets','agent_event_budgets'] LOOP
  EXECUTE format('CREATE POLICY supply_scope ON public.%I TO lab_supply_executor USING (run_id=(public.agent_scope()->>''run_id'')::uuid AND store=public.agent_scope()->>''store'') WITH CHECK (run_id=(public.agent_scope()->>''run_id'')::uuid AND store=public.agent_scope()->>''store'')',tbl);
 END LOOP;
END $$;
CREATE POLICY supply_events_read ON public.events FOR SELECT TO lab_supply_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store' AND public.agent_definition()->'accepts' ? topic);
CREATE POLICY supply_events_update ON public.events FOR UPDATE TO lab_supply_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store' AND public.agent_definition()->'accepts' ? topic)
 WITH CHECK(run_id=(public.agent_scope()->>'run_id')::uuid AND target_store=public.agent_scope()->>'store' AND public.agent_definition()->'accepts' ? topic);
CREATE POLICY supply_decisions ON public.decisions TO lab_supply_executor USING (
 run_id=(public.agent_scope()->>'run_id')::uuid AND agent=public.agent_scope()->>'agent_id')
 WITH CHECK(run_id=(public.agent_scope()->>'run_id')::uuid AND agent=public.agent_scope()->>'agent_id');
REVOKE ALL ON FUNCTION public.supply_allowed(text,jsonb),public.supply_alternative(text),public.supply_nearest(uuid,text,jsonb),
 public.supply_send(uuid,bigint,text,text,jsonb,integer),public.supply_fail(uuid,text,text,integer),
 public.supply_context(text),public.supply_command(bigint,uuid,integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.agent_scope(),public.agent_definition(),public.agent_clock(),public.agent_queue_room(integer),
 public.agent_reserve_budget(bigint,uuid,integer),public.supply_context(text),public.supply_command(bigint,uuid,integer) TO lab_supply_executor;
