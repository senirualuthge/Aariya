"""
Executive Controller — prioritizes tasks and selects the current focus.

Mirrors the doc's ExecutiveFunctionSystem (prioritize / select_focus) with
safety: empty input returns an explicit empty status instead of raising.
"""

from typing import Dict, Any, List


class ExecutiveController:
    def prioritize(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort tasks by descending `priority` (missing priority = 0)."""
        return sorted(tasks, key=lambda x: float(x.get("priority", 0.0)), reverse=True)

    def select_focus(self, tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not tasks:
            return {"tasks": [], "status": "empty"}
        ranked = self.prioritize(tasks)
        return {"focus": ranked[0], "status": "focused", "queue": ranked[1:]}
