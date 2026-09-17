"""
hierarchical_goals.py — multi-level goal system (Agents Swarm Visualize doc §202-207).

Levels:
    L1 = immediate   (actions)
    L2 = tactical    (subgoals)
    L3 = strategic   (long-lived goals from STRATEGIC_TEMPLATES)

Pipeline per the doc:
    generate goals (L1–L3) → arbitration (score + cap active) → hierarchical
    planning (decompose → actions) → conflict resolution.

Bounded exactly as the doc warns: MAX_DEPTH=2, MAX_ACTIONS=3, max_active=2.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

L1, L2, L3 = 1, 2, 3  # immediate / tactical / strategic


@dataclass
class HierarchicalGoal:
    id: str
    goal_type: str
    level: int                      # 1, 2, 3
    priority: float
    progress: float = 0.0
    parent_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    target: Dict[str, float] = field(default_factory=dict)
    children: List["HierarchicalGoal"] = field(default_factory=list)


STRATEGIC_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "maintain_stability": {"target": {"conflict": 0.2}},
    "build_relationship": {"target": {"trust": 0.8}},
    "expand_knowledge": {"target": {"curiosity": 0.8}},
}

MAX_DEPTH = 2       # don't decompose deeper than this
MAX_ACTIONS = 3     # limit execution per turn
MAX_ACTIVE = 2      # only 2 active goals at a time (doc: "VERY IMPORTANT")

# Conflicting action pairs — the second of a pair is dropped.
CONFLICTS = {
    ("increase_empathy", "reduce_risk"),
}


def create_goal(goal_type: str, level: int, priority: float,
                parent_id: Optional[str] = None) -> HierarchicalGoal:
    template = STRATEGIC_TEMPLATES.get(goal_type, {})
    return HierarchicalGoal(
        id=f"{goal_type}_{int(time.time() * 1000)}",
        goal_type=goal_type,
        level=level,
        priority=priority,
        parent_id=parent_id,
        target=dict(template.get("target", {})),
    )


def create_subgoal(goal_type: str, parent_id: str) -> HierarchicalGoal:
    return create_goal(goal_type, L2, 0.6, parent_id=parent_id)


# ── 1. Generation (L1–L3) ─────────────────────────────────────────────────────

def generate_strategic_goals(reflection: Any, arcs: Dict[str, Any]) -> List[HierarchicalGoal]:
    """Strategic (L3) goals from reflection + narrative arcs."""
    goals: List[HierarchicalGoal] = []
    stability = getattr(reflection, "stability", 0.5)
    alignment = getattr(reflection, "alignment", 0.5)

    if stability < 0.5:
        goals.append(create_goal("maintain_stability", L3, 0.9))
    if alignment < 0.5:
        goals.append(create_goal("build_relationship", L3, 0.7))

    for arc_name, arc in (arcs or {}).items():
        strength = getattr(arc, "strength", 0.0)
        if arc_name == "curiosity_arc" and strength > 0.5:
            goals.append(create_goal("expand_knowledge", L3, 0.6))

    return goals


# ── 2. Arbitration ────────────────────────────────────────────────────────────

def score_goal(goal: HierarchicalGoal, reflection: Any, arcs: Dict[str, Any]) -> float:
    """Urgency + relevance weighting (doc §A: this is critical)."""
    urgency = (1.0 - getattr(reflection, "stability", 0.5)) if goal.goal_type == "maintain_stability" else 0.5

    relevance = 0.0
    if goal.goal_type == "reduce_risk":
        relevance = getattr((arcs or {}).get("conflict_arc"), "strength", 0.0)

    return goal.priority * 0.5 + urgency * 0.3 + relevance * 0.2


def select_active_goals(goals: List[HierarchicalGoal], reflection: Any,
                        arcs: Dict[str, Any], max_active: int = MAX_ACTIVE) -> List[HierarchicalGoal]:
    """Score + cap to `max_active` (default 2)."""
    scored = [(g, score_goal(g, reflection, arcs)) for g in goals]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [g for g, _ in scored[:max_active]]


# ── 3. Hierarchical planning ──────────────────────────────────────────────────

def decompose_goal(goal: HierarchicalGoal) -> List[HierarchicalGoal]:
    """L3 strategic goal → L2 subgoals."""
    subgoals: List[HierarchicalGoal] = []
    if goal.goal_type == "maintain_stability":
        subgoals.append(create_subgoal("reduce_volatility", goal.id))
        subgoals.append(create_subgoal("increase_reasoning", goal.id))
    if goal.goal_type == "build_relationship":
        subgoals.append(create_subgoal("increase_empathy", goal.id))
    if goal.goal_type == "expand_knowledge":
        subgoals.append(create_subgoal("increase_curiosity", goal.id))
    goal.children = subgoals
    return subgoals


def subgoal_to_actions(subgoal: HierarchicalGoal) -> List[str]:
    """L2 subgoal → L1 actions."""
    mapping = {
        "reduce_volatility": ["reduce_volatility"],
        "increase_empathy": ["increase_empathy"],
        "increase_reasoning": ["increase_reasoning"],
        "increase_curiosity": ["increase_curiosity"],
        "decrease_risk": ["decrease_risk"],
    }
    return list(mapping.get(subgoal.goal_type, []))


def build_plan(goals: List[HierarchicalGoal]) -> List[str]:
    """Decompose active goals → L1 action list, bounded by MAX_DEPTH/MAX_ACTIONS."""
    actions: List[str] = []
    for g in goals:
        subgoals = decompose_goal(g)
        for sg in subgoals[:MAX_DEPTH]:
            actions += subgoal_to_actions(sg)
    return actions[:MAX_ACTIONS]


# ── 4. Conflict resolution ────────────────────────────────────────────────────

def resolve_conflicts(actions: List[str]) -> List[str]:
    """Drop actions that conflict with already-accepted ones."""
    final: List[str] = []
    for a in actions:
        if any((a, b) in CONFLICTS or (b, a) in CONFLICTS for b in final):
            continue
        final.append(a)
    return final


# ── 5. Full loop ──────────────────────────────────────────────────────────────

def hierarchical_plan(reflection: Any, arcs: Dict[str, Any]) -> Tuple[List[str], List[HierarchicalGoal]]:
    """
    One full hierarchical planning pass:
    generate → arbitrate → plan → resolve conflicts.
    Returns (actions, active_goals).
    """
    goals = generate_strategic_goals(reflection, arcs)
    active = select_active_goals(goals, reflection, arcs)
    actions = build_plan(active)
    actions = resolve_conflicts(actions)
    return actions, active


class HierarchicalGoalSystem:
    """Stateful wrapper that remembers the active strategic goals across turns."""

    def __init__(self):
        self.active_goals: List[HierarchicalGoal] = []
        self.last_actions: List[str] = []

    def step(self, reflection: Any, arcs: Dict[str, Any]) -> Tuple[List[str], List[HierarchicalGoal]]:
        actions, active = hierarchical_plan(reflection, arcs)
        self.active_goals = active
        self.last_actions = actions
        return actions, active
