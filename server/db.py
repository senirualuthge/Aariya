import sqlite3
import os

DB_PATH = "data/brain_v4.db"

def init_db():
    os.makedirs("data", exist_ok=True)
    conn = get_db_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS personality_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            warmth REAL,
            energy REAL,
            assertiveness REAL,
            formality REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT,
            start_time DATETIME,
            avg_valence REAL,
            avg_arousal REAL,
            valence_volatility REAL
        );

        -- ── AUTONOMY LAYER (persistent proactive cognition) ────────────────
        -- Latest brain snapshot per user so the 24/7 daemon has real state
        -- even when no WebSocket client is connected.
        CREATE TABLE IF NOT EXISTS autonomy_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            valence REAL DEFAULT 0.0,
            arousal REAL DEFAULT 0.0,
            trust REAL DEFAULT 0.5,
            attachment REAL DEFAULT 0.0,
            last_user_message REAL DEFAULT 0.0,
            ts REAL NOT NULL
        );

        -- Self-generated goals (Aariya decides what she wants to do).
        CREATE TABLE IF NOT EXISTS autonomy_goals (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            description TEXT NOT NULL,
            goal_type TEXT NOT NULL DEFAULT 'learn_topic',
            source TEXT DEFAULT 'engine',
            priority REAL DEFAULT 0.5,
            status TEXT DEFAULT 'active',   -- active | completed | failed | suspended
            progress REAL DEFAULT 0.0,
            created_at REAL NOT NULL,
            updated_at REAL
        );

        -- Executable decomposition of a goal (Plan → Approve → Execute).
        CREATE TABLE IF NOT EXISTS autonomy_plans (
            id TEXT PRIMARY KEY,
            goal_id TEXT NOT NULL,
            steps_json TEXT NOT NULL,
            status TEXT DEFAULT 'proposed', -- proposed | awaiting_approval | running | completed | rejected | failed
            risk_level TEXT DEFAULT 'low',
            requires_approval INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            updated_at REAL
        );

        -- Audit log — every autonomous action, always.
        CREATE TABLE IF NOT EXISTS autonomy_actions (
            id TEXT PRIMARY KEY,
            plan_id TEXT,
            goal_id TEXT,
            action_type TEXT NOT NULL,
            params_json TEXT,
            status TEXT DEFAULT 'pending', -- pending | running | completed | failed | rejected
            outcome TEXT,
            ts REAL NOT NULL
        );

        -- Fired initiatives (proactive moments), with delivery status.
        CREATE TABLE IF NOT EXISTS autonomy_initiatives (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            urgency TEXT DEFAULT 'low',
            hint TEXT,
            message TEXT,
            status TEXT DEFAULT 'fired',   -- fired | sent | dismissed
            ts REAL NOT NULL
        );

        -- Knowledge gaps Aariya detected and wants to fill.
        CREATE TABLE IF NOT EXISTS autonomy_gaps (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            context TEXT,
            priority INTEGER DEFAULT 5,
            status TEXT DEFAULT 'pending', -- pending | researching | resolved | failed
            queued_at REAL NOT NULL,
            resolved_at REAL,
            insight TEXT
        );

        -- What she learned while you were away.
        CREATE TABLE IF NOT EXISTS autonomy_insights (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT DEFAULT 'background_research',
            confidence REAL DEFAULT 0.5,
            surfaced INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        );

        -- ── CONTINUITY LAYER (conversational self) ─────────────────────────
        -- Full chronological conversation log per user so Aariya's sense of
        -- "self" survives reconnects and restarts. Every turn is stored with
        -- her private inner thought + the emotional state at the time.
        CREATE TABLE IF NOT EXISTS conversation_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL,          -- 'user' | 'aariya'
            text TEXT NOT NULL,
            thought TEXT,
            valence REAL DEFAULT 0.0,
            trust REAL DEFAULT 0.5,
            ts REAL NOT NULL
        );

        -- Persisted memories — emotionally significant moments recalled
        -- later to shape future responses (durable without ChromaDB).
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            text TEXT NOT NULL,
            valence REAL DEFAULT 0.0,
            trust REAL DEFAULT 0.5,
            significance REAL DEFAULT 0.0,
            created_at REAL NOT NULL
        );

        -- Inner monologue / stream-of-consciousness entries — Aariya's
        -- private life between turns, durable across restarts.
        CREATE TABLE IF NOT EXISTS inner_thoughts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            thought TEXT NOT NULL,
            kind TEXT DEFAULT 'private',  -- 'private' | 'idle' | 'proactive'
            ts REAL NOT NULL
        );

        -- Filesystem confirmation gate (AccessFIles §6/§17): destructive or
        -- mutating FS operations queue here until the user explicitly
        -- confirms via the API. Nothing is executed while status='pending'.
        CREATE TABLE IF NOT EXISTS fs_pending_actions (
            id TEXT PRIMARY KEY,
            action TEXT NOT NULL,          -- 'write_file' | 'append_file' | 'delete_file' | 'run_code'
            path TEXT,
            content TEXT,
            actor TEXT DEFAULT 'ai',       -- who originated: 'ai' | 'user' | agent name
            status TEXT DEFAULT 'pending', -- 'pending' | 'executed' | 'cancelled' | 'failed'
            result TEXT,
            created_ts REAL NOT NULL,
            resolved_ts REAL
        );

        -- External telemetry ingest (/ingest/signal): signals pushed by
        -- mobile / desktop / web clients. Persisted for the history API and
        -- mirrored onto the admin signal bus (dashboard Event Log).
        CREATE TABLE IF NOT EXISTS signals (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            severity TEXT DEFAULT 'info',
            source TEXT DEFAULT 'external',
            payload TEXT NOT NULL,         -- JSON
            timestamp REAL NOT NULL
        );

        -- Device registry (/ingest/device): which clients are connected.
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            user_id TEXT,
            platform TEXT,
            model TEXT,
            os_version TEXT,
            app_version TEXT,
            first_seen REAL,
            last_seen REAL
        );

        -- ── RL LAYER (long-horizon reward grounding) ───────────────────────
        -- Durable, replayable (s, a, r, s', done) transitions for the PPO
        -- conversational-style policy. Written once per turn; read back to
        -- compute n-step returns and to retrain the policy on REAL experience.
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

        -- ── PERSONAL DEVICE AUTHENTICATION (Patch 2/3) ─────────────────────
        -- Trusted personal devices. The long-lived credential is stored only
        -- as a SHA-256 hash; the plaintext exists on the device alone.
        CREATE TABLE IF NOT EXISTS aariya_personal_devices (
            device_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            device_role TEXT NOT NULL
                CHECK (device_role IN ('mobile', 'dashboard')),
            label TEXT NOT NULL,
            platform TEXT NOT NULL,
            credential_hash TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            revoked_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_personal_devices_owner
            ON aariya_personal_devices(owner_id);

        -- One-use, short-lived pairing codes (created by the local CLI, never
        -- by an unauthenticated web endpoint). Only the hash is persisted.
        CREATE TABLE IF NOT EXISTS aariya_pairing_codes (
            code_hash TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            device_role TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            consumed_at REAL
        );

        -- One-use, path-bound, short-lived WebSocket tickets. The device
        -- credential itself is never sent over a WebSocket URL.
        CREATE TABLE IF NOT EXISTS aariya_ws_tickets (
            ticket_hash TEXT PRIMARY KEY,
            device_id TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            path TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            consumed_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_aariya_ws_ticket_expiry
            ON aariya_ws_tickets(expires_at);
    """)
    conn.commit()
    conn.close()

def get_db_connection():
    # timeout=10 gives the 24/7 autonomy daemon + WebSocket handlers room to
    # coexist on concurrent writes without immediate "database is locked".
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn