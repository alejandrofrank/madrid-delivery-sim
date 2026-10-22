CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS runs (
    id uuid PRIMARY KEY,
    seed integer NOT NULL,
    status text NOT NULL DEFAULT 'ready' CHECK (status IN ('ready','running','complete','failed')),
    sim_time integer NOT NULL DEFAULT 0,
    duration integer NOT NULL DEFAULT 43200,
    wall_seconds double precision NOT NULL DEFAULT 600,
    created_at timestamptz NOT NULL DEFAULT now(),
    error text,
    llm_calls integer NOT NULL DEFAULT 0,
    llm_reserved_tokens integer NOT NULL DEFAULT 0,
    llm_tokens integer NOT NULL DEFAULT 0,
    llm_reserved_usd double precision NOT NULL DEFAULT 0,
    llm_cost_usd double precision NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS locations (
    id text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('hub','store','customer')),
    name text NOT NULL,
    district text NOT NULL,
    node bigint NOT NULL,
    point geometry(Point,4326) NOT NULL,
    osm_id text
);
CREATE INDEX IF NOT EXISTS locations_point_idx ON locations USING gist(point);
CREATE TABLE IF NOT EXISTS couriers (
    run_id uuid REFERENCES runs(id),
    id text NOT NULL,
    hub text REFERENCES locations(id),
    mode text NOT NULL CHECK (mode IN ('bike','moto','van')),
    node bigint NOT NULL,
    point geometry(Point,4326) NOT NULL,
    status text NOT NULL DEFAULT 'idle',
    energy double precision NOT NULL DEFAULT 100 CHECK (energy >= 0 AND energy <= 100),
    distance_m double precision NOT NULL DEFAULT 0,
    shift_end integer NOT NULL DEFAULT 43200,
    PRIMARY KEY (run_id,id)
);
CREATE TABLE IF NOT EXISTS orders (
    run_id uuid REFERENCES runs(id),
    id text NOT NULL,
    store text REFERENCES locations(id),
    customer text REFERENCES locations(id),
    status text NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending','assigned','picked_up','delivered','unserved')),
    courier text,
    created_sim integer NOT NULL,
    ready_sim integer NOT NULL,
    due_sim integer NOT NULL,
    assigned_sim integer,
    delivered_sim integer,
    route jsonb,
    route_m double precision NOT NULL DEFAULT 0,
    cost_eur double precision NOT NULL DEFAULT 0,
    version integer NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id,id),
    FOREIGN KEY (run_id,courier) REFERENCES couriers(run_id,id)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_order_per_courier ON orders(run_id,courier)
    WHERE status IN ('assigned','picked_up');
CREATE TABLE IF NOT EXISTS events (
    id bigserial PRIMARY KEY,
    run_id uuid REFERENCES runs(id),
    topic text NOT NULL,
    producer text NOT NULL,
    payload jsonb NOT NULL,
    dedupe_key text NOT NULL,
    trace_id text NOT NULL,
    parent_id bigint REFERENCES events(id),
    priority integer NOT NULL DEFAULT 0,
    due_sim integer NOT NULL DEFAULT 0,
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    state text NOT NULL DEFAULT 'ready' CHECK (state IN ('ready','leased','done','dead')),
    lease_token uuid,
    lease_until timestamptz,
    available_at timestamptz NOT NULL DEFAULT now(),
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE(run_id,topic,dedupe_key)
);
CREATE INDEX IF NOT EXISTS event_ready_idx ON events(run_id,topic,due_sim,priority DESC,id)
    WHERE state IN ('ready','leased');
CREATE OR REPLACE VIEW dead_letters AS SELECT * FROM events WHERE state = 'dead';
CREATE TABLE IF NOT EXISTS decisions (
    id bigserial PRIMARY KEY,
    run_id uuid REFERENCES runs(id),
    sim_time integer NOT NULL,
    agent text NOT NULL,
    order_id text,
    courier_id text,
    event_id bigint REFERENCES events(id),
    action text NOT NULL,
    detail jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS complaints (
    run_id uuid REFERENCES runs(id),
    id text NOT NULL,
    order_id text NOT NULL,
    text text NOT NULL,
    status text NOT NULL DEFAULT 'open',
    response text,
    requested_refund_eur double precision NOT NULL DEFAULT 0,
    approved_refund_eur double precision NOT NULL DEFAULT 0,
    source text,
    PRIMARY KEY(run_id,id),
    FOREIGN KEY(run_id,order_id) REFERENCES orders(run_id,id)
);
CREATE TABLE IF NOT EXISTS llm_requests (
    event_id bigint PRIMARY KEY REFERENCES events(id),
    run_id uuid REFERENCES runs(id),
    source text NOT NULL DEFAULT 'reserved',
    result jsonb,
    tokens integer NOT NULL DEFAULT 0,
    estimated_usd double precision NOT NULL DEFAULT 0,
    model text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
