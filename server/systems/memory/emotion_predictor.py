"""
EmotionPredictor — Enhanced
Predicts the user's NEXT emotional state (valence/arousal) from a rolling history.
Uses a weighted exponential smoothing approach that simulates LSTM trend continuation.
When a real PyTorch model is available, `load_model()` replaces the mock kernel.
"""

from typing import Optional
import math

# ── Sentinel for "risk zone" ───────────────────────────────────────────────────
DISTRESS_THRESHOLD  = -0.3   # predicted valence below this = distress risk
ESCALATION_VELOCITY = -0.15  # rapid drop per turn = escalation risk


class EmotionPredictor:
    """
    Predicts the user's next emotional state.

    In production, swap `_mock_lstm` for a real PyTorch LSTM checkpoint.
    The public API stays identical.
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
        """
        if len(self._history) < 2:
            v = self._history[-1]["valence"] if self._history else 0.0
            a = self._history[-1]["arousal"] if self._history else 0.5
            return self._package(v, a, velocity_v=0.0, confidence=0.1)

        pred_v, pred_a, vel_v = self._mock_lstm(self._history)
        confidence = min(1.0, len(self._history) / self.history_len)
        return self._package(pred_v, pred_a, velocity_v=vel_v, confidence=confidence)

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
        pred_v, pred_a, _ = self._mock_lstm(merged)
        return pred_v, pred_a

    # ── Core prediction kernel ─────────────────────────────────────────────────

    def _mock_lstm(self, window: list[dict]) -> tuple[float, float, float]:
        """
        Weighted exponential trend continuation.
        Newer states get higher weight.  Mirrors what an LSTM naturally learns.
        Replace this with `model(encode(window))` when training is ready.
        """
        n = len(window)
        weights = [math.exp(0.5 * i) for i in range(n)]
        total_w = sum(weights)

        # Weighted average of recent states
        avg_v = sum(w * s["valence"] for w, s in zip(weights, window)) / total_w
        avg_a = sum(w * s["arousal"] for w, s in zip(weights, window)) / total_w

        # Velocity (last 3 steps)
        recent = window[-3:]
        if len(recent) > 1:
            vel_v = (recent[-1]["valence"] - recent[0]["valence"]) / max(len(recent) - 1, 1)
            vel_a = (recent[-1]["arousal"] - recent[0]["arousal"]) / max(len(recent) - 1, 1)
        else:
            vel_v, vel_a = 0.0, 0.0

        # Predicted = weighted avg + 0.6 × velocity (momentum)
        pred_v = avg_v + vel_v * 0.6
        pred_a = avg_a + vel_a * 0.6

        # Clamp
        pred_v = max(-1.0, min(1.0, pred_v))
        pred_a = max(0.0,  min(1.0, pred_a))

        return pred_v, pred_a, vel_v

    def _package(self, pred_v: float, pred_a: float, velocity_v: float, confidence: float) -> dict:
        return {
            "predicted_valence": pred_v,
            "predicted_arousal": pred_a,
            "distress_risk":     pred_v < DISTRESS_THRESHOLD,
            "escalation_risk":   velocity_v < ESCALATION_VELOCITY,
            "velocity_valence":  velocity_v,
            "confidence":        confidence
        }


# ── Singleton per user ─────────────────────────────────────────────────────────
_instances: dict[str, EmotionPredictor] = {}

def get_emotion_predictor(user_id: str) -> EmotionPredictor:
    if user_id not in _instances:
        _instances[user_id] = EmotionPredictor()
    return _instances[user_id]
