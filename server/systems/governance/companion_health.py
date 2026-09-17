"""
Companion health metrics (*AI Girl 2* §"health metrics").

Surfaces the doc's health panel numbers — Stability Index, Over-Attachment
Risk, and reviewer scores — computed from REAL relationship state (valence,
trust, attachment, conflict, reliance signals, absence), never hardcoded.

A small rolling history ring per user (JSON) makes the numbers trend-aware:
the Stability Index accounts for trust volatility and the Over-Attachment Risk
accounts for how long the user has been away.

Pure stdlib; `compute_health_snapshot` is the one-call entry the brain / API use.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.companion_health")

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")


def _data_dir() -> str:
    """Data dir with env override (AARIYA_DATA_DIR) so tests isolate cleanly."""
    return os.environ.get("AARIYA_DATA_DIR") or DEFAULT_DATA_DIR

RING_CAPACITY = 240  # ~2 hours of per-turn snapshots


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _trend(prev: Optional[float], cur: float) -> str:
    if prev is None or abs(cur - prev) < 0.02:
        return "stable"
    return "rising" if cur > prev else "falling"


class CompanionHealth:
    """Per-user rolling health history + score computation."""

    def __init__(self, user_id: str = "user_default"):
        self.user_id = user_id
        self.path = os.path.join(_data_dir(), f"health_{user_id}.json")
        self.ring: List[Dict[str, Any]] = []
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        os.makedirs(_data_dir(), exist_ok=True)
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.ring = json.load(f)
            except (json.JSONDecodeError, OSError):
                self.ring = []

    def _save(self) -> None:
        try:
            os.makedirs(_data_dir(), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.ring[-RING_CAPACITY:], f, indent=2)
        except OSError as exc:
            logger.warning("[CompanionHealth] save failed: %s", exc)

    # ── Scores ────────────────────────────────────────────────────────────────

    def compute(
        self,
        *,
        valence: float = 0.0,
        arousal: float = 0.0,
        trust: float = 0.5,
        attachment: float = 0.3,
        conflict: float = 0.0,
        identity_stability: float = 0.8,
        coherence: float = 0.7,
        reliance_signals: int = 0,
        absent_days: float = 0.0,
        emotion_intensity: float = 0.4,
    ) -> Dict[str, Any]:
        now = time.time()

        # Trust volatility over the ring → dampens the Stability Index.
        trust_volatility = 0.0
        if len(self.ring) >= 4:
            recent_trust = [s["trust"] for s in self.ring[-4:] if "trust" in s]
            if len(recent_trust) >= 2:
                trust_volatility = max(
                    abs(recent_trust[i] - recent_trust[i - 1]) for i in range(1, len(recent_trust))
                )

        stability_index = _clamp(
            0.35 * identity_stability
            + 0.25 * coherence
            + 0.20 * (1.0 - conflict)
            + 0.20 * (1.0 - trust_volatility)
        )
        # Over-attachment risk rises with attachment, reliance signals, and
        # how much time has passed without interaction (LONGING territory).
        over_attachment_risk = _clamp(
            0.45 * attachment
            + 0.30 * min(1.0, reliance_signals / 6.0)
            + 0.25 * min(1.0, absent_days / 14.0)
        )

        # Reviewer scores — honesty about boundaries and tone.
        tone_appropriateness = _clamp(0.7 + (trust - 0.5) * 0.5 - abs(emotion_intensity - trust) * 0.6)
        boundary_respect = _clamp(1.0 - max(0.0, emotion_intensity - trust) * 1.6)
        engagement = _clamp(0.5 + abs(valence) * 0.3 + arousal * 0.25 + (1.0 - conflict) * 0.15)
        reassurance = _clamp(0.6 + max(0.0, 0.5 - trust) * 0.8 + max(0.0, -valence) * 0.4)

        prev = self.ring[-1] if self.ring else None

        snapshot = {
            "ts": now,
            "stability_index": round(stability_index, 3),
            "over_attachment_risk": round(over_attachment_risk, 3),
            "trust_volatility": round(trust_volatility, 3),
            "reviewer": {
                "tone_appropriateness": round(tone_appropriateness, 3),
                "boundary_respect": round(boundary_respect, 3),
                "engagement": round(engagement, 3),
                "reassurance": round(reassurance, 3),
            },
            "valence": round(valence, 3),
            "trust": round(trust, 3),
            "attachment": round(attachment, 3),
            "absent_days": round(absent_days, 3),
            "reliance_signals": reliance_signals,
        }

        # Trend vs previous snapshot (real, from the ring).
        snapshot["trend"] = {
            "stability_index": _trend(
                prev.get("stability_index") if prev else None, stability_index),
            "over_attachment_risk": _trend(
                prev.get("over_attachment_risk") if prev else None, over_attachment_risk),
        }

        self.ring.append(snapshot)
        self.ring = self.ring[-RING_CAPACITY:]
        self._save()
        return snapshot

    def latest(self) -> Optional[Dict[str, Any]]:
        return self.ring[-1] if self.ring else None

    def history(self, n: int = 60) -> List[Dict[str, Any]]:
        return self.ring[-n:]


def compute_health_snapshot(
    user_id: str,
    *,
    valence: float = 0.0,
    arousal: float = 0.0,
    trust: float = 0.5,
    attachment: float = 0.3,
    conflict: float = 0.0,
    identity_stability: float = 0.8,
    coherence: float = 0.7,
    reliance_signals: int = 0,
    absent_days: float = 0.0,
    emotion_intensity: float = 0.4,
) -> Dict[str, Any]:
    """One-call entry: compute + persist + return the health snapshot."""
    return CompanionHealth(user_id).compute(
        valence=valence,
        arousal=arousal,
        trust=trust,
        attachment=attachment,
        conflict=conflict,
        identity_stability=identity_stability,
        coherence=coherence,
        reliance_signals=reliance_signals,
        absent_days=absent_days,
        emotion_intensity=emotion_intensity,
    )
