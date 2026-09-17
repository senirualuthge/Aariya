"""
Goal Management Engine (NEWPredictionPRT2 §"1. Goal Management Engine").

AARIYA handles tasks but doesn't maintain long-term objectives. This module
turns short-lived plans into persisted, progress-tracked goals:

    User Goal
        ↓
    Goal Tracker
        ↓
    Subgoal Generator
        ↓
    Progress Monitor
        ↓
    Executive

The doc's class contract is implemented verbatim:

    class Goal:
        id, description, progress(0-100), subgoals, status("active"|"completed")

    class GoalManager:
        create_goal(goal)             → goal.id
        update_progress(goal_id, value) → clamps to [0,100], completes at 100
        next_action(goal_id)          → active subgoal / description / unavailable

Plus the doc's memory contract — "Store goals inside memory":

    { "goal": "Build AARIYA", "progress": 72, "next_step": "Implement X" }

Goals persist to JSON so objectives survive restarts, and progress updates
are idempotent.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.goal_manager")


class Goal:
    """A long-term objective with subgoals, 0-100 progress, and a lifecycle."""

    def __init__(self, goal_id: str, description: str):
        self.id = goal_id
        self.description = description
        self.progress: float = 0
        self.subgoals: List[Dict[str, Any]] = []
        self.status = "active"
        self.created_at = time.time()
        self.completed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "progress": self.progress,
            "subgoals": self.subgoals,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Goal":
        g = cls(str(data.get("id", "")), str(data.get("description", "")))
        g.progress = float(data.get("progress", 0))
        g.subgoals = list(data.get("subgoals", []))
        g.status = str(data.get("status", "active"))
        g.created_at = float(data.get("created_at", g.created_at))
        g.completed_at = data.get("completed_at")
        return g


class GoalManager:
    """Persisted registry of long-term goals with automatic progress tracking.

        manager.create_goal("Become an AI engineer", subgoals=[...])
        manager.update_progress(goal_id, 42)
        manager.next_action(goal_id)   → the active subgoal / description
        manager.summary()              → the doc's memory snapshot
    """

    def __init__(self, persist_path: Optional[str] = None):
        self.goals: Dict[str, Goal] = {}
        self.persist_path = persist_path
        if persist_path:
            self._load()

    # ── Goal lifecycle ────────────────────────────────────────────────────────

    def create_goal(self, goal: Goal) -> str:
        self.goals[goal.id] = goal
        self._save()
        return goal.id

    def create_goal_from(self, description: str, subgoals: Optional[List[str]] = None) -> str:
        """Convenience: build + register a goal from a description and optional
        subgoal list (Subgoal Generator). Returns the goal id."""
        gid = f"goal_{int(time.time() * 1000)}"
        goal = Goal(gid, description)
        for i, sg in enumerate(subgoals or []):
            goal.subgoals.append({
                "id": f"{gid}_sg{i}",
                "description": sg,
                "status": "active",
            })
        return self.create_goal(goal)

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        return self.goals.get(goal_id)

    def active_goals(self) -> List[Goal]:
        return [g for g in self.goals.values() if g.status == "active"]

    # ── Progress tracking (Progress Monitor) ──────────────────────────────────

    def update_progress(self, goal_id: str, value: float) -> Dict[str, Any]:
        """Clamp progress to [0,100]; auto-complete the goal at 100."""
        goal = self.goals.get(goal_id)
        if not goal:
            return {"status": "unknown_goal", "goal_id": goal_id}
        goal.progress = min(100, max(0, float(value)))
        if goal.progress >= 100:
            goal.status = "completed"
            goal.completed_at = goal.completed_at or time.time()
        else:
            goal.status = "active"
        self._save()
        return {"status": goal.status, "goal_id": goal_id, "progress": goal.progress}

    def complete_subgoal(self, goal_id: str, subgoal_id: str) -> Dict[str, Any]:
        """Mark one subgoal done and auto-advance the goal's progress to the
        share of completed subgoals (automatic progress tracking)."""
        goal = self.goals.get(goal_id)
        if not goal:
            return {"status": "unknown_goal"}
        for sg in goal.subgoals:
            if sg.get("id") == subgoal_id:
                sg["status"] = "completed"
                break
        if goal.subgoals:
            done = sum(1 for sg in goal.subgoals if sg.get("status") == "completed")
            goal.progress = round(done * 100 / len(goal.subgoals), 1)
        if goal.progress >= 100:
            goal.status = "completed"
            goal.completed_at = goal.completed_at or time.time()
        self._save()
        return {"status": goal.status, "goal_id": goal_id, "progress": goal.progress}

    # ── Executive: next action ────────────────────────────────────────────────

    def next_action(self, goal_id: str) -> Dict[str, Any]:
        """Return the first active subgoal, or the goal description itself when
        the goal has no subgoals. Unavailable for unknown/completed goals."""
        goal = self.goals.get(goal_id)
        if not goal or goal.status != "active":
            return {"status": "unavailable", "goal_id": goal_id}
        if goal.subgoals:
            for sg in goal.subgoals:
                if sg.get("status") == "active":
                    return {"status": "active", "goal_id": goal_id,
                            "action": sg.get("description"), "subgoal_id": sg.get("id")}
        return {"status": "active", "goal_id": goal_id, "action": goal.description}

    def next_steps(self) -> List[Dict[str, Any]]:
        """next_action() for every active goal — the daemon's work queue."""
        out = []
        for gid in sorted(self.goals):
            if self.goals[gid].status == "active":
                na = self.next_action(gid)
                if na.get("status") == "active":
                    na["goal"] = self.goals[gid].description
                    out.append(na)
        return out

    # ── Memory contract / summary ─────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """The doc's in-memory representation:
        { "goal": "Build AARIYA", "progress": 72, "next_step": "Implement X" }"""
        active = self.active_goals()
        if not active:
            return {"goals": [], "active_count": 0}
        snapshots = []
        for g in active:
            na = self.next_action(g.id)
            snapshots.append({
                "goal": g.description,
                "progress": g.progress,
                "next_step": na.get("action") if na.get("status") == "active" else None,
                "goal_id": g.id,
                "subgoals": len(g.subgoals),
                "completed_subgoals": sum(1 for sg in g.subgoals if sg.get("status") == "completed"),
            })
        return {"goals": snapshots, "active_count": len(snapshots)}

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        if not self.persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self.persist_path) or ".", exist_ok=True)
            with open(self.persist_path, "w", encoding="utf-8") as f:
                json.dump({"goals": [g.to_dict() for g in self.goals.values()]}, f, indent=2)
        except OSError as exc:
            logger.warning("[GoalManager] persist failed: %s", exc)

    def _load(self) -> None:
        if not self.persist_path:
            return
        try:
            if not os.path.exists(self.persist_path):
                return
            with open(self.persist_path, encoding="utf-8") as f:
                data = json.load(f)
            self.goals = {g.id: g for g in map(Goal.from_dict, data.get("goals", []))}
            logger.info("[GoalManager] loaded %d goals", len(self.goals))
        except Exception as exc:
            logger.warning("[GoalManager] load failed (fresh start): %s", exc)
