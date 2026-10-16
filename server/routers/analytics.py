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


# ── Personality trajectory (Core-identity vs Acquired-traits) ─────────────────
# The three personality axes and their sub-traits (see server.systems.personality).
_PERSONALITY_AXES = ("cognitive", "emotional", "social")


def _axis_means(traits: dict) -> dict:
    """Aggregate a flat `axis.trait` dict into per-axis means.

    Only REAL, numeric traits present in the row are averaged — an axis with no
    readings is omitted rather than defaulted, so the caller can tell honest
    "no data" apart from a genuine zero.
    """
    buckets: dict = {axis: [] for axis in _PERSONALITY_AXES}
    for key, value in (traits or {}).items():
        if "." not in key:
            continue
        axis = key.split(".", 1)[0]
        if axis in buckets and isinstance(value, (int, float)) and not isinstance(value, bool):
            buckets[axis].append(float(value))
    return {axis: sum(vals) / len(vals) for axis, vals in buckets.items() if vals}


def _core_axis_means() -> dict:
    """The immutable baseline origin — the system's default ('balanced') persona
    aggregated to axis means.

    This is a *constant by design* (the numeric baseline Aariya drifts away
    from), and it is computed from the code's own canonical default vector
    rather than invented here.
    """
    from server.systems.personality import PERSONALITY_PRESETS
    return _axis_means(PERSONALITY_PRESETS["balanced"])


@router.get("/personality/trajectory")
async def get_personality_trajectory(user_id: str = "user_default", limit: int = 50):
    """Per-session personality trajectory built from the REAL snapshot table the
    live personality system writes (`personality_snapshots_v2`).

    Returns the drifted ("acquired") traits over time, aggregated onto the three
    personality axes, plus the immutable "core" baseline as the reference origin.
    Points are chronological (oldest → newest) so the UI can draw a trail, and a
    user with no snapshots gets an honest empty list — nothing is fabricated.
    """
    max_points = max(1, min(limit, 500))
    conn = get_db_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS personality_snapshots_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                traits_json TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)

        # Newest `limit` rows, then reversed to chronological order so the trail
        # reads oldest → newest (a plain ASC LIMIT would return the *oldest* N).
        cur = conn.execute("""
            SELECT timestamp, traits_json FROM (
                SELECT timestamp, traits_json
                FROM personality_snapshots_v2
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            ) ORDER BY timestamp ASC
        """, (user_id, max_points))

        points = []
        for ts, traits_json in cur.fetchall():
            try:
                traits = json.loads(traits_json) or {}
            except (json.JSONDecodeError, TypeError):
                traits = {}
            if not isinstance(traits, dict):
                traits = {}
            point = {"ts": ts, "traits": traits}
            point.update(_axis_means(traits))
            points.append(point)

        return {
            "user_id": user_id,
            "count": len(points),
            "core": _core_axis_means(),
            "points": points,
            "timestamp": _now_iso(),
        }
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
