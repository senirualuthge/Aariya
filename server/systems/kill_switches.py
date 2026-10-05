"""
Kill Switches & Feature Flags System
Implements SOC-2 / EU AI Act §14 (Human Oversight) controls.

Central control for:
- Microphone capture (system-wide privacy switch)
- Camera capture (system-wide privacy switch)
- TTS enable/disable
- Emotion cap on/off
- Memory write on/off
- Voice pipeline enable/disable
- Emotion tracking enable/disable
- Personality drift enable/disable
- Trust gating on/off

All flags are hot-reloadable via Redis and override file-based defaults.
Audit-logged on every toggle for deterministic replay.
"""

import json
import time
import os
from typing import Dict, Optional, Any, Callable, List
from dataclasses import dataclass, field, asdict
from enum import Enum

try:
    from server.infrastructure.redis_manager import get_redis
    _redis = get_redis()
except Exception:
    _redis = None

try:
    from server.infrastructure.observability import logger
except Exception:
    import logging
    logger = logging.getLogger("aariya.kill_switches")


class FeatureFlag(Enum):
    """All controllable feature flags."""
    TTS_ENABLED = "tts_enabled"
    EMOTION_CAP = "emotion_cap"
    MEMORY_WRITE = "memory_write"
    VOICE_PIPELINE = "voice_pipeline"
    EMOTION_TRACKING = "emotion_tracking"
    PERSONALITY_DRIFT = "personality_drift"
    TRUST_GATING = "trust_gating"
    BARGE_IN = "barge_in"
    MICRO_EXPRESSIONS = "micro_expressions"
    MULTI_LANGUAGE = "multi_language"
    AUDIT_LOGGING = "audit_logging"
    AUTONOMY = "autonomy"
    VISION = "vision"
    WEB_RESEARCH = "web_research"
    FILE_ACCESS = "file_access"
    # System-wide privacy switches (ToDo §5). These are deliberately separate
    # from VOICE_PIPELINE/VISION: those gate whole subsystems, these gate the
    # capture devices themselves, so a user can keep the UI up with the lens
    # and microphone physically closed.
    MICROPHONE = "microphone"
    CAMERA = "camera"


# Default state for all flags
DEFAULT_FLAGS: Dict[str, bool] = {
    FeatureFlag.TTS_ENABLED.value: True,
    FeatureFlag.EMOTION_CAP.value: True,
    FeatureFlag.MEMORY_WRITE.value: True,
    FeatureFlag.VOICE_PIPELINE.value: True,
    FeatureFlag.EMOTION_TRACKING.value: True,
    FeatureFlag.PERSONALITY_DRIFT.value: True,
    FeatureFlag.TRUST_GATING.value: True,
    FeatureFlag.BARGE_IN.value: True,
    FeatureFlag.MICRO_EXPRESSIONS.value: True,
    FeatureFlag.MULTI_LANGUAGE.value: True,
    FeatureFlag.AUDIT_LOGGING.value: True,
    FeatureFlag.AUTONOMY.value: True,
    FeatureFlag.VISION.value: True,
    FeatureFlag.WEB_RESEARCH.value: True,
    FeatureFlag.FILE_ACCESS.value: True,
    FeatureFlag.MICROPHONE.value: True,
    FeatureFlag.CAMERA.value: True,
}

# Emotion intensity cap (0.0 - 1.0) — when EMOTION_CAP is active
DEFAULT_EMOTION_CAP: float = 0.8

REDIS_PREFIX = "killswitch:"
REDIS_FLAGS_KEY = f"{REDIS_PREFIX}flags"
REDIS_EMOTION_CAP_KEY = f"{REDIS_PREFIX}emotion_cap"
REDIS_AUDIT_LOG_KEY = f"{REDIS_PREFIX}audit_log"


@dataclass
class FlagToggleEvent:
    """Audit record for a flag toggle."""
    flag: str
    old_value: bool
    new_value: bool
    reason: str
    timestamp: float = field(default_factory=time.time)
    source: str = "system"  # "system" | "api" | "governance" | "emergency"


