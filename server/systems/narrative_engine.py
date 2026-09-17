"""
narrative_engine.py — event tracking + shock wave system.

Doc (Agents Swarm Visualize §173): each event generates a decaying shock wave
    shock(t) = intensity * e^(-decay * t)
across the domains it impacts. `compute_shock()` returns a per-domain dict of
current shock effects, so the synoptic pipeline can fold narrative pressure
into the cognitive domains (temporal persistence).

Backward compatible: `compute_shock_scalar()` keeps the old coarse scalar used
by the goal arbitrator.
"""

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List

EVENT_TYPES = {"neutral", "emotional", "question", "conflict", "memory"}


@dataclass
class NarrativeEvent:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = "general"
    user_sentiment: float = 0.0
    trust_delta: float = 0.0
    intensity: float = 0.0          # 0–1
    valence: float = 0.0            # -1..+1
    event_type: str = "neutral"
    domain_impact: Dict[str, float] = field(default_factory=dict)
    memory_refs: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


def create_event(text: str, emotion_valence: float,
                 contradiction_level: float = 0.0) -> NarrativeEvent:
    """Build a narrative event from a perception turn (doc §B)."""
    intensity = min(1.0, abs(emotion_valence) + contradiction_level)

    event_type = "neutral"
    if contradiction_level > 0.6:
        event_type = "conflict"
    elif abs(emotion_valence) > 0.5:
        event_type = "emotional"
    elif "?" in (text or ""):
        event_type = "question"

    domain_impact = {
        "emotion": abs(emotion_valence),
        "reasoning": 0.5 if event_type == "question" else 0.2,
        "risk": contradiction_level,
        "memory": 0.3,
    }

    return NarrativeEvent(
        topic=text or "general",
        user_sentiment=emotion_valence,
        valence=emotion_valence,
        intensity=intensity,
        event_type=event_type,
        domain_impact=domain_impact,
    )


class NarrativeEngine:
    def __init__(self, decay: float = 1.5, max_events: int = 200):
        self.decay = decay
        self.events: List[NarrativeEvent] = []
        self.max_events = max_events
        self.current_shock: float = 0.0  # legacy scalar, kept for arbitration
        self.baseline_sentiment: float = 0.0
        self.shock_threshold: float = 0.5

    def add_event(self, event: NarrativeEvent) -> None:
        self.events.append(event)
        if len(self.events) > self.max_events:
            self.events.pop(0)

        # Moving baseline of recent sentiment — for scalar shock shifts.
        recent = self.events[-5:]
        self.baseline_sentiment = sum(e.user_sentiment for e in recent) / len(recent)

    def compute_shock(self) -> Dict[str, float]:
        """
        Per-domain decaying shock effects from all recent events.
        shock(t) = intensity * e^(-decay * dt), summed per domain.
        """
        now = time.time()
        domain_effects: Dict[str, float] = {}
        for event in self.events:
            dt = now - event.timestamp
            if dt < 0:
                dt = 0.0
            shock = event.intensity * math.exp(-self.decay * dt)
            for domain, weight in event.domain_impact.items():
                domain_effects[domain] = domain_effects.get(domain, 0.0) + shock * weight
        return domain_effects

    def compute_shock_scalar(self) -> float:
        """Legacy coarse scalar — sudden sentiment shifts / high intensity."""
        if not self.events:
            return 0.0
        latest = self.events[-1]
        shift = abs(latest.user_sentiment - self.baseline_sentiment)
        if shift > self.shock_threshold or latest.intensity > self.shock_threshold:
            self.current_shock = min(1.0, self.current_shock + shift + latest.intensity)
        else:
            self.current_shock = max(0.0, self.current_shock - 0.1)
        return self.current_shock
