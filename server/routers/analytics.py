from fastapi import APIRouter, HTTPException, Query
from server.db import get_db_connection
from typing import List, Optional
import json

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

@router.get("/overview")
async def get_overview(user_id: str = "user_default", limit: int = 20):
    """
    Returns a summary of sessions and trust trends for the Overview tab.
    """
    conn = get_db_connection()
    try:
        # Get Sessions
        cur = conn.execute("""
            SELECT session_id, start_time, end_time, avg_valence, avg_arousal, duration_sec
            FROM sessions
            WHERE user_id = ?
            ORDER BY start_time DESC
            LIMIT ?
        """, (user_id, limit))
        sessions = [dict(row) for row in cur.fetchall()]
        
        # Get latest Trust from user table
        cur = conn.execute("SELECT total_sessions, last_session FROM users WHERE user_id = ?", (user_id,))
        user_info = dict(cur.fetchone()) if cur.rowcount != 0 else {}

        return {
            "sessions": sessions,
            "user_info": user_info,
            "timestamp": "2026-04-07T03:42:00Z" # Standard ISO for sync
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/personality")
async def get_personality_history(user_id: str = "user_default", limit: int = 10):
    """
    Returns historical personality snapshots for the Personality tab.
    """
    conn = get_db_connection()
    try:
        cur = conn.execute("""
            SELECT snapshot_id, timestamp, warmth, energy, assertiveness, formality
            FROM personality_snapshots
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, limit))
        snapshots = [dict(row) for row in cur.fetchall()]
        return snapshots
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@router.get("/memories")
async def get_memories(user_id: str = "user_default", limit: int = 50):
    """
    Returns session memories for the Timeline tab.
    """
    conn = get_db_connection()
    try:
        cur = conn.execute("""
            SELECT memory_id, session_id, type, content, importance, timestamp
            FROM memories
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, limit))
        memories = [dict(row) for row in cur.fetchall()]
        return memories
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()
