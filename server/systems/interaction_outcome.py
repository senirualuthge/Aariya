"""
Interaction Outcome Model (IOM) — Fixv2 Implementation.

OBSERVER ONLY — measures interaction quality, logs reward scores.
Must NOT modify live behavior or trust directly.
Learning happens OFFLINE from this log data.

Metrics computed:
- Per-turn reward: valence shift, engagement, trust delta, latency, interrupts, memory
- Session reward: length, valence trend, trust gain

Logged to: interaction_outcomes (per-turn), session reward columns
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import List, Optional

from server.infrastructure.observability import logger
from server.infrastructure.postgres_manager import get_postgres


# ─────────────────────────────────────────────
#  Input bundles
# ─────────────────────────────────────────────

@dataclass
class TurnOutcomeInput:
    """All data required to compute a single turn reward."""
    turn_id: str
    session_id: str
    user_id: str

    user_valence_before: float     # [-1, 1]
    user_valence_after: float      # [-1, 1]
    turn_duration_ms: float        # how long the user spoke
    user_interrupt_flag: bool      # user interrupted AI
    ai_interrupt_flag: bool        # AI interrupted user (spoke while user was)
    response_latency_ms: float     # time from user-stop to AI first token
    backchannel_used: bool
    memory_recall_used: bool
    trust_before: float            # [0, 1]
    trust_after: float             # [0, 1]
    user_silence_after_ms: float   # silence duration after AI response (engagement proxy)
    session_active_flag: bool = True

    # For memory recall effect (set from NEXT turn's valence)
    next_turn_valence: Optional[float] = None


@dataclass
class TurnReward:
    turn_id: str
    reward: float          # clamped [-1, 1]
    delta_valence: float
    engagement: float
    trust_score: float
    latency_score: float
    interrupt_penalty: float
    ai_interrupt_penalty: float
    memory_effect: float


@dataclass
class SessionOutcomeInput:
    session_id: str
    user_id: str
    turn_rewards: List[float]
    session_duration_sec: float
    trust_start: float
    trust_end: float
    valence_series: List[float]   # one per turn


@dataclass
class SessionReward:
    session_id: str
    reward: float
    session_score: float
    valence_trend: float      # linear regression slope
    trust_gain: float
    avg_latency_ms: float
    interrupt_rate: float


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _latency_score(latency_ms: float) -> float:
    """
    From Fixv2 spec:
    < 250 ms → +0.2
    250–600 ms → +0.1
    600–900 ms →  0.0
    > 900 ms   → -0.2
    """
    if latency_ms < 250:
        return 0.2
    if latency_ms < 600:
        return 0.1
    if latency_ms < 900:
        return 0.0
    return -0.2


def _linear_trend(values: List[float]) -> float:
    """
    Return slope of a simple linear regression over the value series.
    Positive slope = valence improving over session.
    """
    n = len(values)
    if n < 2:
        return 0.0

    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n

    numer = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
    denom = sum((x - mean_x) ** 2 for x in xs)

    if denom == 0:
        return 0.0
    return round(numer / denom, 5)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ─────────────────────────────────────────────
#  IOM class
# ─────────────────────────────────────────────

class InteractionOutcomeModel:
    """
    Observer-only interaction quality tracker.

    Key constraint: this model MUST NOT modify trust, router behaviour,
    or any live system state.  It observes and logs only.
    """

    def __init__(self):
        self.db = get_postgres()

    # ─────────────────────────────────────────
    #  Turn reward
    # ─────────────────────────────────────────

    def compute_turn_reward(self, O: TurnOutcomeInput) -> TurnReward:
        """
        Compute per-turn reward from Fixv2 spec:

        reward = 0.30*ΔV + 0.20*engagement + 0.20*trust_score
               + latency_score + interrupt_penalty + ai_interrupt_penalty
               + memory_effect

        Clamped to [-1, 1].
        """
        # ── Component metrics ─────────────────────────────────────────────
        dv          = O.user_valence_after - O.user_valence_before   # [-2, 2]
        dv_norm     = _clamp(dv / 2.0, -1.0, 1.0)                   # normalise to [-1,1]

        engagement  = _clamp(O.turn_duration_ms / 4000.0, 0.0, 1.0)

        trust_score = _clamp((O.trust_after - O.trust_before) * 2.0, -1.0, 1.0)

        lat_score   = _latency_score(O.response_latency_ms)

        int_pen     = -0.4 if O.user_interrupt_flag else 0.0
        ai_int_pen  = -0.6 if O.ai_interrupt_flag   else 0.0

        # Memory recall effect (requires next-turn valence)
        mem_effect = 0.0
        if O.memory_recall_used and O.next_turn_valence is not None:
            # Compare next-turn to current valence as a delta proxy
            next_dv = O.next_turn_valence - O.user_valence_after
            if next_dv > 0.05:
                mem_effect = +0.15
            elif next_dv < -0.05:
                mem_effect = -0.25

        # ── Composite ─────────────────────────────────────────────────────
        raw = (
            0.30 * dv_norm
            + 0.20 * engagement
            + 0.20 * trust_score
            + lat_score
            + int_pen
            + ai_int_pen
            + mem_effect
        )
        reward = _clamp(raw, -1.0, 1.0)

        result = TurnReward(
            turn_id=O.turn_id,
            reward=round(reward, 4),
            delta_valence=round(dv_norm, 4),
            engagement=round(engagement, 4),
            trust_score=round(trust_score, 4),
            latency_score=lat_score,
            interrupt_penalty=int_pen,
            ai_interrupt_penalty=ai_int_pen,
            memory_effect=mem_effect,
        )

        # Log to DB (non-blocking best-effort)
        self._log_turn_reward(O, result)

        logger.info(
            "IOM turn reward computed",
            turn_id=O.turn_id,
            reward=result.reward,
            dv=result.delta_valence,
            engagement=result.engagement,
        )

        return result

    # ─────────────────────────────────────────
    #  Session reward
    # ─────────────────────────────────────────

    def compute_session_reward(
        self,
        S: SessionOutcomeInput,
        turn_latencies_ms: Optional[List[float]] = None,
        interrupt_count: int = 0,
        total_turns: int = 0,
    ) -> SessionReward:
        """
        Compute end-of-session reward from Fixv2 spec:

        reward = 0.4*avg(turn_rewards) + 0.3*session_score + 0.3*trust_gain
        """
        avg_turn = sum(S.turn_rewards) / len(S.turn_rewards) if S.turn_rewards else 0.0

        # Session length score: clamp(total_minutes / 10, 0, 1)
        total_minutes  = S.session_duration_sec / 60.0
        session_score  = _clamp(total_minutes / 10.0, 0.0, 1.0)

        trust_gain     = _clamp(S.trust_end - S.trust_start, -1.0, 1.0)

        valence_trend  = _linear_trend(S.valence_series)

        raw = (
            0.4 * avg_turn
            + 0.3 * session_score
            + 0.3 * trust_gain
        )
        reward = _clamp(raw, -1.0, 1.0)

        avg_latency   = (sum(turn_latencies_ms) / len(turn_latencies_ms)
                         if turn_latencies_ms else 0.0)
        interrupt_rate = (interrupt_count / total_turns) if total_turns > 0 else 0.0

        result = SessionReward(
            session_id=S.session_id,
            reward=round(reward, 4),
            session_score=round(session_score, 4),
            valence_trend=valence_trend,
            trust_gain=round(trust_gain, 4),
            avg_latency_ms=round(avg_latency, 1),
            interrupt_rate=round(interrupt_rate, 4),
        )

        self._log_session_reward(result)

        logger.info(
            "IOM session reward computed",
            session_id=S.session_id,
            reward=result.reward,
            valence_trend=valence_trend,
            trust_gain=trust_gain,
        )

        return result

    # ─────────────────────────────────────────
    #  DB logging (best-effort, never raises)
    # ─────────────────────────────────────────

    def _log_turn_reward(self, O: TurnOutcomeInput, R: TurnReward):
        try:
            self.db.execute_update(
                """
                INSERT INTO interaction_outcomes (
                    turn_id, session_id, user_id,
                    reward_turn, delta_valence, engagement,
                    latency_ms, user_interrupt, ai_interrupt,
                    memory_used, trust_delta
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    O.turn_id, O.session_id, O.user_id,
                    R.reward, R.delta_valence, R.engagement,
                    O.response_latency_ms,
                    1 if O.user_interrupt_flag else 0,
                    1 if O.ai_interrupt_flag   else 0,
                    1 if O.memory_recall_used  else 0,
                    R.trust_score,
                )
            )
        except Exception as e:
            logger.error("IOM turn log failed", error=str(e))

    def _log_session_reward(self, R: SessionReward):
        try:
            self.db.execute_update(
                """
                UPDATE sessions
                SET reward_session  = ?,
                    valence_trend   = ?,
                    avg_latency_ms  = ?,
                    interrupt_rate  = ?
                WHERE session_id = ?
                """,
                (R.reward, R.valence_trend, R.avg_latency_ms, R.interrupt_rate, R.session_id)
            )
        except Exception as e:
            logger.error("IOM session log failed", error=str(e))


