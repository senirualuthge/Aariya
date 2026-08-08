-- Rollback for Migration 001
-- Removes trust and contradiction tracking tables

DROP TABLE IF EXISTS trust_history;

DROP TABLE IF EXISTS contradiction_history;

DROP TABLE IF EXISTS episodic_memory;

DROP TABLE IF EXISTS pattern_memory;

DROP TABLE IF EXISTS audit_logs;

-- Note: Cannot easily rollback ALTER TABLE ADD COLUMN in SQLite
-- For Postgres, you would use:
-- ALTER TABLE sessions DROP COLUMN trust_start;
-- ALTER TABLE sessions DROP COLUMN trust_end;
-- ALTER TABLE sessions DROP COLUMN contradiction_avg;
-- ALTER TABLE sessions DROP COLUMN safety_violations;
-- ALTER TABLE sessions DROP COLUMN neural_network_active;