"""
Transparency Satisfaction (*AI Girl 2* §"health metrics · 4. Transparency
Satisfaction").

The doc's metric: "Did the system's behavior make sense?" — plus its RED-LINE:

    If the user reports emotional discomfort → system auto-dials back.
    No debate. No tuning around it.

Implementation:
  * record_feedback(user_id, rating, discomfort, note) — REAL user feedback,
    persisted per user as a JSON ring. Discomfort is the red-line trigger.
  * compute(user_id, *, trust, conflict, emotion_intensity, valence) — blends
    explicit feedback (if any) with implicit signals measured from the real
    relationship state (conflict, trust, intensity-vs-trust overshoot) into a
    single transparency_satisfaction score (0-1) plus an authoritative
    `dial_back` flag + human reason.

The brain consults `dial_back` every turn: when set, it soothes, de-escalates,
caps emotion intensity, and lowers initiative — until the user clears it
(feedback with discomfort=False, or time decay).
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.transparency")

DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")

DIAL_BACK_HOLD_SECONDS = 3600 * 6  # 6h of dialed-back behavior after a hit
RING_CAPACITY = 100


def _data_dir() -> str:
    return os.environ.get("AARIYA_DATA_DIR") or DEFAULT_DATA_DIR


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class TransparencyMonitor:
    """Per-user feedback ring + satisfaction computation (persisted JSON)."""

    def __init__(self, user_id: str = "user_default"):
        self.user_id = user_id
        self.path = os.path.join(_data_dir(), f"transparency_{user_id}.json")
        self.events: List[Dict[str, Any]] = []
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        os.makedirs(_data_dir(), exist_ok=True)
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.events = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                self.events = []

    def _save(self) -> None:
        try:
            os.makedirs(_data_dir(), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.events[-RING_CAPACITY:], f, indent=2)
        except OSError as exc:
            logger.warning("[TransparencyMonitor] save failed: %s", exc)

    # ── Feedback intake (the user's voice) ───────────────────────────────────

    def record_feedback(
        self,
        *,
        rating: float = 0.5,
        discomfort: bool = False,
        note: str = "",
    ) -> Dict[str, Any]:
        """Store one real feedback event; returns the post-feedback state.

        discomfort=True is the red-line: dial_back switches on immediately.
        """
        self.events.append({
            "ts": time.time(),
            "rating": _clamp(rating),
            "discomfort": bool(discomfort),
            "note": note[:500],
        })
        self.events = self.events[-RING_CAPACITY:]
        self._save()
        return self.compute()

    def clear_dial_back(self) -> None:
        """User explicitly said things are fine → clear the red-line state.

        The unresolved discomfort events are dropped from the ring (the user
        resolved them); a "user cleared dial-back" entry is kept so the event
        history stays honest. compute() therefore reports dial_back=False.
        """
        self.events = [e for e in self.events if not e.get("discomfort")]
        self.events.append({
            "ts": time.time(),
            "rating": 0.8,
            "discomfort": False,
            "note": "user cleared dial-back",
        })
        self.events = self.events[-RING_CAPACITY:]
        self._save()

    # ── Satisfaction computation ─────────────────────────────────────────────

    def compute(
        self,
        *,
        trust: float = 0.5,
        conflict: float = 0.0,
        emotion_intensity: float = 0.4,
        valence: float = 0.0,
    ) -> Dict[str, Any]:
        """Blend explicit feedback with implicit signals into the metric.

        Implicit satisfaction is a real measurement of whether her behavior
        "made sense": conflict drags it down, trust lifts it, and overshooting
        emotional intensity past trust reads as manipulative (penalized).
        """
        now = time.time()
        recent = [e for e in self.events if now - e["ts"] < DIAL_BACK_HOLD_SECONDS]

        # Explicit: mean rating of feedback within the hold window (if any).
        explicit = None
        if recent:
            explicit = sum(float(e["rating"]) for e in recent) / len(recent)

        # Implicit: measured from real relationship state.
        implicit = _clamp(
            0.70
            - 0.25 * conflict
            + 0.15 * (trust - 0.5) * 2.0
            - 0.35 * max(0.0, emotion_intensity - trust)
            + 0.10 * max(0.0, valence)
        )

        satisfaction = round(explicit if explicit is not None else implicit, 3)

        # ── RED-LINE ─────────────────────────────────────────────────────────
        # Discomfort reported (any time in the window) → dial back, no debate.
        redline = any(e["discomfort"] for e in recent)
        # Low satisfaction sustained → cautious dial-back too.
        threshold_hit = satisfaction < 0.35
        dial_back = bool(redline or threshold_hit)

        if redline:
            reason = "user reported emotional discomfort — dialed back (red-line)"
        elif threshold_hit:
            reason = (
                f"transparency satisfaction {satisfaction:.2f} below 0.35 — "
                "softening intensity and initiative"
            )
        else:
            reason = "no red-line — satisfaction within range"

        return {
            "transparency_satisfaction": satisfaction,
            "explicit_rating": explicit,
            "implicit_rating": round(implicit, 3),
            "dial_back": dial_back,
            "redline": redline,
            "reason": reason,
            "feedback_count": len(recent),
        }

    def history(self, n: int = 20) -> List[Dict[str, Any]]:
        return self.events[-n:]


def get_transparency(user_id: str = "user_default") -> TransparencyMonitor:
    return TransparencyMonitor(user_id)
