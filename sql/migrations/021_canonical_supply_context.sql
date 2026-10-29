-- Equal business facts must compare equal regardless of physical tuple/query order.
CREATE OR REPLACE FUNCTION public.supply_context(orderid text) RETURNS jsonb
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
   to_jsonb(q)-'run_id'-'proposed'-'household_approved' ORDER BY q.id) FROM public.supply_requests q
   WHERE q.run_id=b.run_id AND q.order_id=orderid AND q.market=b.store),'[]'::jsonb),
   'stock',coalesce((SELECT jsonb_agg(to_jsonb(s)-'run_id' ORDER BY s.ingredient) FROM public.supply_stock s WHERE s.run_id=b.run_id AND s.owner=b.store),'[]'::jsonb)) INTO result;
 ELSIF (b.definition->>'role'='household' AND o.household=b.store) OR
       (b.definition->>'role'='restaurant' AND o.restaurant=b.store) THEN
  SELECT jsonb_build_object('order',to_jsonb(o)-'run_id',
   'requests',coalesce((SELECT jsonb_agg(to_jsonb(q)-'run_id' ORDER BY q.id) FROM public.supply_requests q WHERE q.run_id=b.run_id AND q.order_id=orderid),'[]'::jsonb),
   'stock',CASE WHEN b.definition->>'role'='restaurant' THEN coalesce((SELECT jsonb_agg(to_jsonb(s)-'run_id' ORDER BY s.ingredient) FROM public.supply_stock s WHERE s.run_id=b.run_id AND s.owner=b.store),'[]'::jsonb) ELSE '[]'::jsonb END) INTO result;
 ELSE RAISE EXCEPTION 'Unknown scoped supply order' USING ERRCODE='42501'; END IF;
 RETURN result;
END $$;