# ─────────────────────────────────────────────
#  Session accumulator (held in WebSocket scope)
# ─────────────────────────────────────────────

class SessionIOMAccumulator:
    """
    Lightweight per-session state for the IOM.
    Holds running lists for session-end aggregation.
    Zero overhead if not used.
    """

    def __init__(self, session_id: str, user_id: str, trust_start: float):
        self.session_id    = session_id
        self.user_id       = user_id
        self.trust_start   = trust_start
        self.turn_rewards:   List[float] = []
        self.valence_series: List[float] = []
        self.latencies_ms:   List[float] = []
        self.interrupt_count = 0
        self.total_turns     = 0
        self._last_valence:  Optional[float] = None
        self._pending_reward: Optional[TurnReward] = None
        self._pending_input:  Optional[TurnOutcomeInput] = None

    def record_turn(
        self,
        iom: InteractionOutcomeModel,
        turn_input: TurnOutcomeInput,
    ) -> TurnReward:
        """
        Finalise previous pending turn (with next-turn valence now known),
        then store this turn as pending.
        """
        # Resolve previous turn's memory effect with current valence
        if self._pending_input is not None:
            self._pending_input.next_turn_valence = turn_input.user_valence_before
            prev_reward = iom.compute_turn_reward(self._pending_input)
            self.turn_rewards.append(prev_reward.reward)
            if turn_input.user_interrupt_flag:
                self.interrupt_count += 1

        # Store this turn as pending
        self._pending_input = turn_input
        self.valence_series.append(turn_input.user_valence_after)
        self.latencies_ms.append(turn_input.response_latency_ms)
        self.total_turns += 1

        # Return a provisional reward for display (without next-turn info)
        provisional = iom.compute_turn_reward(turn_input)
        self._pending_reward = provisional
        return provisional

    def finalize(
        self,
        iom: InteractionOutcomeModel,
        trust_end: float,
        session_duration_sec: float,
    ) -> SessionReward:
        """Call on session end."""
        # Flush pending turn with no next valence
        if self._pending_input is not None:
            final_reward = iom.compute_turn_reward(self._pending_input)
            self.turn_rewards.append(final_reward.reward)

        session_input = SessionOutcomeInput(
            session_id=self.session_id,
            user_id=self.user_id,
            turn_rewards=self.turn_rewards,
            session_duration_sec=session_duration_sec,
            trust_start=self.trust_start,
            trust_end=trust_end,
            valence_series=self.valence_series,
        )
        return iom.compute_session_reward(
            session_input,
            turn_latencies_ms=self.latencies_ms,
            interrupt_count=self.interrupt_count,
            total_turns=self.total_turns,
        )


# ─────────────────────────────────────────────
#  Global singleton
# ─────────────────────────────────────────────

_iom: Optional[InteractionOutcomeModel] = None


def get_iom() -> InteractionOutcomeModel:
    global _iom
    if _iom is None:
        _iom = InteractionOutcomeModel()
    return _iom
