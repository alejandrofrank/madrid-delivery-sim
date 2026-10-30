ALTER TABLE runs ADD COLUMN IF NOT EXISTS chaos_config jsonb;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS recovery_node bigint;

CREATE TABLE chaos_events (
    run_id uuid REFERENCES runs(id) ON DELETE CASCADE,
    id text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('heavy_rain','metro_strike','restaurant_outage',
                                      'courier_offline','demand_surge')),
    district text,
    target text,
    severity double precision NOT NULL CHECK (severity BETWEEN 1 AND 4),
    start_sim integer NOT NULL CHECK (start_sim >= 0),
    end_sim integer NOT NULL CHECK (end_sim > start_sim),
    state text NOT NULL DEFAULT 'scheduled' CHECK (state IN ('scheduled','active','ended')),
    PRIMARY KEY(run_id,id)
);
CREATE TABLE chaos_impacts (
    run_id uuid NOT NULL,
    disruption text NOT NULL,
    order_id text NOT NULL,
    observed_sim integer NOT NULL,
    baseline_eta double precision,
    PRIMARY KEY(run_id,disruption,order_id),
    FOREIGN KEY(run_id,disruption) REFERENCES chaos_events(run_id,id) ON DELETE CASCADE,
    FOREIGN KEY(run_id,order_id) REFERENCES orders(run_id,id) ON DELETE CASCADE
);
CREATE TABLE chaos_work (
    run_id uuid REFERENCES runs(id) ON DELETE CASCADE,
    id text NOT NULL,
    disruption text NOT NULL,
    agent text NOT NULL,
    order_id text NOT NULL,
    state text NOT NULL DEFAULT 'pending' CHECK (state IN ('pending','reserved','done','failed')),
    result jsonb,
    tokens integer NOT NULL DEFAULT 0,
    cost_usd double precision NOT NULL DEFAULT 0,
    completed_sim integer,
    PRIMARY KEY(run_id,id),
    UNIQUE(run_id,disruption,agent,order_id),
    FOREIGN KEY(run_id,disruption,order_id)
        REFERENCES chaos_impacts(run_id,disruption,order_id) ON DELETE CASCADE
);
CREATE TABLE chaos_contacts (
    run_id uuid NOT NULL,
    work_id text NOT NULL,
    order_id text NOT NULL,
    message text NOT NULL,
    eta_sim integer,
    refund_eur double precision NOT NULL DEFAULT 0 CHECK (refund_eur BETWEEN 0 AND 5),
    approval_status text NOT NULL,
    sim_time integer NOT NULL,
    PRIMARY KEY(run_id,work_id),
    FOREIGN KEY(run_id,work_id) REFERENCES chaos_work(run_id,id) ON DELETE CASCADE
);
