"""
Autonomy layer configuration — every tunable reads from environment variables
with sensible defaults, following the `AgentConfig` pattern
(server/systems/agent/config.py).

All AARIYA_* vars are optional; values are clamped so a bad env value can
never zero-out a cadence (which would busy-loop the daemon) or collapse the
safety cap. Values are read once at import — changing them requires a restart.

Available knobs (defaults in parentheses):

  Daemon cadences (seconds)
    AARIYA_TICK_SECONDS            (60)   initiative evaluation cadence
    AARIYA_LEARNING_SECONDS        (300)  background research cadence
    AARIYA_GOAL_REVIEW_SECONDS     (600)  goal generation / planning cadence

  LSTM emotion predictor retraining (self-updating model)
    AARIYA_EMOTION_RETRAIN_CHECK_SECONDS  (600)   how often the daemon checks
    AARIYA_EMOTION_RETRAIN_HOURS          (24)    min hours between retrains
    AARIYA_EMOTION_RETRAIN_MIN_NEW_SNAPSHOTS (100) new snapshots needed to retrain
    AARIYA_EMOTION_TRAIN_EPOCHS           (30)    epochs per retrain run
    AARIYA_EMOTION_TRAIN_SEQ_LEN          (8)     LSTM sequence length

  Proactive engine thresholds (seconds)
    AARIYA_SILENCE_TRIGGER_SECONDS      (180)  silence before a check-in
    AARIYA_PROACTIVE_COOLDOWN_SECONDS   (90)   min gap between proactive messages
    AARIYA_INSIGHT_COOLDOWN_SECONDS     (300)  min gap between insight shares
    AARIYA_OPPORTUNITY_COOLDOWN_SECONDS (900)  min gap between plan nudges
    AARIYA_CURIOSITY_COOLDOWN_SECONDS   (1800) min gap between curiosity sparks

  Initiative safety guard
    AARIYA_INITIATIVE_COOLDOWN_SECONDS  (300)  min gap between initiations
    AARIYA_INITIATIVES_PER_HOUR         (3)    hard cap per hour per user
                                               (0 = quiet mode: never initiate)
    AARIYA_ATTACHMENT_BLOCK_THRESHOLD   (0.85) block if AI is too attached
"""

import logging
import os

from pydantic import BaseModel, Field

logger = logging.getLogger("aariya.autonomy.config")


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    """Parse an int env var; fall back to `default` when missing/invalid/too low."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Ignoring non-integer %s=%r (using default %s)", name, raw, default
        )
        return default
    if value < minimum:
        logger.warning(
            "Ignoring %s=%r (below minimum %s; using default %s)",
            name, raw, minimum, default,
        )
        return default
    return value


def _float_env(name: str, default: float, minimum: float = 0.0) -> float:
    """Parse a float env var; fall back to `default` when missing/invalid/too low."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "Ignoring non-numeric %s=%r (using default %s)", name, raw, default
        )
        return default
    if value < minimum:
        logger.warning(
            "Ignoring %s=%r (below minimum %s; using default %s)",
            name, raw, minimum, default,
        )
        return default
    return value


class AutonomyConfig(BaseModel):
    """Environment-variable-driven configuration for the autonomy layer."""

    # ── Daemon cadences (seconds) ───────────────────────────────────────────
    TICK_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_TICK_SECONDS", 60, minimum=5)
    )
    LEARNING_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_LEARNING_SECONDS", 300, minimum=10)
    )
    GOAL_REVIEW_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_GOAL_REVIEW_SECONDS", 600, minimum=30)
    )

    # ── LSTM emotion predictor retraining (self-updating model) ────────────
    # How often the daemon re-checks whether a retrain is due. The decision
    # itself (sidecar meta read + one MAX(id) query) is cheap.
    EMOTION_RETRAIN_CHECK_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_EMOTION_RETRAIN_CHECK_SECONDS", 600, minimum=10)
    )
    # Minimum hours between retrains (0 allowed — retrain as soon as eligible).
    EMOTION_RETRAIN_HOURS: float = Field(
        default_factory=lambda: _float_env("AARIYA_EMOTION_RETRAIN_HOURS", 24.0)
    )
    # New snapshots since the last training required before retraining.
    EMOTION_RETRAIN_MIN_NEW_SNAPSHOTS: int = Field(
        default_factory=lambda: _int_env("AARIYA_EMOTION_RETRAIN_MIN_NEW_SNAPSHOTS", 100, minimum=1)
    )
    EMOTION_TRAIN_EPOCHS: int = Field(
        default_factory=lambda: _int_env("AARIYA_EMOTION_TRAIN_EPOCHS", 30, minimum=1)
    )
    EMOTION_TRAIN_SEQ_LEN: int = Field(
        default_factory=lambda: _int_env("AARIYA_EMOTION_TRAIN_SEQ_LEN", 8, minimum=2)
    )

    # ── Proactive engine thresholds (seconds) ──────────────────────────────
    SILENCE_TRIGGER_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_SILENCE_TRIGGER_SECONDS", 180, minimum=5)
    )
    PROACTIVE_COOLDOWN_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_PROACTIVE_COOLDOWN_SECONDS", 90, minimum=1)
    )
    INSIGHT_COOLDOWN_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_INSIGHT_COOLDOWN_SECONDS", 300, minimum=5)
    )
    OPPORTUNITY_COOLDOWN_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_OPPORTUNITY_COOLDOWN_SECONDS", 900, minimum=10)
    )
    CURIOSITY_COOLDOWN_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_CURIOSITY_COOLDOWN_SECONDS", 1800, minimum=30)
    )

    # ── Idle stream-of-consciousness (visible inner life) ────────────────────
    # Minimum silence before she begins to muse, and minimum gap between
    # stream-of-consciousness broadcasts while idle.
    STREAM_MIN_IDLE_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_STREAM_MIN_IDLE_SECONDS", 300, minimum=10)
    )
    STREAM_INTERVAL_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_STREAM_INTERVAL_SECONDS", 1500, minimum=30)
    )

    # ── Initiative safety guard ─────────────────────────────────────────────
    INITIATIVE_COOLDOWN_SECONDS: int = Field(
        default_factory=lambda: _int_env("AARIYA_INITIATIVE_COOLDOWN_SECONDS", 300, minimum=5)
    )
    # 0 = quiet mode (guard blocks every initiation), 1+ = hard cap per hour
    INITIATIVES_PER_HOUR: int = Field(
        default_factory=lambda: _int_env("AARIYA_INITIATIVES_PER_HOUR", 3, minimum=0)
    )
    ATTACHMENT_BLOCK_THRESHOLD: float = Field(
        default_factory=lambda: _float_env("AARIYA_ATTACHMENT_BLOCK_THRESHOLD", 0.85)
    )


# Global configuration instance (values frozen at import time)
config = AutonomyConfig()
