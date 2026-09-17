"""
Drift detection engine (NEWPredictionPRT2 §"5. DRIFT DETECTION ENGINE").

Detects when the prediction engine's accuracy is degrading over time — a
signal the underlying distribution has shifted and the engine needs
recalibration or re-training. Tracks a rolling window of verification
outcomes and compares recent accuracy against a baseline.

    record(outcome)          → feed each verification result
    snapshot()               → {drift_detected, recent_accuracy, baseline,
                                shift_score, verdict}

The brain / daemon feed every verified prediction here; when a persistent
downward trend is detected the engine flags itself for recalibration instead
of silently degrading.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.prediction_drift")


class DriftDetector:
    def __init__(self, *, window: int = 40, baseline_window: int = 60,
                 threshold: float = 0.15, persist_path: Optional[str] = None):
        self.window = max(10, window)
        self.baseline_window = max(20, baseline_window)
        self.threshold = threshold  # recent accuracy < baseline - threshold → drift
        self._outcomes: List[Dict[str, Any]] = []
        self._persist_path = persist_path
        if persist_path:
            self._load()

    def record(self, correct: bool, *, domain: str = "general") -> None:
        self._outcomes.append({
            "ts": time.time(),
            "correct": bool(correct),
            "domain": domain,
        })
        if len(self._outcomes) > max(self.window, self.baseline_window) * 3:
            self._outcomes = self._outcomes[-max(self.window, self.baseline_window) * 2:]
        if self._persist_path:
            self._save()

    def _accuracy(self, tail: List[Dict[str, Any]]) -> float:
        if not tail:
            return 0.0
        return sum(1 for o in tail if o["correct"]) / len(tail)

    def snapshot(self) -> Dict[str, Any]:
        total = len(self._outcomes)
        baseline = self._outcomes[:self.baseline_window]
        recent = self._outcomes[-self.window:] if self.window <= len(self._outcomes) else self._outcomes
        recent_acc = self._accuracy(recent)
        base_acc = self._accuracy(baseline)
        shift = base_acc - recent_acc
        drift_detected = total >= self.window and shift > self.threshold
        return {
            "total_verified": total,
            "baseline": round(base_acc, 3),
            "recent_accuracy": round(recent_acc, 3),
            "shift_score": round(shift, 3),
            "drift_detected": bool(drift_detected),
            "verdict": "drift" if drift_detected else "healthy",
            "last_update": self._outcomes[-1]["ts"] if self._outcomes else None,
        }

    def _save(self) -> None:
        if not self._persist_path:
            return
        try:
            import os
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump({"outcomes": self._outcomes}, f)
        except OSError as exc:
            logger.warning("[DriftDetector] persist failed: %s", exc)

    def _load(self) -> None:
        if not self._persist_path:
            return
        try:
            import os
            import json
            if not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, encoding="utf-8") as f:
                self._outcomes = json.load(f).get("outcomes", [])
            logger.info("[DriftDetector] loaded %d outcomes", len(self._outcomes))
        except Exception as exc:
            logger.warning("[DriftDetector] load failed (fresh start): %s", exc)
