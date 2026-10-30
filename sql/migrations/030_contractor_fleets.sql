-- Existing runs retain their original roster and dispatch behavior.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS fleet_config jsonb;
ALTER TABLE couriers ADD COLUMN IF NOT EXISTS fleet_id text NOT NULL DEFAULT 'regular';
CREATE INDEX IF NOT EXISTS couriers_fleet ON couriers(run_id,fleet_id);
