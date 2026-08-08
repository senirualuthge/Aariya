import os
import hashlib
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("PULSE_DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("PULSE_DATABASE_URL environment variable is required")

_SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    type             TEXT CHECK (type IN ('rss','api','scraper','social')),
    base_url         TEXT,
    credibility_score FLOAT DEFAULT 0.5,
    region           TEXT,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS articles (
    id             TEXT PRIMARY KEY,
    source_id      TEXT,
    title          TEXT NOT NULL,
    url            TEXT UNIQUE NOT NULL,
    description    TEXT,
    content        TEXT,
    author         TEXT,
    published_at   TEXT,
    content_hash   TEXT UNIQUE,
    summary        TEXT,
    importance     INT,
    category       TEXT,
    is_risk        BOOLEAN DEFAULT FALSE,
    key_entities   TEXT[],
    region_tag     TEXT,
    region_tags    TEXT[] DEFAULT '{}',
    language       TEXT DEFAULT 'en',
    clean_text     TEXT,
    word_count     INT DEFAULT 0,
    image_url      TEXT,
    engagement_score FLOAT DEFAULT 0.0,
    sentiment      FLOAT DEFAULT 0.0,
    alert_cooldown_until TIMESTAMPTZ,
    ingested_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS article_chunks (
    id          TEXT PRIMARY KEY,
    article_id  TEXT REFERENCES articles(id),
    chunk_index INT,
    content     TEXT,
    token_count INT
);

CREATE TABLE IF NOT EXISTS embeddings (
    id        TEXT PRIMARY KEY,
    chunk_id  TEXT REFERENCES article_chunks(id),
    embedding VECTOR(384),
    model     TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS embedding_idx
ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE IF NOT EXISTS entities (
    id              TEXT PRIMARY KEY,
    name            TEXT,
    type            TEXT,
    normalized_name TEXT UNIQUE
);

CREATE TABLE IF NOT EXISTS article_entities (
    article_id TEXT REFERENCES articles(id),
    entity_id  TEXT REFERENCES entities(id),
    weight     FLOAT DEFAULT 1.0,
    PRIMARY KEY (article_id, entity_id)
);

CREATE TABLE IF NOT EXISTS topics (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    description TEXT,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS article_topics (
    article_id TEXT REFERENCES articles(id),
    topic_id   TEXT REFERENCES topics(id),
    relevance  FLOAT,
    PRIMARY KEY (article_id, topic_id)
);

CREATE TABLE IF NOT EXISTS trend_signals (
    id              SERIAL PRIMARY KEY,
    category        TEXT NOT NULL,
    velocity        FLOAT DEFAULT 0,
    burst_ratio     FLOAT DEFAULT 1.0,
    source_diversity FLOAT DEFAULT 0,
    trend_score     FLOAT DEFAULT 0,
    status          TEXT DEFAULT 'stable',
    recent_mentions INT DEFAULT 0,
    recorded_at     TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trend_signals_cat_time ON trend_signals(category, recorded_at DESC);

CREATE TABLE IF NOT EXISTS trend_snapshots (
    id              SERIAL PRIMARY KEY,
    category        TEXT NOT NULL,
    trend_score     FLOAT DEFAULT 0,
    status          TEXT DEFAULT 'stable',
    burst_ratio     FLOAT DEFAULT 1.0,
    source_diversity FLOAT DEFAULT 0,
    snapped_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_trend_snapshots_cat_time ON trend_snapshots(category, snapped_at DESC);

CREATE TABLE IF NOT EXISTS trend_predictions (
    id              SERIAL PRIMARY KEY,
    category        TEXT NOT NULL,
    predicted_importance FLOAT DEFAULT 0,
    predicted_breaking_prob FLOAT DEFAULT 0,
    predicted_at    TIMESTAMPTZ DEFAULT now(),
    horizon_hours   INT DEFAULT 6
);
CREATE INDEX IF NOT EXISTS idx_trend_predictions_cat_time ON trend_predictions(category, predicted_at DESC);

CREATE TABLE IF NOT EXISTS event_stream (
    id         TEXT PRIMARY KEY,
    event_type TEXT,
    payload    JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
    id         TEXT PRIMARY KEY,
    email      TEXT UNIQUE,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id         TEXT PRIMARY KEY,
    user_id    TEXT REFERENCES users(id),
    device_token TEXT,
    platform   TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_interactions (
    id            TEXT PRIMARY KEY,
    user_id       TEXT REFERENCES users(id),
    article_id    TEXT REFERENCES articles(id),
    feedback_type TEXT CHECK (feedback_type IN ('view','click','save','share','dismiss')),
    dwell_ms      INT,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_user_interactions_uid_time ON user_interactions(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS user_topic_prefs (
    user_id   TEXT REFERENCES users(id),
    topic     TEXT NOT NULL,
    affinity  FLOAT DEFAULT 1.0,
    PRIMARY KEY (user_id, topic)
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id          TEXT PRIMARY KEY REFERENCES users(id),
    interests        TEXT[] DEFAULT '{}',
    region           TEXT DEFAULT 'global',
    risk_mode        BOOLEAN DEFAULT FALSE,
    alert_threshold  INT DEFAULT 7,
    alert_cooldown_mins INT DEFAULT 30,
    tts_rate         FLOAT DEFAULT 0.45,
    tts_pitch        FLOAT DEFAULT 1.0,
    theme            TEXT DEFAULT 'dark',
    created_at       TIMESTAMPTZ DEFAULT now(),
    updated_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS learned_weights (
    param_key     TEXT PRIMARY KEY,
    param_value   FLOAT NOT NULL,
    sample_count  INT DEFAULT 0,
    updated_at    TIMESTAMPTZ DEFAULT now()
);

INSERT INTO learned_weights (param_key, param_value, sample_count) VALUES
    ('ema_alpha', 0.3, 0),
    ('recency_decay', 0.1, 0),
    ('risk_bonus', 1.2, 0),
    ('base_blend_weight', 0.4, 0),
    ('ml_blend_weight', 0.6, 0),
    ('personalize_blend_weight', 0.5, 0),
    ('trend_impact_weight', 0.35, 0),
    ('trend_diversity_weight', 0.20, 0),
    ('trend_burst_weight', 0.25, 0),
    ('trend_velocity_weight', 0.20, 0),
    ('agent_trend_weight', 0.30, 0),
    ('agent_fact_weight', 0.20, 0),
    ('agent_novelty_weight', 0.15, 0),
    ('agent_pagerank_weight', 0.10, 0),
    ('agent_burst_weight', 0.25, 0)
ON CONFLICT (param_key) DO NOTHING;

-- Users are created on first login — no synthetic default user.
"""


def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    with conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA_SQL)


@contextmanager
def db_cursor():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                yield cur
    finally:
        try:
            conn.close()
        except Exception:
            pass


def get_learned_weight(key: str, default: float = 0.0) -> float:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT param_value FROM learned_weights WHERE param_key = %s", (key,))
            row = cur.fetchone()
            if row:
                return float(row["param_value"])
    except Exception:
        pass
    return default


def update_learned_weight(key: str, value: float, sample_count: int = 0):
    try:
        with db_cursor() as cur:
            cur.execute(
                """INSERT INTO learned_weights (param_key, param_value, sample_count, updated_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (param_key) DO UPDATE SET
                    param_value = EXCLUDED.param_value,
                    sample_count = learned_weights.sample_count + EXCLUDED.sample_count,
                    updated_at = now()""",
                (key, value, sample_count),
            )
    except Exception:
        pass


def get_user_settings(user_id: str) -> dict:
    with db_cursor() as cur:
        cur.execute("SELECT * FROM user_settings WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
    return _default_user_settings(user_id)


def _default_user_settings(user_id: str) -> dict:
    out: dict = {"user_id": user_id}
    try:
        with db_cursor() as cur:
            cur.execute(
                """SELECT
                    AVG(alert_threshold) as avg_threshold,
                    AVG(alert_cooldown_mins) as avg_cooldown,
                    AVG(tts_rate) as avg_rate,
                    AVG(tts_pitch) as avg_pitch,
                    MODE() WITHIN GROUP (ORDER BY region) as common_region,
                    MODE() WITHIN GROUP (ORDER BY theme) as common_theme
                FROM user_settings"""
            )
            row = cur.fetchone()
            if row:
                out["alert_threshold"] = int(row["avg_threshold"] or 7)
                out["alert_cooldown_mins"] = int(row["avg_cooldown"] or 30)
                out["tts_rate"] = float(row["avg_rate"] or 0.45)
                out["tts_pitch"] = float(row["avg_pitch"] or 1.0)
                out["region"] = row["common_region"] or "global"
                out["theme"] = row["common_theme"] or "dark"
                out["risk_mode"] = True
                out["interests"] = ["AI", "economy", "startups"]
                return out
    except Exception:
        pass
    out.update({
        "interests": ["AI", "economy", "startups"],
        "region": "global",
        "risk_mode": True,
        "alert_threshold": 7,
        "alert_cooldown_mins": 30,
        "tts_rate": 0.45,
        "tts_pitch": 1.0,
        "theme": "dark",
    })
    return out


def update_user_settings(user_id: str, settings: dict):
    allowed = {"interests", "region", "risk_mode", "alert_threshold",
               "alert_cooldown_mins", "tts_rate", "tts_pitch", "theme"}
    filtered = {k: v for k, v in settings.items() if k in allowed and v is not None}
    if not filtered:
        return
    cols = ", ".join(filtered.keys())
    vals = list(filtered.values())
    placeholders = ", ".join(["%s"] * len(vals))
    set_clause = ", ".join(f"{k} = EXCLUDED.{k}" for k in filtered)
    with db_cursor() as cur:
        cur.execute(
            f"""INSERT INTO user_settings (user_id, {cols}, updated_at)
            VALUES (%s, {placeholders}, now())
            ON CONFLICT (user_id) DO UPDATE SET {set_clause}, updated_at = now()""",
            [user_id] + vals,
        )


def content_hash(title: str, description: str = "") -> str:
    key = (title + description).encode("utf-8")
    return hashlib.sha256(key).hexdigest()
