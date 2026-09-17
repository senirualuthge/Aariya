"""
Prediction verification loop (NEWPredictionPRT2 §11 / Phase 8).

Doc: "Most AI predicts. Few verify." This module closes the loop:
predict → store → observe → verify → score → recalibrate.

  verify_due(engine, resolver)  → check past-due predictions against real
                                  outcomes, mark correct/incorrect, and fold
                                  the results back into confidence + beliefs.

  calibration metrics            → per-domain accuracy, agreement, average
                                  over-confidence so the UI can show "she was
                                  right 68% of the time" (not just raw count).

  recalibrate(engine)            → doc §3 Confidence Calibration: an incorrect
                                  prediction decays its stored confidence
                                  (new_confidence = old * 0.9); a correct one
                                  nudges it up slightly.

The resolver is supplied by the caller (brain/daemon) so the loop stays
domain-agnostic: it decides what "the real outcome" is for a stored
prediction (e.g. the actual valence/arousal observed at verify time). If no
resolver verdict can be reached, the prediction is left unverified rather
than guessed at.
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("aariya.prediction_verify")


class PredictionVerifier:
    """Closed-loop verification + calibration for a PredictionEngine."""

    def __init__(self, engine, *, horizon_seconds: float = 300.0):
        self.engine = engine
        self.horizon_seconds = horizon_seconds
        # Per-domain accuracy ledger (doc §15 Evaluation Framework).
        self._domain_stats: Dict[str, Dict[str, float]] = {}
        # Distribution-shift tracker (doc §"5. DRIFT DETECTION ENGINE").
        from server.systems.prediction.drift_detector import DriftDetector
        self.drift = DriftDetector()

    # ── Verification ─────────────────────────────────────────────────────────

    def verify_due(self, resolver: Optional[Callable[[Dict[str, Any]], Optional[bool]]] = None,
                   *, force: bool = False) -> Dict[str, Any]:
        """Check unverified predictions whose time has come.

        resolver(prediction) → True/False/None. None means "cannot tell yet"
        and the prediction stays unverified. When resolver is omitted, only
        predictions with an expected_date are eligible and the stored
        `actual_outcome` (if any) decides correctness.
        """
        now = time.time()
        verified = 0
        verification_samples: List[Dict[str, Any]] = []
        for entry in list(self.engine.store.predictions):
            if entry.get("verified"):
                continue
            eligible = force
            if entry.get("expected_date"):
                try:
                    eligible = now >= float(entry["expected_date"])
                except (TypeError, ValueError):
                    eligible = force
            elif resolver is not None:
                # No expected date: use the configured verification horizon.
                eligible = (now - float(entry.get("added_at", now))) >= self.horizon_seconds
            if not eligible:
                continue

            verdict = None
            if resolver is not None:
                verdict = resolver(entry)
            if verdict is None and entry.get("actual_outcome") is not None:
                verdict = bool(entry.get("correct"))
            if verdict is None:
                continue  # no real verdict yet — don't guess

            self.engine.store.verify(entry["id"], "resolved", correct=verdict)
            self._record(entry.get("domain", "general"), verdict)
            self.drift.record(verdict, domain=entry.get("domain", "general"))
            verification_samples.append({
                "confidence": float(entry.get("confidence", 0.5)),
                "correct": 1 if verdict else 0,
                "value": float(entry.get("value", 0.5)),
            })
            verified += 1

        if verified:
            self._recalibrate()
            # Learned forecast (NEWPredictionPRT2 §ForecastModel): fold the
            # freshly verified transitions into the forecast head so
            # predict_future() learns instead of walking randomly.
            try:
                self.engine.core.forecast_model.learn_from_verification(
                    self.engine.store.predictions)
            except Exception as e:
                logger.debug(f"[PredictionVerifier] forecast learn skipped: {e}")

        # Core recalibration (drift→retrain): feed this pass's verification
        # outcomes into PredictionCore so confidence bias self-corrects, and
        # widen confidence when the drift detector says the distribution moved.
        calibration = self.engine.core.calibrate(verification_samples)
        drift_snapshot = self.drift.snapshot()
        retrain = {}
        if drift_snapshot.get("drift_detected"):
            retrain = self.engine.core.drift_recalibrate(drift_snapshot)

        return {
            "verified_this_pass": verified,
            "accuracy": self.engine.store.accuracy(),
            "per_domain": dict(self._domain_stats),
            "calibration": calibration,
            "recalibration": retrain,
            "drift": drift_snapshot,
        }

    # ── Feedback ─────────────────────────────────────────────────────────────

    def _record(self, domain: str, correct: bool) -> None:
        stats = self._domain_stats.setdefault(domain, {"correct": 0.0, "total": 0.0})
        stats["total"] += 1.0
        if correct:
            stats["correct"] += 1.0

    def _recalibrate(self) -> None:
        """Doc §3 Confidence Calibration — fold verification results back into
        stored confidences so the engine stops being over-confident."""
        for entry in self.engine.store.predictions:
            if not entry.get("verified"):
                continue
            conf = float(entry.get("confidence", 0.5))
            if entry.get("correct"):
                entry["confidence"] = round(min(0.99, conf * 1.02), 3)
            else:
                entry["confidence"] = round(max(0.05, conf * 0.9), 3)

    # ── Metrics ──────────────────────────────────────────────────────────────

    def metrics(self) -> Dict[str, Any]:
        """Calibration / evaluation summary for the dashboard (§15)."""
        store = self.engine.store
        verified = [p for p in store.predictions if p.get("verified")]
        correct = [p for p in verified if p.get("correct")]
        overconfident = [
            {"id": p["id"], "confidence": p["confidence"], "correct": p.get("correct")}
            for p in verified
            if float(p.get("confidence", 0.5)) > 0.7 and not p.get("correct")
        ]
        return {
            "total": len(store.predictions),
            "verified": len(verified),
            "correct": len(correct),
            "accuracy": round(store.accuracy(), 3),
            "per_domain": {k: {"accuracy": round(v["correct"] / v["total"], 3), "n": int(v["total"])}
                           for k, v in self._domain_stats.items()},
            "overconfident_misses": overconfident[-5:],
            "loop_closed": len(verified) > 0,
            "drift": self.drift.snapshot(),
            "core_calibration": self.engine.core.calibration_state(),
        }
