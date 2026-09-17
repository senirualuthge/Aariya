"""
AutonomyStore — persistent state for Aariya's autonomy layer.
──────────────────────────────────────────────────────────────
All proactive cognition is persisted to SQLite (data/brain_v4.db) so
the 24/7 daemon survives restarts and never depends on a live
WebSocket connection. This is the single source of truth for:
  - latest brain snapshots (real valence/arousal/trust/attachment)
  - self-generated goals
  - plans (proposed / awaiting_approval / running / completed)
  - action audit log
  - fired initiatives (proactive messages)
  - knowledge gaps + insights learned in the background
"""

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from server.db import get_db_connection


def _now() -> float:
    return time.time()


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class AutonomyStore:
    # ── Snapshots (latest brain state per user) ──────────────────────────────

    def save_snapshot(self, user_id: str, valence: float, arousal: float,
                      trust: float, attachment: float = 0.0,
                      last_user_message: Optional[float] = None) -> None:
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO autonomy_snapshots
                   (user_id, valence, arousal, trust, attachment, last_user_message, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, valence, arousal, trust, attachment,
                 last_user_message if last_user_message is not None else _now(),
                 _now()),
            )
            conn.commit()
        finally:
            conn.close()

    def get_latest_snapshot(self, user_id: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            row = conn.execute(
                """SELECT * FROM autonomy_snapshots WHERE user_id = ?
                   ORDER BY id DESC LIMIT 1""",
                (user_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_max_snapshot_id(self, user_id: Optional[str] = None) -> int:
        """Highest snapshot id persisted — the retrain watermark for the LSTM
        emotion predictor's self-updating cadence (see should_retrain)."""
        conn = get_db_connection()
        try:
            if user_id:
                row = conn.execute(
                    "SELECT COALESCE(MAX(id), 0) AS m FROM autonomy_snapshots "
                    "WHERE user_id = ?", (user_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(MAX(id), 0) AS m FROM autonomy_snapshots",
                ).fetchone()
            return int(row["m"]) if row else 0
        finally:
            conn.close()

    def get_snapshot_count(self, user_id: Optional[str] = None) -> int:
        """Number of autonomy_snapshots rows (per user or all) — for the
        predictor status API's corpus readout."""
        conn = get_db_connection()
        try:
            if user_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM autonomy_snapshots WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM autonomy_snapshots",
                ).fetchone()
            return int(row["c"]) if row else 0
        finally:
            conn.close()

    def get_snapshot_history(self, user_id: Optional[str] = None,
                             limit: int = 20000) -> List[Dict[str, Any]]:
        """Chronological brain snapshots — the training corpus for the LSTM
        emotion predictor (server/systems/emotion/predictor.py)."""
        conn = get_db_connection()
        try:
            if user_id:
                rows = conn.execute(
                    """SELECT * FROM autonomy_snapshots WHERE user_id = ?
                       ORDER BY id ASC LIMIT ?""",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM autonomy_snapshots ORDER BY id ASC LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_session_history(self, user_id: Optional[str] = None,
                            limit: int = 20000) -> List[Dict[str, Any]]:
        """Chronological `sessions` rows (avg_valence / avg_arousal per
        session) — the bootstrap seed for the LSTM emotion predictor, so it
        can train on real session history before per-turn snapshots
        accumulate."""
        conn = get_db_connection()
        try:
            if user_id:
                rows = conn.execute(
                    """SELECT * FROM sessions WHERE user_id = ?
                       ORDER BY start_time ASC LIMIT ?""",
                    (user_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM sessions ORDER BY start_time ASC LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_session_count(self, user_id: Optional[str] = None) -> int:
        """Number of session rows — used by the daemon's retrain-eligibility
        check (bootstrap seed count)."""
        conn = get_db_connection()
        try:
            if user_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM sessions WHERE user_id = ?",
                    (user_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM sessions",
                ).fetchone()
            return int(row["c"]) if row else 0
        finally:
            conn.close()

    # ── Goals ────────────────────────────────────────────────────────────────

    def add_goal(self, description: str, goal_type: str, source: str,
                 priority: float = 0.5, user_id: str = "user_default",
                 goal_id: Optional[str] = None) -> str:
        goal_id = goal_id or _uid("goal")
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO autonomy_goals
                   (id, user_id, description, goal_type, source, priority, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', ?)""",
                (goal_id, user_id, description, goal_type, source, priority, _now()),
            )
            conn.commit()
            return goal_id
        finally:
            conn.close()

    def list_goals(self, user_id: str = "user_default",
                   status: Optional[str] = "active") -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            if status:
                rows = conn.execute(
                    """SELECT * FROM autonomy_goals WHERE user_id = ? AND status = ?
                       ORDER BY priority DESC, created_at DESC""",
                    (user_id, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM autonomy_goals WHERE user_id = ?
                       ORDER BY priority DESC, created_at DESC""",
                    (user_id,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def update_goal(self, goal_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn = get_db_connection()
        try:
            conn.execute(
                f"UPDATE autonomy_goals SET {cols} WHERE id = ?",
                (*fields.values(), goal_id),
            )
            conn.commit()
        finally:
            conn.close()

    def get_goal(self, goal_id: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM autonomy_goals WHERE id = ?", (goal_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ── Plans ────────────────────────────────────────────────────────────────

    def add_plan(self, goal_id: str, steps: List[Dict[str, Any]],
                 risk_level: str = "low", requires_approval: bool = False,
                 status: str = "proposed") -> str:
        plan_id = _uid("plan")
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO autonomy_plans
                   (id, goal_id, steps_json, status, risk_level, requires_approval, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (plan_id, goal_id, json.dumps(steps), status, risk_level,
                 int(requires_approval), _now()),
            )
            conn.commit()
            return plan_id
        finally:
            conn.close()

    def get_plan(self, plan_id: str) -> Optional[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT * FROM autonomy_plans WHERE id = ?", (plan_id,)
            ).fetchone()
            if not row:
                return None
            plan = dict(row)
            plan["steps"] = json.loads(plan.pop("steps_json"))
            return plan
        finally:
            conn.close()

    def list_plans(self, goal_id: Optional[str] = None,
                   status: Optional[str] = None,
                   limit: int = 50) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            query = "SELECT * FROM autonomy_plans"
            clauses, params = [], []
            if goal_id:
                clauses.append("goal_id = ?")
                params.append(goal_id)
            if status:
                clauses.append("status = ?")
                params.append(status)
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            plans = []
            for r in rows:
                plan = dict(r)
                plan["steps"] = json.loads(plan.pop("steps_json"))
                plans.append(plan)
            return plans
        finally:
            conn.close()

    def update_plan(self, plan_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn = get_db_connection()
        try:
            conn.execute(
                f"UPDATE autonomy_plans SET {cols} WHERE id = ?",
                (*fields.values(), plan_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Action audit log ─────────────────────────────────────────────────────

    def log_action(self, action_type: str, plan_id: Optional[str] = None,
                   goal_id: Optional[str] = None, params: Optional[dict] = None,
                   status: str = "pending", outcome: Optional[str] = None) -> str:
        action_id = _uid("act")
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO autonomy_actions
                   (id, plan_id, goal_id, action_type, params_json, status, outcome, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (action_id, plan_id, goal_id, action_type,
                 json.dumps(params or {}), status, outcome, _now()),
            )
            conn.commit()
            return action_id
        finally:
            conn.close()

    def update_action(self, action_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn = get_db_connection()
        try:
            conn.execute(
                f"UPDATE autonomy_actions SET {cols} WHERE id = ?",
                (*fields.values(), action_id),
            )
            conn.commit()
        finally:
            conn.close()

    def list_actions(self, limit: int = 25, plan_id: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            if plan_id:
                rows = conn.execute(
                    "SELECT * FROM autonomy_actions WHERE plan_id = ? ORDER BY ts DESC LIMIT ?",
                    (plan_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM autonomy_actions ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
            actions = []
            for r in rows:
                action = dict(r)
                action["params"] = json.loads(action.pop("params_json") or "{}")
                actions.append(action)
            return actions
        finally:
            conn.close()

    # ── Initiatives (proactive moments) ──────────────────────────────────────

    def add_initiative(self, user_id: str, trigger_type: str, urgency: str,
                       hint: str, message: Optional[str] = None,
                       status: str = "fired") -> str:
        init_id = _uid("init")
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO autonomy_initiatives
                   (id, user_id, trigger_type, urgency, hint, message, status, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (init_id, user_id, trigger_type, urgency, hint, message, status, _now()),
            )
            conn.commit()
            return init_id
        finally:
            conn.close()

    def update_initiative(self, init_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn = get_db_connection()
        try:
            conn.execute(
                f"UPDATE autonomy_initiatives SET {cols} WHERE id = ?",
                (*fields.values(), init_id),
            )
            conn.commit()
        finally:
            conn.close()

    def list_initiatives(self, user_id: str = "user_default",
                         limit: int = 12) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM autonomy_initiatives WHERE user_id = ?
                   ORDER BY ts DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Knowledge gaps ───────────────────────────────────────────────────────

    def add_gap(self, topic: str, context: str = "", priority: int = 5) -> bool:
        """Add a gap (deduplicated by topic). Returns True if newly queued."""
        topic = str(topic).strip()[:240]
        context = str(context).strip()[:500]
        if not topic:
            return False
        conn = get_db_connection()
        try:
            existing = conn.execute(
                "SELECT id FROM autonomy_gaps WHERE topic = ? AND status != 'failed'",
                (topic,),
            ).fetchone()
            if existing:
                return False
            conn.execute(
                """INSERT INTO autonomy_gaps (id, topic, context, priority, status, queued_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (_uid("gap"), topic, context, int(priority), _now()),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def get_pending_gaps(self, limit: int = 5) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM autonomy_gaps WHERE status = 'pending'
                   ORDER BY priority DESC, queued_at ASC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def update_gap(self, gap_id: str, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn = get_db_connection()
        try:
            conn.execute(
                f"UPDATE autonomy_gaps SET {cols} WHERE id = ?",
                (*fields.values(), gap_id),
            )
            conn.commit()
        finally:
            conn.close()

    def list_gaps(self, limit: int = 12) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM autonomy_gaps ORDER BY queued_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ── Insights (what she learned) ──────────────────────────────────────────

    def add_insight(self, topic: str, content: str, source: str = "background_research",
                    confidence: float = 0.5) -> str:
        insight_id = _uid("ins")
        conn = get_db_connection()
        try:
            existing = conn.execute(
                "SELECT id FROM autonomy_insights WHERE topic = ?", (topic,)
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE autonomy_insights SET content = ?, source = ?, confidence = ?,
                       surfaced = 0, created_at = ? WHERE id = ?""",
                    (content, source, confidence, _now(), existing["id"]),
                )
                conn.commit()
                return existing["id"]
            conn.execute(
                """INSERT INTO autonomy_insights
                   (id, topic, content, source, confidence, surfaced, created_at)
                   VALUES (?, ?, ?, ?, ?, 0, ?)""",
                (insight_id, topic, content, source, confidence, _now()),
            )
            conn.commit()
            return insight_id
        finally:
            conn.close()

    def get_unsurfaced_insights(self, limit: int = 5) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM autonomy_insights WHERE surfaced = 0
                   ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def mark_insight_surfaced(self, insight_id: str) -> None:
        conn = get_db_connection()
        try:
            conn.execute(
                "UPDATE autonomy_insights SET surfaced = 1 WHERE id = ?", (insight_id,)
            )
            conn.commit()
        finally:
            conn.close()

    def list_insights(self, limit: int = 12) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM autonomy_insights ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
