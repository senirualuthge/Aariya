"""
Skill Registry — reusable named workflows (skills) with execution + history.

Skills are learned/repeated workflows (e.g. "coding_startup"). `execute`
returns the stored workflow steps; a `record_outcome` keeps a small feedback
log so self-improvement can rank skills.
"""

import time
from typing import Any, Dict, List, Optional


class SkillRegistry:
    def __init__(self):
        self.skills: Dict[str, Dict[str, Any]] = {}
        self._outcomes: List[Dict[str, Any]] = []

    def register(self, name: str, workflow: Any, *, metadata: Optional[Dict[str, Any]] = None) -> None:
        self.skills[name] = {
            "workflow": workflow,
            "metadata": metadata or {},
            "created_at": time.time(),
        }

    def unregister(self, name: str) -> bool:
        return self.skills.pop(name, None) is not None

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return self.skills.get(name)

    def execute(self, name: str) -> Optional[Any]:
        skill = self.skills.get(name)
        return skill["workflow"] if skill else None

    def list(self) -> List[str]:
        return sorted(self.skills)

    def record_outcome(self, name: str, *, success: bool, notes: str = "") -> None:
        self._outcomes.append({
            "skill": name,
            "success": bool(success),
            "notes": notes,
            "timestamp": time.time(),
        })
        # Update a running success rate on the skill record.
        skill = self.skills.get(name)
        if skill:
            entries = [o for o in self._outcomes if o["skill"] == name]
            skill["metadata"]["success_rate"] = (
                sum(1 for e in entries if e["success"]) / len(entries)
            )
