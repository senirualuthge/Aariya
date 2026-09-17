"""Risk evaluation (NEWPredictionPRT2 §"Meta-Policy" / meta_policy/risk.py).

    class RiskEngine:
        def score(self, volatility, confidence):
            return volatility * (1 - confidence)
"""

from typing import Any, Dict


class RiskEngine:
    """Scores risk as volatility scaled by model doubt. High volatility alone
    is fine when confidence is high; it becomes risky when the model is unsure
    (low confidence) of a volatile situation."""

    def score(self, volatility: float, confidence: float) -> float:
        return max(0.0, min(1.0, float(volatility) * (1.0 - float(confidence))))

    def state(self, volatility: float, confidence: float) -> Dict[str, Any]:
        return {
            "score": round(self.score(volatility, confidence), 3),
            "volatility": round(float(volatility), 3),
            "confidence": round(float(confidence), 3),
        }
