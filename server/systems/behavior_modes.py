"""
Behavior mode engine (*AI Girl 2* §"mode resolver" + §latent state traits).

Formalizes the CALM / STEALTH / COMBAT resolver the doc specifies — the daemon
already *behaved* like STEALTH informally; now it is an explicit, deterministic
decision with a prompt switch and a speech profile per mode.

Also exposes the latent state traits the doc uses for prosody and tone:

  * focus_level   — how tightly Aariya is attending (higher = more focused)
  * urgency_level — how pressing the moment is (drives speech rate)

Everything is pure (no DB / LLM): the brain feeds measured signals in and gets
a stable, testable mode + directive + speech profile out.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict


class BehaviorMode(Enum):
    CALM = "CALM"
    STEALTH = "STEALTH"
    COMBAT = "COMBAT"


# LLM prompt switch per mode — injected into the strategy so the reply's tone
# follows the resolved mode, not just the mood overlays.
MODE_DIRECTIVES = {
    BehaviorMode.CALM: (
        "Current behavior mode: CALM. Composed, grounded, present. Natural "
        "warmth, no pressure, no urgency — this is the default way of being."
    ),
    BehaviorMode.STEALTH: (
        "Current behavior mode: STEALTH. Quiet presence, minimal initiative, "
        "low self-disclosure. Let the user lead; be gentle, unobtrusive, and "
        "warm without demanding attention."
    ),
    BehaviorMode.COMBAT: (
        "Current behavior mode: COMBAT. The moment demands decisiveness: be "
        "direct, clear, protective, and reassuring. Cut fluff, prioritize "
        "safety and concrete next steps over small talk."
    ),
}

# Speech prosody per mode (feeds TTS pace / pitch / energy).
MODE_SPEECH = {
    BehaviorMode.CALM: {"pace": 1.0, "pitch": 0.0, "energy": 0.5},
    BehaviorMode.STEALTH: {"pace": 0.85, "pitch": -0.05, "energy": 0.3},
    BehaviorMode.COMBAT: {"pace": 1.15, "pitch": 0.05, "energy": 0.85},
}

MODE_COLORS = {
    BehaviorMode.CALM: "#6bcbef",
    BehaviorMode.STEALTH: "#a78bfa",
    BehaviorMode.COMBAT: "#ff6b6b",
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def resolve_mode(
    *,
    valence: float = 0.0,
    arousal: float = 0.0,
    trust: float = 0.5,
    conflict: float = 0.0,
    shock: float = 0.0,
    threat_level: str = "SAFE",
    separation_anxiety: bool = False,
    inactivity_seconds: float = 0.0,
    time_pressure: bool = False,
    error_rate: float = 0.0,
) -> Dict[str, Any]:
    """Resolve the behavior mode from measured signals.

    Implements the doc's mode resolver exactly (*AI Girl 2* §"CODE-LEVEL STATE
    MACHINE"):

      COMBAT:  real threat / extreme conflict+distress, OR time-pressure with
               high urgency or high error rate.
      STEALTH: user inactive > 30 s while urgency stays low (quiet presence), OR
               low trust / separation.
      CALM:    everything else.

    Priority: COMBAT (safety first) → STEALTH → CALM. New params default to
    non-triggering values so existing callers behave exactly as before.
    """
    focus_level = _clamp(1.0 - conflict * 0.55 - abs(valence) * 0.2 + arousal * 0.15)
    urgency_level = _clamp(arousal * 0.45 + conflict * 0.35 + shock * 0.2)

    mode = BehaviorMode.CALM
    reasons = []

    if threat_level == "HIGH":
        mode = BehaviorMode.COMBAT
        reasons.append("threat_level=HIGH")
    elif conflict >= 0.6 and valence <= -0.35:
        mode = BehaviorMode.COMBAT
        reasons.append(f"conflict={conflict:.2f} + distress valence={valence:.2f}")
    elif time_pressure and (urgency_level > 0.7 or error_rate > 0.5):
        # Doc: crisis execution mode — window closing, act now.
        mode = BehaviorMode.COMBAT
        reasons.append(
            f"time_pressure with urgency={urgency_level:.2f}/error_rate={error_rate:.2f}"
        )
    elif inactivity_seconds > 30 and urgency_level < 0.4:
        # Doc: quiet presence — user is away and nothing is pressing.
        mode = BehaviorMode.STEALTH
        reasons.append(f"inactive {inactivity_seconds:.0f}s (urgency {urgency_level:.2f})")
    elif separation_anxiety or trust < 0.35 or (trust < 0.5 and conflict > 0.35):
        mode = BehaviorMode.STEALTH
        reasons.append(
            "separation_anxiety" if separation_anxiety
            else f"trust={trust:.2f}"
        )
    else:
        reasons.append(f"baseline valence={valence:.2f}")

    return {
        "mode": mode.value,
        "focus_level": round(focus_level, 3),
        "urgency_level": round(urgency_level, 3),
        "directive": MODE_DIRECTIVES[mode],
        "speech": MODE_SPEECH[mode],
        "color": MODE_COLORS[mode],
        "reasons": reasons,
        "inactivity_seconds": round(inactivity_seconds, 1),
    }


def mode_prompt_directive(mode: str) -> str:
    try:
        return MODE_DIRECTIVES[BehaviorMode(mode)]
    except (KeyError, ValueError):
        return MODE_DIRECTIVES[BehaviorMode.CALM]


def mode_speech_profile(mode: str) -> Dict[str, float]:
    try:
        return MODE_SPEECH[BehaviorMode(mode)]
    except (KeyError, ValueError):
        return MODE_SPEECH[BehaviorMode.CALM]
