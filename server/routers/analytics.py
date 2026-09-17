"""
Analytics Router — /api/analytics/* for the Overview / Personality / Timeline
tabs. All queries run against the REAL SQLite schema created by
`server.db.init_db` and every timestamp is the actual server time — no
hardcoded dates, no fantasy tables.
"""

from datetime import datetime, timezone
import json
from typing import List

from fastapi import APIRouter, HTTPException

from server.db import get_db_connection

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@router.get("/overview")
async def get_overview(user_id: str = "user_default", limit: int = 20):
    """Session summary + trust-relevant totals, computed from the real
    `sessions` table (no separate users table exists)."""
    conn = get_db_connection()
    try:
        cur = conn.execute("""
            SELECT id AS session_id, start_time, avg_valence, avg_arousal,
                   valence_volatility
            FROM sessions
            WHERE user_id = ?
            ORDER BY start_time DESC
            LIMIT ?
        """, (user_id, max(1, min(limit, 100))))
        sessions = [dict(row) for row in cur.fetchall()]

        # Totals derived from the same real rows (there is no users table).
        cur = conn.execute("""
            SELECT COUNT(*) AS total_sessions,
                   MAX(start_time) AS last_session,
                   AVG(avg_valence) AS lifetime_avg_valence
            FROM sessions WHERE user_id = ?
        """, (user_id,))
        user_info = dict(cur.fetchone() or {})

        return {
            "sessions": sessions,
            "user_info": user_info,
            "timestamp": _now_iso(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/personality")
async def get_personality_history(user_id: str = "user_default", limit: int = 10):
    """Historical personality snapshots. Reads the v1 column table first;
    falls back to the v2 JSON-snapshot table the live personality system
    actually writes (`server.systems.personality`), expanding its real
    traits. Empty list is an honest answer when nothing has snapshotted."""
    conn = get_db_connection()
    try:
        cur = conn.execute("""
            SELECT id, timestamp, warmth, energy, assertiveness, formality
            FROM personality_snapshots
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, max(1, min(limit, 100))))
        snapshots = [dict(row) for row in cur.fetchall()]
        if snapshots:
            return snapshots

        # v2 is created lazily by the personality system — ensure it exists
        # so a fresh database answers honestly with [] instead of erroring.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS personality_snapshots_v2 (
                user_id TEXT,
                traits_json TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur = conn.execute("""
            SELECT rowid AS id, user_id, traits_json, timestamp
            FROM personality_snapshots_v2
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, max(1, min(limit, 100))))
        out = []
        for row in cur.fetchall():
            d = dict(row)
            try:
                traits = json.loads(d.pop("traits_json") or "{}")
            except json.JSONDecodeError:
                traits = {}
            d.update(traits)
            out.append(d)
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@router.get("/memories")
async def get_memories(user_id: str = "user_default", limit: int = 50):
    """Significant memories for the Timeline tab — real columns of the
    `memories` table (text/valence/trust/significance/created_at)."""
    conn = get_db_connection()
    try:
        cur = conn.execute("""
            SELECT id AS memory_id, text AS content, valence, trust,
                   significance, created_at AS timestamp
            FROM memories
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (user_id, max(1, min(limit, 200))))
        memories: List[dict] = [dict(row) for row in cur.fetchall()]
        return memories
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
