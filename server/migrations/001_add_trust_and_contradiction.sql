-- Migration 001: Add Trust and Contradiction Tracking
-- This migration adds tables for trust history, contradiction memory,
-- multi-timescale memory hierarchy, and audit logs for compliance.

-- Trust History Table
CREATE TABLE IF NOT EXISTS trust_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT,
    trust_score REAL NOT NULL,
    trust_delta REAL,
    trigger_event TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id),
    FOREIGN KEY (session_id) REFERENCES sessions (session_id)
);

CREATE INDEX IF NOT EXISTS idx_trust_history_user ON trust_history (user_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_trust_history_session ON trust_history (session_id);

-- Contradiction History Table
CREATE TABLE IF NOT EXISTS contradiction_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT,
    turn_number INTEGER,
    face_valence REAL,
    face_arousal REAL,
    face_confidence REAL,
    voice_valence REAL,
    voice_arousal REAL,
    voice_confidence REAL,
    text_sentiment REAL,
    text_confidence REAL,
    contradiction_score REAL NOT NULL,
    contradiction_ema REAL NOT NULL,
    confidence_mean REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id),
    FOREIGN KEY (session_id) REFERENCES sessions (session_id)
);

CREATE INDEX IF NOT EXISTS idx_contradiction_user ON contradiction_history (user_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_contradiction_session ON contradiction_history (session_id, turn_number);

-- Episodic Memory Table (Conversation Summaries)
CREATE TABLE IF NOT EXISTS episodic_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT,
    summary TEXT NOT NULL,
    emotional_context TEXT,
    importance REAL DEFAULT 0.5,
    trust_level_at_time REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id),
    FOREIGN KEY (session_id) REFERENCES sessions (session_id)
);

CREATE INDEX IF NOT EXISTS idx_episodic_user ON episodic_memory (
    user_id,
    importance DESC,
    timestamp DESC
);

CREATE INDEX IF NOT EXISTS idx_episodic_session ON episodic_memory (session_id);

-- Pattern Memory Table (Behavioral Patterns)
CREATE TABLE IF NOT EXISTS pattern_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    pattern_type TEXT NOT NULL, -- 'behavioral', 'emotional', 'conversational', 'contradiction'
    pattern_description TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    occurrences INTEGER DEFAULT 1,
    first_observed DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_observed DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);

CREATE INDEX IF NOT EXISTS idx_pattern_user ON pattern_memory (
    user_id,
    pattern_type,
    confidence DESC
);

CREATE INDEX IF NOT EXISTS idx_pattern_type ON pattern_memory (
    pattern_type,
    last_observed DESC
);

-- Audit Logs Table (Compliance & Security)
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    action_type TEXT NOT NULL, -- 'personality_reset', 'trust_override', 'model_version_change', 'admin_action', 'data_export', 'data_deletion'
    action_details TEXT,
    performed_by TEXT,
    ip_address TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs (user_id, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_logs (action_type, timestamp DESC);

-- Add new columns to sessions table for enhanced tracking
ALTER TABLE sessions ADD COLUMN trust_start REAL DEFAULT 0.5;

ALTER TABLE sessions ADD COLUMN trust_end REAL DEFAULT 0.5;

ALTER TABLE sessions ADD COLUMN contradiction_avg REAL DEFAULT 0.0;

ALTER TABLE sessions ADD COLUMN safety_violations INTEGER DEFAULT 0;

ALTER TABLE sessions
ADD COLUMN neural_network_active INTEGER DEFAULT 0;