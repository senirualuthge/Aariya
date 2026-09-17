"""
Reflection Engine — evaluates goal outcomes to drive self-improvement.

Produces a reflection record from a goal + result. A small in-memory log keeps
recent reflections so the conscious loop can summarize patterns over time.
"""

import time
from typing import Any, Dict, List


class ReflectionEngine:
    def __init__(self, max_log: int = 100):
        self._log: List[Dict[str, Any]] = []
        self._max = max_log

    def reflect(self, goal: str, result: Dict[str, Any]) -> Dict[str, Any]:
        reflection = {
            "goal": goal,
            "success": bool(result.get("success")),
            "errors": result.get("errors", []),
            "timestamp": time.time(),
        }
        self._log.append(reflection)
        if len(self._log) > self._max:
            self._log.pop(0)
        return reflection

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._log[-limit:]

    def success_rate(self) -> float:
        if not self._log:
            return 0.0
        return sum(1 for r in self._log if r["success"]) / len(self._log)
