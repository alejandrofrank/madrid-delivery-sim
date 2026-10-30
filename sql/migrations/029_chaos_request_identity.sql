-- Preserve caller intent when an automatic target is resolved at activation.
ALTER TABLE chaos_events ADD COLUMN requested_target text;
UPDATE chaos_events SET requested_target=target;
