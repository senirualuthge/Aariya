"""
Durable transition store for the PPO conversational-style policy (Track E).

The in-memory `RolloutBuffer` only ever holds one update cycle. Long-horizon
reward needs the (s, a, r, s', done) history on disk so n-step returns and
periodic retraining can draw on REAL accumulated experience — never synthesised
data. This mirrors the lazy-table pattern used elsewhere in the codebase
(`personality_snapshots_v2`, `signals`): the table is created on first use so it
works even when `server.db.init_db` has not been called.
"""

from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from server.db import get_db_connection

_TABLE_SQL = """
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
    )
"""


class RLTransitionStore:
    """Thin SQLite wrapper around the `rl_transitions` table."""

    def __init__(self) -> None:
        self._ready = False

    def _ensure_table(self) -> None:
        if self._ready:
            return
        conn = get_db_connection()
        try:
            conn.execute(_TABLE_SQL)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rl_transitions_user_ts "
                "ON rl_transitions (user_id, ts)"
            )
            conn.commit()
        finally:
            conn.close()
        self._ready = True

    # ── Write ────────────────────────────────────────────────────────────────

    def record(self, *, state, action: int, reward: float, next_state=None,
               done: bool = False, user_id: str = "user_default",
               session_id: Optional[str] = None, ts: Optional[float] = None) -> int:
        """Persist one real transition. Returns the new row id."""
        self._ensure_table()
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "INSERT INTO rl_transitions "
                "(session_id, user_id, ts, state_json, action, reward, "
                " next_state_json, done) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    user_id,
                    float(ts if ts is not None else time.time()),
                    json.dumps(list(state)),
                    int(action),
                    float(reward),
                    json.dumps(list(next_state)) if next_state is not None else None,
                    1 if done else 0,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    # ── Read ─────────────────────────────────────────────────────────────────

    def count(self) -> int:
        self._ensure_table()
        conn = get_db_connection()
        try:
            return int(conn.execute("SELECT COUNT(*) FROM rl_transitions").fetchone()[0])
        finally:
            conn.close()

    def count_since(self, ts: float) -> int:
        self._ensure_table()
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM rl_transitions WHERE ts > ?", (float(ts),)
            ).fetchone()
            return int(row[0])
        finally:
            conn.close()

    def recent(self, limit: int = 500, user_id: Optional[str] = None) -> List[Dict]:
        """The newest `limit` transitions, returned oldest → newest so a corpus
        (or an n-step trajectory) reads in chronological order."""
        self._ensure_table()
        conn = get_db_connection()
        try:
            if user_id:
                cur = conn.execute(
                    "SELECT * FROM ("
                    "  SELECT * FROM rl_transitions WHERE user_id = ? "
                    "  ORDER BY ts DESC, id DESC LIMIT ?"
                    ") ORDER BY ts ASC, id ASC",
                    (user_id, int(limit)),
                )
            else:
                cur = conn.execute(
                    "SELECT * FROM ("
                    "  SELECT * FROM rl_transitions "
                    "  ORDER BY ts DESC, id DESC LIMIT ?"
                    ") ORDER BY ts ASC, id ASC",
                    (int(limit),),
                )
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()

    def latest_actions(self, limit: int = 200) -> List[int]:
        """Actions of the newest `limit` transitions (for status telemetry)."""
        self._ensure_table()
        conn = get_db_connection()
        try:
            cur = conn.execute(
                "SELECT action FROM rl_transitions ORDER BY id DESC LIMIT ?",
                (int(limit),),
            )
            return [int(r[0]) for r in cur.fetchall()]
        finally:
            conn.close()


_store: Optional[RLTransitionStore] = None


def get_transition_store() -> RLTransitionStore:
    global _store
    if _store is None:
        _store = RLTransitionStore()
    return _store
