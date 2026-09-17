"""
Skill Synthesis (AccessFIles §49, §50 — gap: unwired).

Learns new reusable skills from repeated successful workflows instead of only
replaying hand-registered ones:

  observe_turn(workflow_id, steps, success) → tracks how often a workflow runs
  synthesize()                              → promotes a workflow with >=
                                              MIN_REPETITIONS successful runs
                                              into a registered SkillRegistry skill
  suggest_skill(name, workflow)             → helper to pre-seed a known skill

The registry also feeds a reusable `list_skills` helper so the swarm's planner
can pick the best-known workflow for a goal.
"""

import time
from typing import Any, Dict, List, Optional

from server.systems.skills.skill_registry import SkillRegistry

MIN_REPETITIONS = 3
MIN_SUCCESS_RATE = 0.7


class SkillSynthesis:
    def __init__(self, registry: Optional[SkillRegistry] = None):
        self.registry = registry or SkillRegistry()
        # workflow_id -> observed runs
        self._observed: Dict[str, List[Dict[str, Any]]] = {}

    def observe_turn(self, workflow_id: str, steps: List[str],
                     success: bool, *, metadata: Optional[Dict[str, Any]] = None) -> None:
        self._observed.setdefault(workflow_id, []).append({
            "steps": list(steps),
            "success": bool(success),
            "ts": time.time(),
            "metadata": metadata or {},
        })

    def synthesize(self, *, force: bool = False) -> List[str]:
        """
        Promote repeated successful workflows into registered skills.
        Returns the names of newly created skills.
        """
        created = []
        for wid, runs in self._observed.items():
            if len(runs) < MIN_REPETITIONS and not force:
                continue
            successes = sum(1 for r in runs if r["success"])
            rate = successes / len(runs)
            if rate < MIN_SUCCESS_RATE and not force:
                continue
            if self.registry.get(wid):
                continue
            template_steps = self._most_common_steps(runs)
            self.registry.register(
                wid,
                {"steps": template_steps},
                metadata={
                    "source": "synthesized",
                    "success_rate": round(rate, 3),
                    "occurrences": len(runs),
                    "synthesized_at": time.time(),
                },
            )
            created.append(wid)
        return created

    @staticmethod
    def _most_common_steps(runs: List[Dict[str, Any]]) -> List[str]:
        """Pick the step sequence from the most-repeated workflow variant."""
        from collections import Counter
        variants = Counter(tuple(r["steps"]) for r in runs)
        return list(variants.most_common(1)[0][0])

    def suggest_skill(self, name: str, workflow: Any, *, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Pre-seed a known skill (e.g. "coding_startup" from the docs)."""
        self.registry.register(name, workflow, metadata=metadata)

    def best_skill_for(self, goal_keyword: str) -> Optional[str]:
        """Pick the highest-success-rate registered skill matching a keyword."""
        best, best_rate = None, -1.0
        for name in self.registry.list():
            skill = self.registry.get(name)
            if not skill or goal_keyword not in name:
                continue
            rate = float(skill.get("metadata", {}).get("success_rate", 0.5))
            if rate > best_rate:
                best, best_rate = name, rate
        return best

    def summary(self) -> Dict[str, Any]:
        return {
            "skills": self.registry.list(),
            "observed_workflows": list(self._observed),
            "recent_outcomes": self.registry._outcomes[-5:],
        }


def get_skill_synthesis() -> SkillSynthesis:
    return SkillSynthesis()
