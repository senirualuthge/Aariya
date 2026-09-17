"""
goal_system.py — self-directed goal system (Agents Swarm Visualize doc, §196-201).

The system sets internal objectives (from reflection + narrative arcs), picks the
top-priority goal, plans actions toward it, and applies small bounded adjustments
to the cognitive domains / personality. This is what moves Aariya from reactive
to intentional:

    Reflection → Goals → Plans → Actions → Behavior

Kept to 4 goal templates (not 20) and small per-step adjustments, per the doc's
"keep it simple or you'll destabilize the system" warning.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── Models ────────────────────────────────────────────────────────────────────

@dataclass
class Goal:
    id: str
    goal_type: str            # "stabilize", "build_trust", ...
    priority: float           # 0–1
    progress: float = 0.0     # 0–1
    created_at: float = field(default_factory=time.time)
    target: Dict[str, float] = field(default_factory=dict)


@dataclass
class Plan:
    goal_id: str
    actions: List[str]


# ── Templates & action vocabulary ─────────────────────────────────────────────

GOAL_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "stabilize": {"target": {"conflict": 0.2}},
    "build_trust": {"target": {"trust": 0.8}},
    "increase_curiosity": {"target": {"curiosity": 0.75}},
    "reduce_risk": {"target": {"risk": 0.2}},
}

# Keep the action vocabulary small + grounded (doc §B).
ACTIONS: List[str] = [
    "increase_empathy",
    "increase_reasoning",
    "reduce_volatility",
    "increase_curiosity",
    "decrease_risk",
]


def create_goal(goal_type: str, priority: float) -> Goal:
    template = GOAL_TEMPLATES[goal_type]
    return Goal(
        id=f"{goal_type}_{int(time.time() * 1000)}",
        goal_type=goal_type,
        priority=priority,
        target=template["target"],
    )


def generate_goals(reflection: Any, arcs: Dict[str, Any]) -> List[Goal]:
    """
    Goals come from reflection + narrative arcs, not randomly.
    Returns a short list sorted by priority desc.
    """
    goals: List[Goal] = []
    stability = getattr(reflection, "stability", 0.5)
    alignment = getattr(reflection, "alignment", 0.5)

    if stability < 0.4:
        goals.append(create_goal("stabilize", 0.9))
    if alignment < 0.5:
        goals.append(create_goal("build_trust", 0.7))

    for arc_name, arc in (arcs or {}).items():
        strength = getattr(arc, "strength", 0.0)
        if arc_name == "curiosity_arc" and strength > 0.5:
            goals.append(create_goal("increase_curiosity", 0.6))
        elif arc_name == "conflict_arc" and strength > 0.5:
            goals.append(create_goal("reduce_risk", 0.8))

    return sorted(goals, key=lambda g: g.priority, reverse=True)


# ── Evaluation ────────────────────────────────────────────────────────────────

def evaluate_goal(goal: Goal, synoptic: Dict[str, float], personality: Dict[str, float]) -> Goal:
    """Measure how close the current state is to the goal's target state."""
    if not goal.target:
        return goal
    progress = 0.0
    for k, target_val in goal.target.items():
        current = synoptic.get(k, personality.get(k, 0.5))
        diff = abs(target_val - current)
        progress += (1 - diff)
    goal.progress = max(0.0, min(1.0, progress / len(goal.target)))
    return goal


# ── Planning ──────────────────────────────────────────────────────────────────

def create_plan(goal: Goal) -> Plan:
    actions: List[str] = []
    if goal.goal_type == "stabilize":
        actions += ["reduce_volatility", "increase_reasoning"]
    elif goal.goal_type == "build_trust":
        actions += ["increase_empathy"]
    elif goal.goal_type == "increase_curiosity":
        actions += ["increase_curiosity", "increase_reasoning"]
    elif goal.goal_type == "reduce_risk":
        actions += ["decrease_risk", "increase_reasoning"]
    return Plan(goal_id=goal.id, actions=actions)


# ── Execution ─────────────────────────────────────────────────────────────────

def apply_actions(domains: Dict[str, float], personality: Dict[str, float],
                  actions: List[str]) -> tuple:
    """
    Apply goal-driven actions as small bounded adjustments. Returns
    (domains, personality) — mutations are kept tiny per the doc.
    """
    domains = dict(domains)
    personality = dict(personality)

    for action in actions:
        if action == "increase_empathy":
            personality["empathy"] = personality.get("empathy", 0.5) + 0.02
        elif action == "increase_reasoning":
            domains["reasoning"] = domains.get("reasoning", 0.0) + 0.03
        elif action == "reduce_volatility":
            domains = {k: v * 0.95 for k, v in domains.items()}
        elif action == "increase_curiosity":
            personality["curiosity"] = personality.get("curiosity", 0.5) + 0.02
        elif action == "decrease_risk":
            domains["risk"] = domains.get("risk", 0.0) * 0.9

    return domains, personality


# ── Orchestration convenience ─────────────────────────────────────────────────

class GoalSystem:
    """Stateful goal lifecycle: generate → pick → evaluate → plan → execute."""

    def __init__(self):
        self.active_goal: Optional[Goal] = None
        self.active_plan: Optional[Plan] = None
        self.goal_history: List[Goal] = []

    def step(self, reflection: Any, arcs: Dict[str, Any],
             synoptic: Dict[str, float], personality: Dict[str, float]) -> tuple:
        """
        One full loop iteration. Returns (active_goal, plan, domains, personality)
        after applying the plan's actions to the given domains/personality.
        """
        goals = generate_goals(reflection, arcs)
        self.active_goal = goals[0] if goals else None
        if self.active_goal:
            self.active_goal = evaluate_goal(self.active_goal, synoptic, personality)
            self.active_plan = create_plan(self.active_goal)
            domains, personality = apply_actions(
                synoptic, personality, self.active_plan.actions
            )
        else:
            self.active_plan = None
            domains = dict(synoptic)
        return self.active_goal, self.active_plan, domains, personality
