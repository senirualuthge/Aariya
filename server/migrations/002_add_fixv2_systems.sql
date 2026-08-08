-- Migration 002: Fixv2 Policy Router, IOM, and Memory Recall Logging
-- Adds: router_logs, interaction_outcomes, memory_recall_log
-- Extends: sessions table with IOM reward columns

-- Router Log Table (training dataset for future neural social policy)
CREATE TABLE IF NOT EXISTS router_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    selected_mode TEXT NOT NULL,
    tone TEXT,
    trust REAL,
    complexity REAL,
    latency_budget_ms REAL,
    contradiction_ema REAL,
    guarded INTEGER DEFAULT 0,
    outcome_latency_ms REAL,
    user_interrupt INTEGER DEFAULT 0,
    router_us REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_router_session ON router_logs (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_router_mode ON router_logs (
    selected_mode,
    created_at DESC
);

-- Interaction Outcomes Table (per-turn IOM reward log)
CREATE TABLE IF NOT EXISTS interaction_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    reward_turn REAL,
    delta_valence REAL,
    engagement REAL,
    latency_ms REAL,
    user_interrupt INTEGER DEFAULT 0,
    ai_interrupt INTEGER DEFAULT 0,
    memory_used INTEGER DEFAULT 0,
    trust_delta REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_outcomes_session ON interaction_outcomes (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_outcomes_user ON interaction_outcomes (user_id, created_at DESC);

-- Memory Recall Log (tracks recall events for reuse penalty)
CREATE TABLE IF NOT EXISTS memory_recall_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    user_reaction TEXT DEFAULT 'pending', -- 'positive' | 'neutral' | 'negative' | 'pending'
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_recall_memory ON memory_recall_log (memory_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_recall_turn ON memory_recall_log (turn_id);

-- Extend sessions table with IOM session-level reward columns
ALTER TABLE sessions ADD COLUMN reward_session REAL DEFAULT NULL;

ALTER TABLE sessions ADD COLUMN valence_trend REAL DEFAULT NULL;

ALTER TABLE sessions ADD COLUMN avg_latency_ms REAL DEFAULT NULL;

ALTER TABLE sessions ADD COLUMN interrupt_rate REAL DEFAULT NULL;

-- Add memory_type column to episodic_memory for MRP type-based filtering
ALTER TABLE episodic_memory
ADD COLUMN memory_type TEXT DEFAULT 'episodic';

ALTER TABLE episodic_memory
ADD COLUMN created_at DATETIME DEFAULT CURRENT_TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_episodic_type ON episodic_memory (
    user_id,
    memory_type,
    created_at DESC
);