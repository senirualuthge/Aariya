"""
Horizon Planner — long-horizon goal trees with subgoals + dependencies.

Builds and manages a goal tree so multi-step objectives persist beyond a
single turn. Supports adding subgoals, resolving dependencies, and progress
tracking.
"""

import time
from typing import Any, Dict, List, Optional


class HorizonPlanner:
    def __init__(self):
        self._trees: Dict[str, Dict[str, Any]] = {}

    def create_goal_tree(self, objective: str) -> Dict[str, Any]:
        tree = {
            "id": f"goal_{int(time.time())}",
            "objective": objective,
            "subgoals": [],
            "dependencies": [],
            "progress": 0.0,
            "status": "active",
            "created_at": time.time(),
        }
        self._trees[tree["id"]] = tree
        return tree

    def add_subgoal(self, tree_id: str, task: str, *, depends_on: Optional[str] = None) -> Optional[Dict[str, Any]]:
        tree = self._trees.get(tree_id)
        if not tree:
            return None
        subgoal = {"task": task, "done": False, "depends_on": depends_on}
        tree["subgoals"].append(subgoal)
        if depends_on and depends_on not in tree["dependencies"]:
            tree["dependencies"].append(depends_on)
        return subgoal

    def mark_done(self, tree_id: str, task: str) -> bool:
        tree = self._trees.get(tree_id)
        if not tree:
            return False
        for sg in tree["subgoals"]:
            if sg["task"] == task:
                sg["done"] = True
                break
        done = sum(1 for s in tree["subgoals"] if s["done"])
        total = len(tree["subgoals"]) or 1
        tree["progress"] = round(done / total, 2)
        if tree["progress"] >= 1.0:
            tree["status"] = "complete"
        return True

    def get(self, tree_id: str) -> Optional[Dict[str, Any]]:
        return self._trees.get(tree_id)

    def active(self) -> List[Dict[str, Any]]:
        return [t for t in self._trees.values() if t["status"] == "active"]
