"""
Learned forecast (NEWPredictionPRT2 §ForecastModel / "No automatic improvement
loop").

The doc's predictor chain ends with a ForecastModel that learns instead of
following a fixed random walk. This module trains a small torch MLP on
(value, confidence) → next-value transitions gathered from the prediction
store's verified (predicted_value, actual_value) pairs, so predict_future()
uses a genuinely learned forecast when data exists and degrades to a simple
momentum heuristic when it doesn't (never crashes without torch either).

Design:

  ForecastModel.learn(history)     → train/fit from [(x0, c0, y0), ...]
  ForecastModel.predict(state, n)  → learned multi-step continuation
  ForecastModel.trained            → whether a fit has been completed

torch is optional: if unavailable (or too few samples), predict() falls back
to the same bounded random-walk shape the engine used before, so the learned
head is a pure upgrade, never a new failure mode.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger("aariya.forecast_model")

_MIN_SAMPLES = 8
_FALLBACK_STEP = 0.08


class _MLP:
    """Tiny 2-layer MLP mapping [value, confidence] → delta. Trained with the
    Adam optimizer on mean-squared error; kept ~200 params so it trains in a
    few ms on turn history."""

    def __init__(self) -> None:
        import torch  # type: ignore[import-not-found]
        self._torch = torch
        self.model = torch.nn.Sequential(
            torch.nn.Linear(2, 16),  # type: ignore[union-attr]
            torch.nn.Tanh(),  # type: ignore[union-attr]
            torch.nn.Linear(16, 1),  # type: ignore[union-attr]
        )
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=0.02)  # type: ignore[union-attr]
        self.loss_fn = torch.nn.MSELoss()  # type: ignore[union-attr]

    def fit(self, x: Any, y: Any, epochs: int = 60) -> float:
        self.model.train()
        last_loss = 0.0
        for _ in range(epochs):
            self.optimizer.zero_grad()
            out = self.model(x).squeeze(-1)
            loss = self.loss_fn(out, y)
            loss.backward()
            self.optimizer.step()
            last_loss = float(loss.item())
        self.model.eval()
        return last_loss

    def forward(self, x: Any) -> Any:
        self.model.eval()
        with self._torch.no_grad():
            return self.model(x).squeeze(-1)


class ForecastModel:
    """Learnable successor to the engine's random-walk predict_future."""

    def __init__(self) -> None:
        self._mlp: Optional[_MLP] = None
        self.trained = False
        self._last_train_ts: Optional[float] = None
        self._n_samples = 0
        self._last_loss: Optional[float] = None

    # ── Training ──────────────────────────────────────────────────────────────

    def learn(self, history: Sequence[Tuple[float, float, float]]) -> bool:
        """Fit on (value, confidence) → actual next value transitions.
        Returns True when a model was trained (enough samples + torch)."""
        samples = [(float(v), float(c), float(a)) for v, c, a in history]
        if len(samples) < _MIN_SAMPLES:
            logger.debug("[ForecastModel] need >= %d samples, have %d",
                         _MIN_SAMPLES, len(samples))
            return False
        try:
            import torch
        except ImportError:
            logger.debug("[ForecastModel] torch unavailable — staying heuristic")
            return False

        xs = torch.tensor([[v, c] for v, c, _ in samples], dtype=torch.float32)
        ys = torch.tensor([a for _, _, a in samples], dtype=torch.float32)
        mlp = _MLP()
        loss = mlp.fit(xs, ys)
        self._mlp = mlp
        self.trained = True
        self._n_samples = len(samples)
        self._last_train_ts = time.time()
        self._last_loss = loss
        logger.info("[ForecastModel] trained on %d samples (loss %.4f)", self._n_samples, loss)
        return True

    def learn_from_verification(self, predictions: Sequence[Dict[str, Any]]) -> bool:
        """Extract verified (predicted_value, confidence) → actual_value pairs
        straight from the prediction store and learn on them."""
        history = []
        for p in predictions:
            if p.get("verified") and p.get("predicted_value") is not None \
               and p.get("actual_value") is not None:
                history.append((p["predicted_value"], float(p.get("confidence", 0.5)),
                                p["actual_value"]))
        return self.learn(history)

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict(self, state: Dict[str, float], steps: int = 3) -> List[float]:
        """Multi-step continuation of a scalar. Uses the learned model when
        trained, otherwise a bounded momentum heuristic."""
        current = max(0.0, min(1.0, float(state.get("value", 0.0))))
        confidence = max(0.0, min(1.0, float(state.get("confidence", 0.5))))
        series: List[float] = []
        value = current
        for _ in range(max(1, int(steps))):
            if self.trained and self._mlp is not None:
                torch = self._mlp._torch
                with torch.no_grad():
                    delta = float(self._mlp.forward(
                        torch.tensor([[value, confidence]], dtype=torch.float32)).item())
                # Clamp the learned delta so the path stays bounded.
                delta = max(-0.3, min(0.3, delta))
            else:
                # Momentum fallback: move a bounded step toward 0.5 with a
                # slight random walk (matches the old engine's shape).
                import random
                delta = (0.5 - value) * 0.1 + random.uniform(-_FALLBACK_STEP, _FALLBACK_STEP)
            value = max(0.0, min(1.0, value + delta))
            series.append(round(value, 3))
        return series

    def state(self) -> Dict[str, Any]:
        return {
            "trained": self.trained,
            "n_samples": self._n_samples,
            "last_train_ts": self._last_train_ts,
            "last_loss": self._last_loss,
        }
