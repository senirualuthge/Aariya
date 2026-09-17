"""
Cognitive Kernel — facade wiring the cognition modules into one loop.

Ties together the previously-standalone cognition components (AccessFIles
§36-42, §51-59) into a single object the brain can drive each turn:

    world_model           → evolving representation of user + environment
    executive_controller  → prioritize / select focus among tasks
    attention_manager     → what the system is actively reasoning about
    reflection_engine     → goal/result evaluation for self-improvement
    meta_reasoner         → which agent should handle a task + confidence
    horizon_planner       → long-horizon goal trees with subgoals

`snapshot()` produces a dashboard-ready dict. Everything is defensive: a
failure in any sub-system never breaks the kernel.
"""

import time
from typing import Any, Dict, List, Optional

from server.systems.cognition.world_model import WorldModel
from server.systems.cognition.executive_controller import ExecutiveController
from server.systems.cognition.attention_manager import AttentionManager
from server.systems.cognition.reflection_engine import ReflectionEngine
from server.systems.cognition.meta_reasoner import MetaReasoner
from server.systems.planning.horizon_planner import HorizonPlanner


class CognitiveKernel:
    def __init__(self):
        self.world_model = WorldModel()
        self.executive = ExecutiveController()
        self.attention = AttentionManager()
        self.reflection = ReflectionEngine()
        self.meta = MetaReasoner()
        self.horizon = HorizonPlanner()

    # ── Per-turn integration ─────────────────────────────────────────────────

    def integrate_turn(self, *, text: str = "", emotion: Optional[Dict[str, float]] = None,
                       goals: Optional[List[Dict[str, Any]]] = None,
                       focus: Optional[str] = None) -> Dict[str, Any]:
        """
        Update world model + attention from the latest turn, prioritize any
        incoming goals, and return a summary dict. Safe to call every turn.
        """
        result: Dict[str, Any] = {"tick": time.time()}

        # World model: user context + emotion + goals
        try:
            self.world_model.record_event({
                "type": "user_turn",
                "text": (text or "")[:500],
                "emotion": emotion or {},
            })
            if goals:
                self.world_model.update("goals", goals)
                self.world_model.update("tasks", goals)
        except Exception as e:
            result["world_model_error"] = str(e)[:120]

        # Executive: pick the current focus from tasks if we don't have one
        try:
            tasks = self.world_model.get("tasks", [])
            if focus:
                self.attention.set_focus(focus)
            elif tasks:
                decision = self.executive.select_focus(tasks)
                if decision["status"] == "focused":
                    self.attention.set_focus(decision["focus"].get("objective", str(decision["focus"])))
                result["task_queue"] = self.executive.prioritize(tasks)
        except Exception as e:
            result["executive_error"] = str(e)[:120]
        finally:
            result["focus"] = self.attention.get_focus()

        return result

    def reflect_on(self, goal: str, result: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self.reflection.reflect(goal, result)
        except Exception as e:
            return {"goal": goal, "error": str(e)[:120]}

    def route_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Ask the meta-reasoner which agent handles a task."""
        try:
            return self.meta.evaluate(task)
        except Exception as e:
            return {"error": str(e)[:120], "best_agent": "general_agent"}

    def plan_objective(self, objective: str, subgoals: Optional[List[str]] = None) -> Dict[str, Any]:
        """Create a long-horizon goal tree (with optional subgoals)."""
        try:
            tree = self.horizon.create_goal_tree(objective)
            if tree is None:
                return {"objective": objective, "error": "goal tree creation failed"}
            goals = subgoals or []
            for i, sg in enumerate(goals):
                self.horizon.add_subgoal(
                    tree["id"], sg,  # type: ignore
                    depends_on=(goals[i - 1] if i > 0 else None),
                )  # type: ignore[call-arg]
            return tree
        except Exception as e:
            return {"objective": objective, "error": str(e)[:120]}

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        return {
            "world": self.world_model.snapshot(),
            "focus": self.attention.get_focus(),
            "reflection_success_rate": round(self.reflection.success_rate(), 3),
            "recent_reflections": self.reflection.recent(5),
            "horizon_goals": self.horizon.active(),
        }


_kernel: Optional[CognitiveKernel] = None


def get_cognitive_kernel() -> CognitiveKernel:
    global _kernel
    if _kernel is None:
        _kernel = CognitiveKernel()
    return _kernel
