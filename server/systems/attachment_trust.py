"""
FIXV3 Attachment + Trust System (3D Multi-Dimensional)

Replaces the 1D linear trust with a 3-component model:
  T_emotional   — bond / closeness (how warm the relationship is)
  T_reliability — consistency / honesty (how predictable/safe the user is)
  T_safety      — risk / boundary respect (has user violated boundaries?)

Final Trust Score:
  T = 0.5 * T_emotional + 0.3 * T_reliability + 0.2 * T_safety

Key upgrades over Fixv2:
  - Time decay via exponential function (trust fades if user disappears)
  - Shock events (single violation drops T_safety 0.3–0.6 instantly)
  - Anti-oscillation momentum (harder to move when trust is extreme)
  - Separate attachment score (emotional bond, distinct from trust)
  - Trust episode log for memory callbacks
"""

import math
import time
import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ── Tuning constants ─────────────────────────────────────────────────────────
DECAY_LAMBDA        = 0.05   # e^(-λ * days_inactive)
ATTACHMENT_DECAY    = 0.03   # Attachment decays slightly faster
SHOCK_SAFETY_DROP   = 0.45   # T_safety drop on a single boundary violation
MOMENTUM_CLAMP_HI   = 0.9
MOMENTUM_CLAMP_LO   = 0.05

# Attachment stage thresholds
ATTACHMENT_STAGES = {
    (0.0, 0.2): "stranger",
    (0.2, 0.4): "familiar",
    (0.4, 0.7): "bonded",
    (0.7, 1.0): "attached",
}


@dataclass
class TrustEpisode:
    """A single named trust event stored for emotional memory callbacks."""
    event: str
    impact: float          # Positive or negative
    component: str         # "emotional" | "reliability" | "safety"
    timestamp: float = field(default_factory=time.time)


