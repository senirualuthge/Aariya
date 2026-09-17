"""
meta_cognition.py — self-observation + gradual self-correction.

Doc (Agents Swarm Visualize §184-195):
  * ReflectionState — coherence / stability / alignment / drift metrics.
  * compute_reflection() — derives those metrics from synoptic, arcs, personality.
  * MetaCognitionEngine.decide() — picks small corrective actions with a cooldown
    so the system never oscillates or snaps.

Backward compatible: `reflect(synoptic_state)` (scalar overlay) is retained.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from server.systems.narrative_arcs import BASE_PERSONALITY


@dataclass
class ReflectionState:
    coherence: float
    stability: float
    alignment: float
    drift: float
    last_updated: float = field(default_factory=time.time)


def compute_reflection(synoptic: Dict[str, Any], arcs: Dict[str, Any],
                       personality: Dict[str, float]) -> ReflectionState:
    coherence = float(synoptic.get("coherence", 1.0))
    conflict = float(synoptic.get("conflict", 0.0))
    stability = 1.0 - conflict
    alignment = compute_alignment(arcs, personality)
    drift = compute_drift(personality)
    return ReflectionState(
        coherence=coherence,
        stability=stability,
        alignment=alignment,
        drift=drift,
    )


def compute_alignment(arcs: Dict[str, Any], personality: Dict[str, float]) -> float:
    """How consistent the current personality is with the active narrative arcs."""
    score, total = 0.0, 0.0
    for arc_name, arc in (arcs or {}).items():
        strength = getattr(arc, "strength", 0.0)
        if arc_name == "conflict_arc":
            score += (1 - personality.get("empathy", 0.5)) * strength
            total += strength
        if arc_name == "curiosity_arc":
            score += personality.get("curiosity", 0.5) * strength
            total += strength
    if total == 0:
        return 1.0
    return score / total


def compute_drift(personality: Dict[str, float]) -> float:
    """Mean absolute distance of current personality from the identity anchor."""
    if not personality:
        return 0.0
    keys = set(personality) | set(BASE_PERSONALITY)
    total = sum(abs(personality.get(k, BASE_PERSONALITY.get(k, 0.5))
                    - BASE_PERSONALITY.get(k, personality.get(k, 0.5)))
                for k in keys)
    return total / len(keys)


# ── Corrections ───────────────────────────────────────────────────────────────

def stabilize_system(domains: Dict[str, float]) -> Dict[str, float]:
    n = max(len(domains), 1)
    return {k: v * 0.95 + (1 / n) * 0.05 for k, v in domains.items()}


def reduce_drift(personality: Dict[str, float]) -> Dict[str, float]:
    out = {}
    for k in set(personality) | set(BASE_PERSONALITY):
        base = BASE_PERSONALITY.get(k, 0.5)
        cur = personality.get(k, base)
        out[k] = cur * 0.9 + base * 0.1
    return out


def realign_personality(personality: Dict[str, float], arcs: Dict[str, Any]) -> Dict[str, float]:
    out = dict(personality)
    for arc_name, arc in (arcs or {}).items():
        strength = getattr(arc, "strength", 0.0)
        if arc_name == "curiosity_arc":
            out["curiosity"] = out.get("curiosity", 0.5) + strength * 0.01
        if arc_name == "conflict_arc":
            out["empathy"] = out.get("empathy", 0.5) - strength * 0.01
    for k in out:
        out[k] = max(0.0, min(1.0, out[k]))
    return out


class MetaCognitionEngine:
    def __init__(self, cooldown: float = 2.0):
        self.last_adjustment: float = 0.0
        self.cooldown = cooldown
        # Legacy state
        self.consecutive_conflict_turns = 0
        self.consecutive_chaos_turns = 0
        self.conflict_threshold = 0.5
        self.chaos_threshold = 0.5
        self.current_overlay: Optional[str] = None

    def decide(self, reflection: ReflectionState) -> List[Tuple[str, float]]:
        """Pick small corrective actions, respecting the cooldown window."""
        actions: List[Tuple[str, float]] = []
        if time.time() - self.last_adjustment < self.cooldown:
            return actions

        if reflection.stability < 0.4:
            actions.append(("stabilize_system", 0.05))
        if reflection.drift > 0.3:
            actions.append(("reduce_drift", 0.05))
        if reflection.alignment < 0.5:
            actions.append(("realign_personality", 0.03))

        if actions:
            self.last_adjustment = time.time()
        return actions

    def apply(self, actions: List[Tuple[str, float]],
              domains: Dict[str, float], personality: Dict[str, float],
              arcs: Dict[str, Any]) -> Tuple[Dict[str, float], Dict[str, float]]:
        for action, _strength in actions:
            if action == "stabilize_system":
                domains = stabilize_system(domains)
            elif action == "reduce_drift":
                personality = reduce_drift(personality)
            elif action == "realign_personality":
                personality = realign_personality(personality, arcs)
        return domains, personality

    # ── Legacy API ────────────────────────────────────────────────────────────

    def reflect(self, synoptic_state) -> Optional[str]:
        """Legacy scalar overlay selector (kept for existing callers)."""
        conflict = getattr(synoptic_state, "conflict", 0.0)
        if conflict > self.conflict_threshold:
            self.consecutive_conflict_turns += 1
        else:
            self.consecutive_conflict_turns = max(0, self.consecutive_conflict_turns - 1)

        coherence = getattr(synoptic_state, "coherence", 1.0)
        if coherence < self.chaos_threshold:
            self.consecutive_chaos_turns += 1
        else:
            self.consecutive_chaos_turns = max(0, self.consecutive_chaos_turns - 1)

        if self.consecutive_conflict_turns >= 3:
            self.current_overlay = "meta_regulation_calm"
        elif self.consecutive_chaos_turns >= 3:
            self.current_overlay = "meta_regulation_focus"
        else:
            self.current_overlay = None
        return self.current_overlay
