"""
Pending Action Store — the filesystem confirmation gate (AccessFIles §6, §17).

Destructive or mutating filesystem operations requested by the AI never run
immediately. They are queued here with status='pending' and only execute after
an explicit user confirmation through the API. The store is SQLite-backed
(server/db.fs_pending_actions) so queued actions survive restarts — a restart
can never silently auto-approve them.
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from server.db import get_db_connection

logger = logging.getLogger("aariya.safety.pending_actions")

# Actions that may be queued. Anything else is refused outright — the gate
# must never become a generic execution queue.
QUEUEABLE = {"write_file", "append_file", "delete_file", "run_code"}


class PendingActionStore:
    def create(self, action: str, *, path: str = "", content: str = "",
               actor: str = "ai") -> Optional[Dict[str, Any]]:
        """Queue a gated action; returns its row, or None if not queueable."""
        if action not in QUEUEABLE:
            logger.warning("[pending] refused non-queueable action: %s", action)
            return None
        action_id = f"pa_{uuid.uuid4().hex[:12]}"
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO fs_pending_actions
                   (id, action, path, content, actor, status, created_ts)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (action_id, action, path, content, actor, time.time()),
            )
            conn.commit()
        finally:
            conn.close()
        return self.get(action_id)

    def get(self, action_id: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM fs_pending_actions WHERE id = ?", (action_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def list(self, status: str = "pending", limit: int = 50) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM fs_pending_actions WHERE status = ?
                   ORDER BY created_ts DESC LIMIT ?""",
                (status, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def resolve(self, action_id: str, status: str,
                result: str = "") -> Optional[Dict[str, Any]]:
        """Transition to a terminal state ('executed' | 'cancelled' | 'failed').

        Only transitions FROM 'pending' succeed, so an already-executed or
        cancelled action can never be double-executed by a stale confirm call.
        """
        if status not in ("executed", "cancelled", "failed"):
            raise ValueError(f"invalid terminal status: {status}")
        conn = get_db_connection()
        try:
            cur = conn.execute(
                """UPDATE fs_pending_actions
                   SET status = ?, result = ?, resolved_ts = ?
                   WHERE id = ? AND status = 'pending'""",
                (status, result[:2000], time.time(), action_id),
            )
            conn.commit()
            updated = cur.rowcount > 0
        finally:
            conn.close()
        return self.get(action_id) if updated else None


_store: Optional[PendingActionStore] = None


def get_pending_action_store() -> PendingActionStore:
    global _store
    if _store is None:
        _store = PendingActionStore()
    return _store