class AttachmentTrustSystem:
    """
    3D trust model with attachment tracking per user.
    Maintains separate state for each user_id.
    """

    def __init__(self):
        # Per-user state: user_id -> state dict
        self._state: Dict[str, dict] = {}

    def _get_state(self, user_id: str) -> dict:
        if user_id not in self._state:
            self._state[user_id] = {
                "t_emotional": 0.5,
                "t_reliability": 0.5,
                "t_safety": 0.8,    # Start trusting on safety
                "attachment": 0.1,  # Start as strangers
                "momentum": 0.2,
                "last_interaction": time.time(),
                "episodes": [],
            }
        return self._state[user_id]

    # ── Single update step ────────────────────────────────────────────────────
    def update(self, user_id: str, perception: dict, boundary_violation: bool = False) -> dict:
        """
        Run one trust + attachment update tick.

        Args:
            user_id: User identifier
            perception: {valence, arousal, contradiction, vulnerability_shared, return_frequency}
            boundary_violation: Whether user violated a boundary this turn

        Returns:
            {trust, attachment, t_emotional, t_reliability, t_safety, attachment_stage}
        """
        s = self._get_state(user_id)
        now = time.time()

        dt_seconds = now - s["last_interaction"]
        s["last_interaction"] = now

        valence         = float(perception.get("valence", 0.0))
        contradiction   = float(perception.get("contradiction", 0.0))
        vulnerability   = float(perception.get("vulnerability_shared", 0.0))
        session_depth   = float(perception.get("session_depth", 0.3))
        consistency     = float(perception.get("consistency_score", 1.0 - contradiction))
        return_freq     = float(perception.get("return_frequency", 0.5))

        # ── Component deltas ──────────────────────────────────────────────────
        dt_emotional = (
            + 0.4 * valence
            + 0.3 * vulnerability
            + 0.2 * session_depth
            - 0.5 * max(0.0, -valence)   # coldness
        )

        dt_reliability = (
            + 0.5 * consistency
            + 0.3 * return_freq
            - 0.7 * contradiction
        )

        dt_safety = (
            + 0.2 * (1.0 - contradiction)   # respectful behavior proxy
        )
        if boundary_violation:
            dt_safety -= SHOCK_SAFETY_DROP
            self._log_episode(s, "boundary_violation", -SHOCK_SAFETY_DROP, "safety")

        # ── Anti-oscillation momentum ─────────────────────────────────────────
        current_trust = self.get_trust(user_id)
        momentum_scale = 1.0 - abs(current_trust - 0.5)  # Harder to move at extremes

        dt_emotional   *= momentum_scale
        dt_reliability *= momentum_scale
        dt_safety      *= momentum_scale

        # Small step size to prevent per-turn jumps
        step = 0.08
        s["t_emotional"]  = _clamp(s["t_emotional"]  + dt_emotional  * step)
        s["t_reliability"]= _clamp(s["t_reliability"]+ dt_reliability* step)
        s["t_safety"]     = _clamp(s["t_safety"]     + dt_safety     * step)

        # ── Attachment update ─────────────────────────────────────────────────
        interaction_time = min(dt_seconds / 60.0, 1.0)  # Normalise to minutes
        attachment_gain = (
            0.2 * interaction_time
            + 0.3 * abs(valence)
            + 0.1 * vulnerability
        )
        s["attachment"] = _clamp(s["attachment"] + attachment_gain * 0.06)

        # ── Time decay (applies only between sessions) ─────────────────────────
        days_inactive = dt_seconds / 86400.0
        if days_inactive > 0.02:   # Only decay after ~30 minutes
            decay_trust      = math.exp(-DECAY_LAMBDA * days_inactive)
            decay_attachment = math.exp(-(DECAY_LAMBDA + ATTACHMENT_DECAY) * days_inactive)
            s["t_emotional"]  *= decay_trust
            s["t_reliability"]*= decay_trust
            # T_safety decays slowly (safety trust is more durable)
            s["t_safety"]     = _clamp(s["t_safety"] * math.exp(-0.01 * days_inactive))
            s["attachment"]   *= decay_attachment

        # ── Separation anxiety trigger ────────────────────────────────────────
        separation_anxiety = False
        if days_inactive > 2.0 and s["attachment"] > 0.6:
            separation_anxiety = True

        final_trust = self.get_trust(user_id)
        attachment_stage = self.get_attachment_stage(user_id)

        return {
            "trust": round(final_trust, 4),
            "attachment": round(s["attachment"], 4),
            "t_emotional": round(s["t_emotional"], 4),
            "t_reliability": round(s["t_reliability"], 4),
            "t_safety": round(s["t_safety"], 4),
            "attachment_stage": attachment_stage,
            "separation_anxiety": separation_anxiety,
            "episodes": s["episodes"][-5:],   # Last 5 episodes for context
        }

    # ── Queries ───────────────────────────────────────────────────────────────
    def get_trust(self, user_id: str) -> float:
        """Compute final trust from 3 components."""
        s = self._get_state(user_id)
        t = (
            0.5 * s["t_emotional"]
            + 0.3 * s["t_reliability"]
            + 0.2 * s["t_safety"]
        )
        return round(_clamp(t), 4)

    def get_attachment(self, user_id: str) -> float:
        return round(self._get_state(user_id)["attachment"], 4)

    def get_attachment_stage(self, user_id: str) -> str:
        a = self.get_attachment(user_id)
        for (lo, hi), stage in ATTACHMENT_STAGES.items():
            if lo <= a < hi:
                return stage
        return "attached"

    def apply_shock_event(self, user_id: str, event: str, magnitude: float = SHOCK_SAFETY_DROP):
        """Immediately drop T_safety for a named shock event (e.g., abuse)."""
        s = self._get_state(user_id)
        s["t_safety"] = _clamp(s["t_safety"] - magnitude)
        self._log_episode(s, event, -magnitude, "safety")

    def _log_episode(self, state: dict, event: str, impact: float, component: str):
        state["episodes"].append({
            "event": event,
            "impact": impact,
            "component": component,
            "timestamp": time.time(),
        })
        # Keep last 20 episodes
        state["episodes"] = state["episodes"][-20:]

    def get_state_summary(self, user_id: str) -> dict:
        """Return full state dict for dashboard / debugging."""
        s = self._get_state(user_id)
        return {
            "trust": self.get_trust(user_id),
            "attachment": s["attachment"],
            "t_emotional": s["t_emotional"],
            "t_reliability": s["t_reliability"],
            "t_safety": s["t_safety"],
            "attachment_stage": self.get_attachment_stage(user_id),
            "episodes_count": len(s["episodes"]),
        }

    def get_state(self, user_id: str) -> dict:
        """
        Public alias for get_state_summary().
        Returns the same dict with trust, attachment, t_emotional, t_reliability,
        t_safety, attachment_stage, episodes_count.
        Used by brain_v2, main.py, and the proactive engine.
        """
        s = self._get_state(user_id)
        return {
            "trust":             self.get_trust(user_id),
            "attachment":        s["attachment"],
            "t_emotional":       s["t_emotional"],
            "t_reliability":     s["t_reliability"],
            "t_safety":          s["t_safety"],
            "separation_anxiety": False,   # Populated by update() only
            "attachment_stage":  self.get_attachment_stage(user_id),
            "episodes":          s["episodes"][-5:],
        }



# ── Helpers ───────────────────────────────────────────────────────────────────
def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


# ── Global singleton ───────────────────────────────────────────────────────────
_attachment_trust: Optional[AttachmentTrustSystem] = None


def get_attachment_trust() -> AttachmentTrustSystem:
    global _attachment_trust
    if _attachment_trust is None:
        _attachment_trust = AttachmentTrustSystem()
    return _attachment_trust
