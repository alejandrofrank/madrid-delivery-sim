-- Additive state only: historical routes and roles retain their authority.
ALTER TABLE runs ADD COLUMN IF NOT EXISTS dispatch_config jsonb NOT NULL DEFAULT '{}';
ALTER TABLE couriers ADD COLUMN IF NOT EXISTS idle_since_sim integer NOT NULL DEFAULT 0;
ALTER TABLE couriers ADD COLUMN IF NOT EXISTS completed_jobs integer NOT NULL DEFAULT 0;
ALTER TABLE couriers ADD COLUMN IF NOT EXISTS empty_distance_m double precision NOT NULL DEFAULT 0;
ALTER TABLE couriers ADD COLUMN IF NOT EXISTS reposition_distance_m double precision NOT NULL DEFAULT 0;
ALTER TABLE couriers ADD COLUMN IF NOT EXISTS operating_cost_eur double precision NOT NULL DEFAULT 0;
ALTER TABLE couriers ADD COLUMN IF NOT EXISTS reposition_route jsonb;
ALTER TABLE couriers ADD COLUMN IF NOT EXISTS last_reposition_sim integer NOT NULL DEFAULT -900;
ALTER TABLE couriers ADD COLUMN IF NOT EXISTS leg_accounted_m double precision NOT NULL DEFAULT 0;
ALTER TABLE couriers ADD COLUMN IF NOT EXISTS leg_empty_accounted_m double precision NOT NULL DEFAULT 0;
