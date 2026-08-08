"""
Turn-Taking State Machine (TTSM) — Fixv2 Implementation.

Controls WHEN the AI speaks, waits, backchannels, or yields.
Runs in Sensor Loop (8–15 Hz) — tick() called with dt_ms each frame.
Outputs signals to the Cognition/Policy layer.

Design goals:
- Responsive (<250 ms reaction)
- Non-interruptive at low trust
- More proactive at high trust
- Human-like pause timing
- Barge-in (overlap) handling

States: LISTENING → PROCESSING → (HOLD) → RESPONDING → YIELDING → LISTENING
                  → BACKCHANNEL_READY → LISTENING
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from server.infrastructure.observability import logger


# ─────────────────────────────────────────────
#  State and related enums
# ─────────────────────────────────────────────

class TTSMState(str, Enum):
    LISTENING          = "LISTENING"
    PROCESSING         = "PROCESSING"
    RESPONDING         = "RESPONDING"
    BACKCHANNEL_READY  = "BACKCHANNEL_READY"
    YIELDING           = "YIELDING"
    HOLD               = "HOLD"


class TurnPhase(str, Enum):
    USER_TURN  = "USER_TURN"
    AI_TURN    = "AI_TURN"
    TRANSITION = "TRANSITION"


HOLD_INTENTS = {"COMFORTING", "TEASING"}


# ─────────────────────────────────────────────
#  Output bundle (emitted every tick)
# ─────────────────────────────────────────────

@dataclass
class TTSMTick:
    """Signals emitted to the Policy Router each sensor tick."""
    vad_state: str           # "SPEAKING" | "SILENCE" | "AI_SPEAKING"
    turn_phase: TurnPhase
    backchannel_allowed: bool
    response_allowed: bool
    stop_tts: bool           # True only on YIELDING → router stops TTS
    state: TTSMState


# ─────────────────────────────────────────────
#  Timing helpers
# ─────────────────────────────────────────────

def _trust_wait_modifier(trust: float) -> float:
    """
    Additional silence before AI starts speaking, based on trust.
        Low trust  → +180 ms (more cautious)
        Mid trust  → +80 ms
        High trust → +0 ms
    """
    if trust < 0.35:
        return 180.0
    if trust < 0.65:
        return 80.0
    return 0.0


def _barge_in_threshold_ms(trust: float) -> float:
    """
    How long AI waits before yielding when user interrupts.
    Low trust → instant yield (50 ms); High trust → 120 ms (slightly assertive).
    Linear interpolation.
    """
    return 50.0 + (120.0 - 50.0) * trust  # lerp(50, 120, trust)


def _backchannel_min_interval_ms(trust: float) -> float:
    """
    Minimum gap between backchannels.
    lerp(6000 ms → 2000 ms, trust)
    """
    return 6000.0 - (6000.0 - 2000.0) * trust


def _hold_duration_ms(arousal: float) -> float:
    """
    Dramatic pause duration scaled by arousal.
    300 ms (low arousal) → 900 ms (high arousal)
    """
    return 300.0 + 600.0 * arousal


# ─────────────────────────────────────────────
#  State Machine
# ─────────────────────────────────────────────

class TurnTakingStateMachine:
    """
    Per-session Turn-Taking State Machine.

    Usage:
        sm = TurnTakingStateMachine()
        tick_out = sm.tick(
            vad_user=True,
            vad_ai=False,
            prosody_energy=0.6,
            turn_length_ms=1350.0,
            silence_ms=0.0,
            trust_level=0.55,
            intent="COMFORTING",
            interruption_flag=False,
            dt_ms=66.7,   # ~15 Hz
        )
    """

    # ── Timing constants (from Fixv2 spec) ──
    BASE_WAIT_MS          = 220.0
    TURN_WAIT_COEFF       = 0.15   # fraction of last turn length added to wait
    BACKCHANNEL_THRESH_MS = 1200.0 # min turn length before backchannel eligible

    def __init__(self):
        self.state: TTSMState = TTSMState.LISTENING

        # Accumulators
        self._turn_length_ms:      float = 0.0
        self._silence_ms:          float = 0.0
        self._hold_ms:             float = 0.0
        self._last_turn_length_ms: float = 0.0  # previous completed user turn

        # Backchannel rate limiter
        self._backchannel_cooldown_ms: float = 0.0

        # Barge-in accumulator (time user has been speaking while AI was speaking)
        self._barge_in_ms: float = 0.0

        # Hold configuration set when entering HOLD
        self._hold_target_ms: float = 0.0

        # For logging
        self._prev_state: TTSMState = TTSMState.LISTENING

    # ─────────────────────────────────────────
    #  Main tick
    # ─────────────────────────────────────────

    def tick(
        self,
        vad_user: bool,
        vad_ai: bool,
        prosody_energy: float,
        turn_length_ms: float,
        silence_ms: float,
        trust_level: float,
        intent: str,
        interruption_flag: bool,
        dt_ms: float,
    ) -> TTSMTick:
        """
        Advance the state machine by dt_ms milliseconds.

        Args:
            vad_user:         True if user microphone is active (speech detected)
            vad_ai:           True if AI TTS is currently playing
            prosody_energy:   User's voice energy [0, 1] (arousal proxy)
            turn_length_ms:   Current / last completed user speech duration
            silence_ms:       Milliseconds since user stopped speaking (resets on speech)
            trust_level:      Current trust score [0, 1]
            intent:           Current social intent string
            interruption_flag: True if user started speaking while AI was speaking
            dt_ms:            Time elapsed since last tick (milliseconds)

        Returns:
            TTSMTick with signals for the cognition/router layer
        """
        self._prev_state = self.state
        stop_tts = False

        # ── Backchannel cooldown countdown ──
        if self._backchannel_cooldown_ms > 0:
            self._backchannel_cooldown_ms = max(0.0, self._backchannel_cooldown_ms - dt_ms)

        # ── State machine ──────────────────────────────────────────────────
        if self.state == TTSMState.LISTENING:
            self._handle_listening(vad_user, prosody_energy, turn_length_ms, trust_level, dt_ms)

        elif self.state == TTSMState.BACKCHANNEL_READY:
            # Micro-state: one tick only
            self._backchannel_cooldown_ms = _backchannel_min_interval_ms(trust_level)
            self._transition(TTSMState.LISTENING)

        elif self.state == TTSMState.PROCESSING:
            self._handle_processing(
                vad_user, silence_ms, trust_level, intent, prosody_energy, dt_ms
            )

        elif self.state == TTSMState.HOLD:
            self._hold_ms += dt_ms
            if self._hold_ms >= self._hold_target_ms:
                self._transition(TTSMState.RESPONDING)

        elif self.state == TTSMState.RESPONDING:
            if interruption_flag:
                # Start barge-in counter
                self._barge_in_ms += dt_ms
                threshold = _barge_in_threshold_ms(trust_level)
                if self._barge_in_ms >= threshold:
                    stop_tts = True
                    self._transition(TTSMState.YIELDING)
            else:
                self._barge_in_ms = 0.0  # reset if flag cleared

        elif self.state == TTSMState.YIELDING:
            # Immediately flush to LISTENING
            self._reset_accumulators()
            self._transition(TTSMState.LISTENING)

        # ── Log state transitions ──────────────────────────────────────────
        if self.state != self._prev_state:
            logger.info(
                "TTSM state transition",
                from_state=self._prev_state.value,
                to_state=self.state.value,
                trust=round(trust_level, 3),
            )

        # ── Build output bundle ────────────────────────────────────────────
        vad_str = (
            "AI_SPEAKING" if vad_ai else
            "SPEAKING"    if vad_user else
            "SILENCE"
        )
        turn_phase = self._compute_turn_phase()
        backchannel_allowed = self.state == TTSMState.BACKCHANNEL_READY
        response_allowed    = (
            self.state == TTSMState.RESPONDING
            and not vad_user
        )

        return TTSMTick(
            vad_state=vad_str,
            turn_phase=turn_phase,
            backchannel_allowed=backchannel_allowed,
            response_allowed=response_allowed,
            stop_tts=stop_tts,
            state=self.state,
        )

    # ─────────────────────────────────────────
    #  State handlers
    # ─────────────────────────────────────────

    def _handle_listening(
        self,
        vad_user: bool,
        prosody_energy: float,
        turn_length_ms: float,
        trust_level: float,
        dt_ms: float,
    ):
        if vad_user:
            self._turn_length_ms += dt_ms
            # Check backchannel eligibility
            if self._is_backchannel_eligible(prosody_energy, trust_level):
                self._transition(TTSMState.BACKCHANNEL_READY)
        else:
            # User stopped → go process
            if self._turn_length_ms > 0:
                self._last_turn_length_ms = self._turn_length_ms
                self._turn_length_ms = 0.0
            self._silence_ms = 0.0
            self._transition(TTSMState.PROCESSING)

    def _handle_processing(
        self,
        vad_user: bool,
        silence_ms: float,
        trust_level: float,
        intent: str,
        arousal: float,
        dt_ms: float,
    ):
        if vad_user:
            # User resumed speaking
            self._transition(TTSMState.LISTENING)
            return

        self._silence_ms += dt_ms
        wait_time = self._compute_wait_time(trust_level)

        if self._silence_ms >= wait_time:
            if self._should_hold(intent, trust_level):
                self._hold_ms = 0.0
                self._hold_target_ms = _hold_duration_ms(arousal)
                self._transition(TTSMState.HOLD)
            else:
                self._transition(TTSMState.RESPONDING)

    # ─────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────

    def _compute_wait_time(self, trust_level: float) -> float:
        """
        Dynamic wait before speaking.
        base_wait = 220 ms + 0.15 * last_turn_length + trust_modifier
        """
        return (
            self.BASE_WAIT_MS
            + self.TURN_WAIT_COEFF * self._last_turn_length_ms
            + _trust_wait_modifier(trust_level)
        )

    def _is_backchannel_eligible(self, prosody_energy: float, trust_level: float) -> bool:
        """Check whether we can emit a backchannel this tick."""
        return (
            self._turn_length_ms > self.BACKCHANNEL_THRESH_MS
            and prosody_energy > 0.45          # user arousal reasonably high
            and trust_level > 0.3
            and self._backchannel_cooldown_ms <= 0.0
        )

    @staticmethod
    def _should_hold(intent: str, trust_level: float) -> bool:
        """HOLD state: dramatic pause for emotional/intimate turns at high trust."""
        return intent in HOLD_INTENTS and trust_level > 0.6

    def _compute_turn_phase(self) -> TurnPhase:
        if self.state in {TTSMState.LISTENING, TTSMState.BACKCHANNEL_READY}:
            return TurnPhase.USER_TURN
        if self.state == TTSMState.RESPONDING:
            return TurnPhase.AI_TURN
        return TurnPhase.TRANSITION

    def _transition(self, new_state: TTSMState):
        self.state = new_state

    def _reset_accumulators(self):
        self._turn_length_ms = 0.0
        self._silence_ms     = 0.0
        self._hold_ms        = 0.0
        self._barge_in_ms    = 0.0

    # ─────────────────────────────────────────
    #  Signal: AI TTS finished (called externally)
    # ─────────────────────────────────────────

    def on_tts_finished(self):
        """Call when TTS playback ends. Transitions back to LISTENING."""
        if self.state == TTSMState.RESPONDING:
            self._transition(TTSMState.LISTENING)
            self._reset_accumulators()


# ─────────────────────────────────────────────
#  Global factory (one TTSM per session)
# ─────────────────────────────────────────────

def create_ttsm() -> TurnTakingStateMachine:
    """Create a new TTSM instance for a session."""
    return TurnTakingStateMachine()
