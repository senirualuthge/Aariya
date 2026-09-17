"""
narrative_arcs.py — long-term narrative patterns + personality drift.

Doc (Agents Swarm Visualize §175-178):
  * NarrativeArcEngine maps events → arc types ("conflict_arc", ...), tracks
    strength (0-1) and trend, and decays arcs so past bias doesn't persist
    forever.
  * Personality drift: arcs slowly push personality traits via DRIFT_MATRIX,
    with a BASE_PERSONALITY anchor that stabilizes identity.

Backward compatible: the older NarrativeArcSystem (theme-based) is retained for
existing callers.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ── Personality drift (doc §178) ──────────────────────────────────────────────

BASE_PERSONALITY: Dict[str, float] = {
    "empathy": 0.6,
    "logic": 0.7,
    "caution": 0.5,
    "curiosity": 0.6,
    "openness": 0.6,
    "warmth": 0.6,
}

DRIFT_MATRIX: Dict[str, Dict[str, float]] = {
    "conflict_arc": {"caution": +0.2, "empathy": -0.1},
    "emotional_arc": {"empathy": +0.2},
    "curiosity_arc": {"curiosity": +0.3, "logic": +0.1},
    "trust_arc": {"warmth": +0.2, "openness": +0.1},
}


def apply_personality_drift(personality: Dict[str, float],
                            arcs: Dict[str, "NarrativeArc"]) -> Dict[str, float]:
    """Very small bounded drift from arc strength → traits."""
    new_personality = dict(personality)
    for arc_name, arc in arcs.items():
        influence = DRIFT_MATRIX.get(arc_name, {})
        strength = getattr(arc, "strength", 0.0)
        for trait, weight in influence.items():
            drift = strength * weight * 0.01  # VERY SMALL (doc)
            new_personality[trait] = new_personality.get(trait, 0.5) + drift
    for k in new_personality:
        new_personality[k] = max(0.0, min(1.0, new_personality[k]))
    return new_personality


def stabilize_personality(current: Dict[str, float],
                          base: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Pull current traits back toward the identity anchor (prevents drift)."""
    base = base or BASE_PERSONALITY
    stabilized = {}
    for k in base:
        stabilized[k] = current.get(k, base[k]) * 0.9 + base[k] * 0.1
    for k in current:
        if k not in stabilized:
            stabilized[k] = current[k]
    return stabilized


# ── Arc model ─────────────────────────────────────────────────────────────────

@dataclass
class NarrativeArc:
    id: str
    arc_type: str              # "conflict_arc", "trust_arc", "curiosity_arc", ...
    strength: float = 0.1      # 0–1
    trend: float = 0.0         # -1..+1
    last_updated: float = field(default_factory=time.time)
    event_count: int = 0

    @property
    def intensity(self) -> float:
        return self.strength


def map_event_to_arc(event) -> str:
    etype = getattr(event, "event_type", "neutral")
    if etype == "conflict":
        return "conflict_arc"
    if etype == "emotional":
        return "emotional_arc"
    if etype == "question":
        return "curiosity_arc"
    if etype == "memory":
        return "memory_arc"
    if getattr(event, "trust_delta", 0.0) > 0.15:
        return "trust_arc"
    return "neutral_arc"


class NarrativeArcEngine:
    """Event-driven arc tracking with strength/trend + decay (doc §175-177)."""

    def __init__(self, decay_rate: float = 0.05):
        self.arcs: Dict[str, NarrativeArc] = {}
        self.decay_rate = decay_rate

    def update(self, event) -> None:
        arc_type = map_event_to_arc(event)
        arc = self.arcs.get(arc_type)
        if not arc:
            arc = NarrativeArc(id=arc_type, arc_type=arc_type)
            self.arcs[arc_type] = arc

        intensity = getattr(event, "intensity", 0.0)
        arc.strength = min(1.0, arc.strength + intensity * 0.1)
        arc.trend = (arc.trend * 0.8) + (intensity * 0.2)
        arc.event_count += 1
        arc.last_updated = time.time()

    def decay_arcs(self) -> None:
        """Exponential-ish decay so stale arcs fade to zero (prevents bias)."""
        now = time.time()
        for arc in self.arcs.values():
            dt = now - arc.last_updated
            arc.strength *= max(0.0, 1 - self.decay_rate * dt)
            if arc.strength < 0.05:
                arc.strength = 0.0

    def get_dominant(self) -> Optional[NarrativeArc]:
        active = [a for a in self.arcs.values() if a.strength > 0]
        return max(active, key=lambda a: a.strength) if active else None

    def snapshot(self) -> Dict[str, Dict[str, float]]:
        return {
            name: {
                "strength": round(arc.strength, 3),
                "trend": round(arc.trend, 3),
                "event_count": arc.event_count,
            }
            for name, arc in self.arcs.items()
        }


# ── Legacy theme-based engine (retained for existing callers) ─────────────────

class _LegacyArc:
    """Duck-typed legacy arc: theme/status/intensity, plus new strength/trend."""
    def __init__(self, theme: str, intensity: float, status: str = "open"):
        self.theme = theme
        self.status = status
        self.intensity = intensity
        self.strength = intensity
        self.trend = 0.0
        self.arc_type = status
        self.event_count = 0

    def __repr__(self):
        return f"_LegacyArc(theme={self.theme!r}, intensity={self.intensity:.2f}, status={self.status!r})"


class NarrativeArcSystem:
    def __init__(self):
        self.active_arcs: Dict[str, _LegacyArc] = {}

    def evaluate_arcs(self, shock: float, latest_event_topic: str) -> None:
        for arc in self.active_arcs.values():
            if arc.status == "open":
                arc.intensity = max(0.0, arc.intensity - 0.05)
                arc.strength = arc.intensity
                if arc.intensity < 0.1:
                    arc.status = "fading"

        if shock > 0.6:
            topic_lower = (latest_event_topic or "").lower()
            if "trust" in topic_lower or "betrayal" in topic_lower or "lie" in topic_lower:
                theme = "Trust Calibration"
            elif "sadness" in topic_lower or "distress" in topic_lower or "cry" in topic_lower:
                theme = "Supporting Distress"
            elif "anger" in topic_lower or "mad" in topic_lower:
                theme = "Conflict De-escalation"
            else:
                theme = "Intense Volatility"

            existing = next(
                (a for a in self.active_arcs.values()
                 if a.status == "open" and a.theme == theme),
                None,
            )
            if existing:
                existing.intensity = min(1.0, existing.intensity + 0.3)
                existing.strength = existing.intensity
            else:
                self.active_arcs[f"arc_{theme}_{int(time.time())}"] = _LegacyArc(theme, shock)

    def get_dominant_arc(self) -> Optional[_LegacyArc]:
        open_arcs = [a for a in self.active_arcs.values() if a.status == "open"]
        return max(open_arcs, key=lambda a: a.intensity) if open_arcs else None
