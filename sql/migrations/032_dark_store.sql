-- Shared physical inventory may now belong to a Madrid run as well as a lab run.
-- Existing row-level policies, keys, quantities and security functions are unchanged.
ALTER TABLE lab_stock DROP CONSTRAINT lab_stock_run_id_fkey;
ALTER TABLE lab_stock ADD FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE;
ALTER TABLE runs ADD COLUMN store_config jsonb;
ALTER TABLE chaos_events ADD COLUMN resource text;
ALTER TABLE chaos_events ADD COLUMN requested_resource text;

CREATE TABLE store_environments (
 run_id uuid REFERENCES runs(id) ON DELETE CASCADE, store text REFERENCES locations(id),
 layout jsonb NOT NULL, catalogue jsonb NOT NULL, last_sim integer NOT NULL DEFAULT -1,
 PRIMARY KEY(run_id,store)
);
CREATE TABLE store_shelves (
 run_id uuid NOT NULL, store text NOT NULL, slot text NOT NULL, sku text NOT NULL,
 quantity integer NOT NULL CHECK(quantity>=0),
 PRIMARY KEY(run_id,store,slot),
 FOREIGN KEY(run_id,store) REFERENCES store_environments(run_id,store) ON DELETE CASCADE,
 FOREIGN KEY(run_id,store,sku) REFERENCES lab_stock(run_id,store,sku) ON DELETE CASCADE
);
CREATE TABLE store_orders (
 run_id uuid NOT NULL, order_id text NOT NULL, store text NOT NULL,
 stage text NOT NULL DEFAULT 'requested' CHECK(stage IN
 ('requested','reserved','picking','packing','to_dock','dock','handed_off','cancelled')),
 lines jsonb NOT NULL, picked jsonb NOT NULL DEFAULT '{}',
 worker text, revision integer NOT NULL DEFAULT 0, packed_sim integer, dock_sim integer,
 PRIMARY KEY(run_id,order_id),
 FOREIGN KEY(run_id,order_id) REFERENCES orders(run_id,id) ON DELETE CASCADE,
 FOREIGN KEY(run_id,store) REFERENCES store_environments(run_id,store) ON DELETE CASCADE
);
CREATE TABLE store_workers (
 run_id uuid NOT NULL, store text NOT NULL, id text NOT NULL,
 kind text NOT NULL CHECK(kind IN ('robot','staff','forklift')),
 node text NOT NULL, route jsonb, task jsonb, available boolean NOT NULL DEFAULT true,
 revision integer NOT NULL DEFAULT 0,
 PRIMARY KEY(run_id,store,id),
 FOREIGN KEY(run_id,store) REFERENCES store_environments(run_id,store) ON DELETE CASCADE
);
CREATE TABLE store_agent_budgets (
 run_id uuid NOT NULL, store text NOT NULL, role text NOT NULL,
 events integer NOT NULL DEFAULT 0, tools integer NOT NULL DEFAULT 0,
 memories jsonb NOT NULL DEFAULT '[]',
 PRIMARY KEY(run_id,store,role),
 FOREIGN KEY(run_id,store) REFERENCES store_environments(run_id,store) ON DELETE CASCADE
);
CREATE TABLE store_frames (
 run_id uuid REFERENCES runs(id) ON DELETE CASCADE, sim integer NOT NULL,
 state jsonb NOT NULL, PRIMARY KEY(run_id,sim)
);
-- Trusted environment workers only. Agents receive bounded tools, never SQL handles.
REVOKE ALL ON store_environments,store_shelves,store_orders,store_workers,
 store_agent_budgets,store_frames FROM PUBLIC;
ALTER TABLE chaos_events DROP CONSTRAINT chaos_events_kind_check;
ALTER TABLE chaos_events ADD CHECK(kind IN ('heavy_rain','metro_strike',
 'restaurant_outage','courier_offline','demand_surge','blocked_aisle',
 'shelf_out_of_stock','robot_breakdown','late_restock_truck'));