class KillSwitchSystem:
    """
    Central kill switch and feature flag manager.

    Usage:
        ks = get_kill_switches()
        if ks.is_enabled(FeatureFlag.TTS_ENABLED):
            # play TTS
            pass

        ks.set_flag(FeatureFlag.TTS_ENABLED, False, reason="user preference")
    """

    def __init__(self):
        self._flags: Dict[str, bool] = dict(DEFAULT_FLAGS)
        self._emotion_cap: float = DEFAULT_EMOTION_CAP
        self._audit_log: List[FlagToggleEvent] = []
        self._listeners: Dict[str, List[Callable]] = {}
        self._load_from_redis()

    def _load_from_redis(self):
        """Load flag overrides from Redis (hot-reloadable)."""
        if _redis is None:
            return
        try:
            raw_flags = _redis.get(REDIS_FLAGS_KEY)
            if raw_flags:
                stored = json.loads(raw_flags) if isinstance(raw_flags, str) else raw_flags
                if isinstance(stored, dict):
                    self._flags.update(stored)

            raw_cap = _redis.get(REDIS_EMOTION_CAP_KEY)
            if raw_cap is not None:
                self._emotion_cap = float(raw_cap)
        except Exception as e:
            logger.debug(f"[KillSwitches] Redis load skipped: {e}")

    def _save_to_redis(self):
        """Persist current flags to Redis for hot-reload."""
        if _redis is None:
            return
        try:
            _redis.set(REDIS_FLAGS_KEY, json.dumps(self._flags))
            _redis.set(REDIS_EMOTION_CAP_KEY, str(self._emotion_cap))
        except Exception as e:
            logger.debug(f"[KillSwitches] Redis save skipped: {e}")

    def is_enabled(self, flag: FeatureFlag) -> bool:
        """Check if a feature flag is enabled."""
        return self._flags.get(flag.value, True)

    def is_enabled_str(self, flag_name: str) -> bool:
        """Check if a feature flag is enabled by string name."""
        return self._flags.get(flag_name, True)

    def set_flag(
        self,
        flag: FeatureFlag,
        enabled: bool,
        reason: str = "manual toggle",
        source: str = "system",
    ) -> FlagToggleEvent:
        """
        Toggle a feature flag. Audit-logged and broadcast to listeners.

        Returns the toggle event for audit trail.
        """
        flag_name = flag.value
        old_value = self._flags.get(flag_name, True)
        self._flags[flag_name] = enabled

        event = FlagToggleEvent(
            flag=flag_name,
            old_value=old_value,
            new_value=enabled,
            reason=reason,
            source=source,
        )
        self._audit_log.append(event)

        # Persist to Redis
        self._save_to_redis()

        # Notify listeners
        self._notify_listeners(flag_name, old_value, enabled)

        logger.info(
            f"[KillSwitches] {flag_name}: {old_value} → {enabled} "
            f"(reason={reason}, source={source})"
        )
        return event

    def get_emotion_cap(self) -> float:
        """Get the current emotion intensity cap."""
        if not self.is_enabled(FeatureFlag.EMOTION_CAP):
            return 1.0  # No cap when emotion cap is disabled
        return self._emotion_cap

    def set_emotion_cap(self, cap: float, reason: str = "manual adjustment"):
        """Set the emotion intensity cap (0.0 - 1.0)."""
        old = self._emotion_cap
        self._emotion_cap = max(0.0, min(1.0, cap))
        self._save_to_redis()
        logger.info(f"[KillSwitches] Emotion cap: {old:.2f} → {self._emotion_cap:.2f}")

    def get_all_flags(self) -> Dict[str, bool]:
        """Return all current flag states."""
        return dict(self._flags)

    def get_audit_log(self, limit: int = 50) -> List[Dict]:
        """Return recent audit log entries."""
        return [asdict(e) for e in self._audit_log[-limit:]]

    def on_flag_change(self, flag_name: str, callback: Callable):
        """Register a listener for when a specific flag changes."""
        if flag_name not in self._listeners:
            self._listeners[flag_name] = []
        self._listeners[flag_name].append(callback)

    def on_any_change(self, callback: Callable):
        """Register a listener for any flag change."""
        self.on_flag_change("*", callback)

    def _notify_listeners(self, flag_name: str, old_val: bool, new_val: bool):
        """Notify registered listeners of a flag change."""
        for cb in self._listeners.get(flag_name, []):
            try:
                cb(flag_name, old_val, new_val)
            except Exception as e:
                logger.debug(f"[KillSwitches] Listener error: {e}")
        for cb in self._listeners.get("*", []):
            try:
                cb(flag_name, old_val, new_val)
            except Exception as e:
                logger.debug(f"[KillSwitches] Global listener error: {e}")

    def apply_governance_override(self, age_band: str = "adult"):
        """
        Apply age-based governance overrides.
        Under-18 gets stricter caps.
        """
        if age_band in ("under_13", "under_16"):
            self.set_flag(
                FeatureFlag.EMOTION_TRACKING, False,
                reason=f"age_band={age_band}", source="governance",
            )
            self.set_flag(
                FeatureFlag.PERSONALITY_DRIFT, False,
                reason=f"age_band={age_band}", source="governance",
            )
            self.set_emotion_cap(0.4, reason=f"age_band={age_band}")

    def snapshot(self) -> Dict[str, Any]:
        """Return a full snapshot for broadcasting to clients."""
        return {
            "flags": dict(self._flags),
            "emotion_cap": self._emotion_cap,
            "audit_count": len(self._audit_log),
        }

    def to_broadcast_frame(self) -> Dict[str, Any]:
        """WebSocket broadcast frame for client sync."""
        return {
            "type": "killswitch.update",
            "flags": dict(self._flags),
            "emotion_cap": self._emotion_cap,
            "timestamp": time.time(),
        }


# ── Module singleton ──────────────────────────────────────────────────────────

_kill_switches: Optional[KillSwitchSystem] = None


def get_kill_switches() -> KillSwitchSystem:
    global _kill_switches
    if _kill_switches is None:
        _kill_switches = KillSwitchSystem()
    return _kill_switches


# ── Capture-device helpers ────────────────────────────────────────────────────
# A feature being "on" never overrides an explicit hardware kill: these are
# ANDed, so MICROPHONE=False closes the mic even while VOICE_PIPELINE is True.

def microphone_allowed() -> bool:
    """True only when BOTH the voice pipeline and the mic kill switch allow capture."""
    ks = get_kill_switches()
    return ks.is_enabled(FeatureFlag.MICROPHONE) and ks.is_enabled(FeatureFlag.VOICE_PIPELINE)


def camera_allowed() -> bool:
    """True only when BOTH vision and the camera kill switch allow capture."""
    ks = get_kill_switches()
    return ks.is_enabled(FeatureFlag.CAMERA) and ks.is_enabled(FeatureFlag.VISION)
