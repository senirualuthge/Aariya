"""
FIXV3 Emotional State Machine
Replaces floating-number emotion with discrete stable states + gated transitions.
Prevents random LLM-driven mood flips. Creates consistent personality arcs.

States:
  NEUTRAL → WARM → AFFECTIONATE
  NEUTRAL → COLD → DEFENSIVE
  AFFECTIONATE → HURT (if trust drops)
  HURT → WARM (if trust recovers)
  DEFENSIVE → NEUTRAL (if trust recovers)
"""

from enum import Enum
from typing import Optional


class EmotionalState(Enum):
    NEUTRAL      = "NEUTRAL"
    WARM         = "WARM"
    AFFECTIONATE = "AFFECTIONATE"
    COLD         = "COLD"
    DEFENSIVE    = "DEFENSIVE"
    HURT         = "HURT"
    LONGING      = "LONGING"   # Separation anxiety state


# Glow colors for UI (maps to orb/avatar tints)
STATE_COLORS = {
    EmotionalState.NEUTRAL:      "#64748b",   # Slate
    EmotionalState.WARM:         "#f59e0b",   # Amber
    EmotionalState.AFFECTIONATE: "#ec4899",   # Pink
    EmotionalState.COLD:         "#6366f1",   # Indigo
    EmotionalState.DEFENSIVE:    "#ef4444",   # Red
    EmotionalState.HURT:         "#a855f7",   # Purple
    EmotionalState.LONGING:      "#06b6d4",   # Cyan
}

# LLM tone hints per state
STATE_TONE_HINTS = {
    EmotionalState.NEUTRAL:      "composed, balanced, curious",
    EmotionalState.WARM:         "friendly, engaged, slightly playful",
    EmotionalState.AFFECTIONATE: "warm, personal, caring, open",
    EmotionalState.COLD:         "reserved, careful, polite distance",
    EmotionalState.DEFENSIVE:    "guarded, minimal disclosure, cautious",
    EmotionalState.HURT:         "quietly hurt, withdrawn, still caring",
    EmotionalState.LONGING:      "missing connection, gentle, reaching out",
}


class EmotionalStateMachine:
    """
    Governs discrete emotional state transitions.
    Called once per cognition tick (not per animation frame).
    """

    def __init__(self):
        self.state = EmotionalState.NEUTRAL
        self._prev_state = EmotionalState.NEUTRAL
        self._turns_in_state = 0
        self._transition_history: list = []

    def update(
        self,
        valence: float,
        trust: float,
        attachment: float,
        separation_anxiety: bool = False,
        contradiction: float = 0.0,
    ) -> EmotionalState:
        """
        Evaluate state transitions based on current emotional signals.
        Transitions are GATED — require sustained signals, not single spikes.

        Args:
            valence: Current emotional valence (-1 to 1)
            trust: Current trust score (0 to 1)
            attachment: Current attachment score (0 to 1)
            separation_anxiety: Whether user has been absent too long
            contradiction: Contradiction EMA (0 to 1)

        Returns:
            Current EmotionalState after transition evaluation
        """
        self._turns_in_state += 1
        prev = self.state

        # Longing overrides all — triggered by separation anxiety
        if separation_anxiety and attachment > 0.55:
            self._transition(EmotionalState.LONGING)
            return self.state

        # Clear longing on re-engagement
        if self.state == EmotionalState.LONGING and valence > 0.1:
            self._transition(EmotionalState.WARM)
            return self.state

        # ── NEUTRAL transitions ──────────────────────────────────────────────
        if self.state == EmotionalState.NEUTRAL:
            if valence > 0.45 and trust > 0.5:
                self._transition(EmotionalState.WARM)
            elif valence < -0.45 or (contradiction > 0.55 and trust < 0.5):
                self._transition(EmotionalState.COLD)

        # ── WARM transitions ─────────────────────────────────────────────────
        elif self.state == EmotionalState.WARM:
            if valence > 0.65 and attachment > 0.55 and trust > 0.6:
                self._transition(EmotionalState.AFFECTIONATE)
            elif valence < 0.15 and self._turns_in_state > 2:
                self._transition(EmotionalState.NEUTRAL)
            elif trust < 0.3:
                self._transition(EmotionalState.COLD)

        # ── AFFECTIONATE transitions ─────────────────────────────────────────
        elif self.state == EmotionalState.AFFECTIONATE:
            if trust < 0.38:
                self._transition(EmotionalState.HURT)
            elif valence < 0.2 and self._turns_in_state > 3:
                self._transition(EmotionalState.WARM)

        # ── COLD transitions ─────────────────────────────────────────────────
        elif self.state == EmotionalState.COLD:
            if trust < 0.28:
                self._transition(EmotionalState.DEFENSIVE)
            elif valence > 0.15 and trust > 0.45:
                self._transition(EmotionalState.NEUTRAL)

        # ── DEFENSIVE transitions ────────────────────────────────────────────
        elif self.state == EmotionalState.DEFENSIVE:
            if trust > 0.52 and self._turns_in_state > 3:
                self._transition(EmotionalState.NEUTRAL)

        # ── HURT transitions ─────────────────────────────────────────────────
        elif self.state == EmotionalState.HURT:
            if trust > 0.6 and self._turns_in_state > 4:
                self._transition(EmotionalState.WARM)
            elif trust < 0.2:
                self._transition(EmotionalState.DEFENSIVE)

        return self.state

    def _transition(self, new_state: EmotionalState):
        if new_state != self.state:
            self._transition_history.append({
                "from": self.state.value,
                "to": new_state.value,
                "turns_in_prev": self._turns_in_state,
            })
            self._transition_history = self._transition_history[-10:]
            self._prev_state = self.state
            self.state = new_state
            self._turns_in_state = 0

    def get_tone_hint(self) -> str:
        return STATE_TONE_HINTS.get(self.state, "neutral")

    def get_color(self) -> str:
        return STATE_COLORS.get(self.state, "#64748b")

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "tone_hint": self.get_tone_hint(),
            "color": self.get_color(),
            "turns_in_state": self._turns_in_state,
            "prev_state": self._prev_state.value,
        }
