-- 003_rl_transitions.sql — durable PPO transition log (Track E).
-- Replayable (s, a, r, s', done) rows so long-horizon returns and periodic
-- retraining use REAL accumulated experience rather than in-memory-only data.

CREATE TABLE IF NOT EXISTS rl_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    user_id TEXT NOT NULL DEFAULT 'user_default',
    ts REAL NOT NULL,
    state_json TEXT NOT NULL,
    action INTEGER NOT NULL,
    reward REAL NOT NULL,
    next_state_json TEXT,
    done INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_rl_transitions_user_ts
    ON rl_transitions (user_id, ts);
