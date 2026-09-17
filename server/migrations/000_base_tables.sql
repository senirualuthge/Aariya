-- TOLERANT ALTER TABLE sessions ADD COLUMN user_id TEXT;
-- TOLERANT ALTER TABLE sessions ADD COLUMN start_time DATETIME;
-- TOLERANT ALTER TABLE sessions ADD COLUMN end_time DATETIME;
-- TOLERANT ALTER TABLE sessions ADD COLUMN trust_end REAL;
-- TOLERANT ALTER TABLE sessions ADD COLUMN avg_valence REAL;
-- TOLERANT ALTER TABLE sessions ADD COLUMN avg_arousal REAL;
-- TOLERANT ALTER TABLE sessions ADD COLUMN valence_volatility REAL;

-- Migration 000: Base tables for the analytics store.
-- The PostgresManager fallback database (~/.aariya/data.db) may pre-date this
-- migration and hold a LEGACY `sessions`/`users` shape from another subsystem,
-- so columns are added additively (TOLERANT = skip if they already exist).
-- Columns mirror the queries in state_machine.py / memory_hierarchy.py.
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME
);

-- GDPR export (/api/compliance/export-user-data) SELECTs these from the
-- analytics store; create them so the export is structurally complete.
CREATE TABLE IF NOT EXISTS personality_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    traits_json TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    text TEXT,
    valence REAL DEFAULT 0.0,
    trust REAL DEFAULT 0.5,
    significance REAL DEFAULT 0.0,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    start_time DATETIME,
    end_time DATETIME,
    avg_valence REAL,
    avg_arousal REAL,
    valence_volatility REAL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions (user_id, start_time DESC);
