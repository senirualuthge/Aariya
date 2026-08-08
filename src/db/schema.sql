-- Retention Analytics Database Schema
-- Privacy-safe, anonymized, local-only

-- Users table (anonymized)
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    install_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_session DATETIME,
    total_sessions INTEGER DEFAULT 0
);

-- Sessions table (core retention metrics)
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME,
    
    -- Emotion metrics
    avg_valence REAL DEFAULT 0,
    avg_arousal REAL DEFAULT 0,
    valence_volatility REAL DEFAULT 0,
    
    -- Retention metrics
    ecs REAL DEFAULT 0,  -- Emotional Continuity Score (0-100)
    psi REAL DEFAULT 0,  -- Personality Satisfaction Index (-1 to +1)
    nse INTEGER DEFAULT 0,  -- Natural Session End (1 = yes, 0 = no)
    rls REAL DEFAULT 1.0,  -- Return Latency Score
    mrs REAL DEFAULT 0,  -- Memory Recall Success (0-1)
    
    -- Metadata
    duration_sec INTEGER DEFAULT 0,
    intervention_triggered INTEGER DEFAULT 0,
    
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Personality snapshots (weekly)
CREATE TABLE IF NOT EXISTS personality_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    
    -- Personality axes
    warmth REAL DEFAULT 0,
    energy REAL DEFAULT 0.5,
    assertiveness REAL DEFAULT 0.5,
    formality REAL DEFAULT 0.5,
    
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- Memories (episodic)
CREATE TABLE IF NOT EXISTS memories (
    memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    session_id TEXT,
    type TEXT NOT NULL,  -- 'short_term' or 'long_term'
    content TEXT NOT NULL,
    emotion_context TEXT,  -- JSON: {valence, arousal}
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    importance REAL DEFAULT 0.5,
    
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_time ON sessions(start_time);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(type);
