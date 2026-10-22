CREATE TABLE lab_worlds (
    run_id uuid PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    city jsonb NOT NULL,
    catalogue jsonb NOT NULL,
    catalogue_hash text NOT NULL,
    selected_product text NOT NULL
);
CREATE TABLE lab_stock (
    run_id uuid REFERENCES lab_worlds(run_id) ON DELETE CASCADE,
    store text NOT NULL,
    sku text NOT NULL,
    on_hand integer NOT NULL CHECK (on_hand >= 0),
    reserved integer NOT NULL DEFAULT 0 CHECK (reserved >= 0 AND reserved <= on_hand),
    version integer NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id,store,sku)
);
CREATE TABLE lab_baskets (
    run_id uuid NOT NULL,
    id text NOT NULL,
    store text NOT NULL,
    sku text NOT NULL,
    quantity integer NOT NULL CHECK (quantity > 0),
    status text NOT NULL CHECK (status IN ('reserved','rejected','expired','cancelled')),
    expires_sim integer NOT NULL,
    PRIMARY KEY (run_id,id),
    FOREIGN KEY (run_id,store,sku) REFERENCES lab_stock(run_id,store,sku) ON DELETE CASCADE
);
CREATE TABLE lab_shipments (
    run_id uuid NOT NULL,
    id text NOT NULL,
    store text NOT NULL,
    sku text NOT NULL,
    quantity integer NOT NULL CHECK (quantity > 0),
    expected_sim integer NOT NULL,
    status text NOT NULL DEFAULT 'expected' CHECK (status IN ('expected','delayed','received')),
    PRIMARY KEY (run_id,id),
    FOREIGN KEY (run_id,store,sku) REFERENCES lab_stock(run_id,store,sku) ON DELETE CASCADE
);
CREATE TABLE lab_movements (
    run_id uuid NOT NULL,
    command_key text NOT NULL,
    store text NOT NULL,
    sku text NOT NULL,
    sim_time integer NOT NULL,
    kind text NOT NULL,
    delta_hand integer NOT NULL,
    delta_reserved integer NOT NULL,
    PRIMARY KEY (run_id,command_key),
    FOREIGN KEY (run_id,store,sku) REFERENCES lab_stock(run_id,store,sku) ON DELETE CASCADE
);
