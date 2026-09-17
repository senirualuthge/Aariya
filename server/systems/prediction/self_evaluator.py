"""
Self Evaluation Engine (NEWPredictionPRT2 §"3. Self Evaluation Engine").

Doc: "No automatic improvement loop." This module closes that loop with a
QUANTITATIVE score, not just binary right/wrong:

    class Evaluator:
        def evaluate(self, prediction, actual):
            error = abs(prediction - actual)
            return error

    class LearningLoop:
        update(error)           → record the error, decay learned weights
        convergence_rate()      → 1 - mean(recent errors)  (1.0 = converged)

  Predict
    → Actual Result
    → Error Score
    → Learning Update

The store keeps each prediction's numeric predicted value and records the
numeric actual value at verify time, so the error magnitude (MAE), not just
correctness, feeds back into confidence and the dashboard's "she was right"
story.

SelfEvaluator is the composing facade: record() a predicted/actual pair, get
MAE / convergence / a persisted error history.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.self_evaluator")


class Evaluator:
    """The doc's Evaluator — error = |prediction - actual|."""

    def evaluate(self, prediction: float, actual: float) -> float:
        try:
            return abs(float(prediction) - float(actual))
        except (TypeError, ValueError):
            return 0.0


class LearningLoop:
    """Doc §3 LearningLoop — error history + learned weights decay + convergence.

    weights are per-feature learned gains (0..1). Each update() decays every
    weight by (1 - learning_rate * error) so features that tracked error get
    pulled toward 0 (less reliance on them). convergence_rate() approaches 1.0
    as recent mean error approaches 0, meaning the engine has converged on the
    current data distribution.
    """

    def __init__(self, learning_rate: float = 0.01):
        self.learning_rate = float(learning_rate)
        self.weights: Dict[str, float] = {}
        self.error_history: List[float] = []

    def set_weight(self, key: str, value: float = 1.0) -> None:
        self.weights[key] = max(0.0, min(1.0, float(value)))

    def update(self, error: float, *, feature: Optional[str] = None) -> None:
        error = max(0.0, min(1.0, float(error)))
        self.error_history.append(error)
        if len(self.error_history) > 100:
            self.error_history.pop(0)
        decay = (1.0 - self.learning_rate * error)
        for key in self.weights:
            self.weights[key] = max(0.0, min(1.0, self.weights[key] * decay))

    def convergence_rate(self) -> float:
        if len(self.error_history) < 10:
            return 1.0
        recent = self.error_history[-10:]
        return round(1.0 - (sum(recent) / len(recent)), 3)

    def mean_abs_error(self, window: int = 0) -> float:
        if not self.error_history:
            return 0.0
        sample = self.error_history[-window:] if window > 0 else self.error_history
        return round(sum(sample) / len(sample), 4)

    def state(self) -> Dict[str, Any]:
        return {
            "learning_rate": self.learning_rate,
            "n_samples": len(self.error_history),
            "mae": self.mean_abs_error(),
            "convergence_rate": self.convergence_rate(),
            "weights": dict(self.weights),
        }


class SelfEvaluator:
    """Facade: quantitative prediction-error loop with persistence.

        self_eval.record(predicted=0.7, actual=0.2, domain="conversation")
        self_eval.metrics()  → {"mae": ..., "per_domain": {...}, "convergence": ...}
    """

    def __init__(self, persist_path: Optional[str] = None):
        self.persist_path = persist_path
        self.evaluator = Evaluator()
        self.loop = LearningLoop()
        self._domains: Dict[str, List[float]] = {}
        if persist_path:
            self._load()

    def record(self, predicted: float, actual: float, *, domain: str = "general",
               feature: Optional[str] = None) -> float:
        """Feed one (predicted, actual) pair; returns the absolute error."""
        error = self.evaluator.evaluate(predicted, actual)
        self.loop.update(error, feature=feature)
        self._domains.setdefault(domain, []).append(error)
        if len(self._domains[domain]) > 1000:
            self._domains[domain] = self._domains[domain][-1000:]
        self._save()
        return error

    def domain_mae(self) -> Dict[str, float]:
        return {d: round(sum(errs) / len(errs), 4)
                for d, errs in self._domains.items() if errs}

    def metrics(self) -> Dict[str, Any]:
        return {
            "mae": self.loop.mean_abs_error(),
            "convergence_rate": self.loop.convergence_rate(),
            "per_domain": self.domain_mae(),
            "n_samples": len(self.loop.error_history),
            "weights": dict(self.loop.weights),
        }

    def _save(self) -> None:
        if not self.persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self.persist_path) or ".", exist_ok=True)
            with open(self.persist_path, "w", encoding="utf-8") as f:
                json.dump({
                    "learning_rate": self.loop.learning_rate,
                    "error_history": self.loop.error_history,
                    "weights": self.loop.weights,
                    "domains": self._domains,
                }, f, indent=2)
        except OSError as exc:
            logger.warning("[SelfEvaluator] persist failed: %s", exc)

    def _load(self) -> None:
        if not self.persist_path:
            return
        try:
            if not os.path.exists(self.persist_path):
                return
            with open(self.persist_path, encoding="utf-8") as f:
                data = json.load(f)
            self.loop.learning_rate = float(data.get("learning_rate", 0.01))
            self.loop.error_history = list(data.get("error_history", []))
            self.loop.weights = dict(data.get("weights", {}))
            self._domains = {k: list(v) for k, v in data.get("domains", {}).items()}
            logger.info("[SelfEvaluator] loaded %d error samples", len(self.loop.error_history))
        except Exception as exc:
            logger.warning("[SelfEvaluator] load failed (fresh start): %s", exc)
