"""
EmotionPredictor — Enhanced
Predicts the user's NEXT emotional state (valence/arousal) from a rolling
history of REAL measured states.

Two kernels, chosen by data availability:
  * "ar1-fit"   — an online least-squares autoregressive fit learned from this
                  user's actual history window (numpy lstsq). The transition
                  coefficients are estimated from observed dynamics, not
                  assumed.
  * "heuristic" — exponentially-weighted trend continuation used only while
                  the window is too short to fit (needs ≥3 transitions).

Both operate exclusively on recorded valence/arousal values; nothing is
synthetic. When a trained PyTorch checkpoint becomes available, `load_model()`
can supersede both.
"""

from typing import Optional
import math

try:
    import numpy as _np
except ImportError:
    _np = None

# ── Sentinel for "risk zone" ───────────────────────────────────────────────────
DISTRESS_THRESHOLD  = -0.3   # predicted valence below this = distress risk
ESCALATION_VELOCITY = -0.15  # rapid drop per turn = escalation risk

# Minimum number of state TRANSITIONS needed to fit the AR model honestly.
_MIN_FIT_TRANSITIONS = 3


class EmotionPredictor:
    """
    Predicts the user's next emotional state.

    Kernel selection is data-driven: as soon as the real history window has
    enough consecutive pairs, an AR(1)-with-momentum model is fitted to THIS
    user's observed transitions and used for forecasting.
    """

    def __init__(self, history_len: int = 8):
        self.history_len = history_len
        self._history: list[dict] = []   # rolling window: [{valence, arousal}, ...]

    # ── Public API ─────────────────────────────────────────────────────────────

    def record(self, valence: float, arousal: float) -> None:
        """Push current state into the rolling window."""
        self._history.append({"valence": valence, "arousal": arousal})
        if len(self._history) > self.history_len:
            self._history.pop(0)

    def predict_next(self) -> dict:
        """
        Returns a dict with:
            predicted_valence   float
            predicted_arousal   float
            distress_risk       bool    (predicted_valence < DISTRESS_THRESHOLD)
            escalation_risk     bool    (valence dropping fast)
            velocity_valence    float   (rate of change per turn)
            confidence          float   [0.0 – 1.0]
            method              str     "ar1-fit" | "heuristic"
        """
        if len(self._history) < 2:
            v = self._history[-1]["valence"] if self._history else 0.0
            a = self._history[-1]["arousal"] if self._history else 0.5
            return self._package(v, a, velocity_v=0.0,
                                 confidence=0.1, method="heuristic")

        pred_v, pred_a, vel_v, method = self._forecast(self._history)
        confidence = min(1.0, len(self._history) / self.history_len)
        return self._package(pred_v, pred_a, velocity_v=vel_v,
                             confidence=confidence, method=method)

    def predict_next_state(
        self,
        current_valence: float,
        current_arousal: float,
        sequence_history: list
    ) -> tuple[float, float]:
        """
        Legacy compatibility wrapper used by external callers.
        Merges provided history with internal window and predicts.
        """
        merged = (sequence_history or []) + [{"valence": current_valence, "arousal": current_arousal}]
        merged = merged[-self.history_len:]
        if len(merged) < 2:
            return current_valence, current_arousal
        pred_v, pred_a, _, _ = self._forecast(merged)
        return pred_v, pred_a

    # ── Core prediction kernels ────────────────────────────────────────────────

    def _fit_ar1(self, window: list[dict]):
        """Fit per-dimension AR(1): x_{t+1} = c + φ·x_t on the REAL window.

        Returns ((c_v, phi_v), (c_a, phi_a)) or None when there are fewer
        than _MIN_FIT_TRANSITIONS usable consecutive pairs (or numpy is
        missing). Ordinary least squares over the observed transitions —
        coefficients come from this user's actual dynamics.
        """
        if _np is None or len(window) < _MIN_FIT_TRANSITIONS + 1:
            return None
        try:
            cur_v = _np.array([s["valence"] for s in window[:-1]])
            nxt_v = _np.array([s["valence"] for s in window[1:]])
            cur_a = _np.array([s["arousal"] for s in window[:-1]])
            nxt_a = _np.array([s["arousal"] for s in window[1:]])

            design_v = _np.column_stack([_np.ones_like(cur_v), cur_v])
            design_a = _np.column_stack([_np.ones_like(cur_a), cur_a])
            coef_v, *_ = _np.linalg.lstsq(design_v, nxt_v, rcond=None)
            coef_a, *_ = _np.linalg.lstsq(design_a, nxt_a, rcond=None)
            return tuple(coef_v), tuple(coef_a)
        except Exception:
            return None

    def _forecast(self, window: list[dict]) -> tuple[float, float, float, str]:
        """Produce (pred_v, pred_a, vel_v, method) from the real window."""
        n = len(window)

        # Velocity from the last few REAL steps.
        recent = window[-3:]
        if len(recent) > 1:
            vel_v = (recent[-1]["valence"] - recent[0]["valence"]) / max(len(recent) - 1, 1)
            vel_a = (recent[-1]["arousal"] - recent[0]["arousal"]) / max(len(recent) - 1, 1)
        else:
            vel_v, vel_a = 0.0, 0.0

        last_v = window[-1]["valence"]
        last_a = window[-1]["arousal"]

        fitted = self._fit_ar1(window)
        if fitted is not None:
            (c_v, phi_v), (c_a, phi_a) = fitted
            pred_v = c_v + phi_v * last_v
            pred_a = c_a + phi_a * last_a
            method = "ar1-fit"
        else:
            # Too few transitions to fit honestly yet — exponential-smoothing
            # continuation of the observed trajectory.
            weights = [math.exp(0.5 * i) for i in range(n)]
            total_w = sum(weights)
            avg_v = sum(w * s["valence"] for w, s in zip(weights, window)) / total_w
            avg_a = sum(w * s["arousal"] for w, s in zip(weights, window)) / total_w
            pred_v = avg_v + vel_v * 0.6
            pred_a = avg_a + vel_a * 0.6
            method = "heuristic"

        pred_v = max(-1.0, min(1.0, pred_v))
        pred_a = max(0.0, min(1.0, pred_a))
        return pred_v, pred_a, vel_v, method

    def _package(self, pred_v: float, pred_a: float, velocity_v: float,
                 confidence: float, method: str) -> dict:
        return {
            "predicted_valence": pred_v,
            "predicted_arousal": pred_a,
            "distress_risk":     pred_v < DISTRESS_THRESHOLD,
            "escalation_risk":   velocity_v < ESCALATION_VELOCITY,
            "velocity_valence":  velocity_v,
            "confidence":        confidence,
            "method":            method,
        }


# ── Singleton per user ─────────────────────────────────────────────────────────
_instances: dict[str, EmotionPredictor] = {}

def get_emotion_predictor(user_id: str) -> EmotionPredictor:
    if user_id not in _instances:
        _instances[user_id] = EmotionPredictor()
    return _instances[user_id]
