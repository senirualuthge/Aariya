"""Uncertainty scoring (NEWPredictionPRT2 §"Meta-Policy" / meta_policy/uncertainty.py).

    class Uncertainty:
        def score(self, forecast):
            return forecast.uncertainty + (1 - max(forecast.up, forecast.down, forecast.neutral))
"""

from typing import Any, Dict


class Uncertainty:
    """Scores how uncertain a forecast is: raw model uncertainty plus how
    spread the direction mass is. A forecast that can't commit to a direction
    (up/down/neutral all low) scores high — the engine should not act on it."""

    def score(self, forecast: Dict[str, Any]) -> float:
        uncertainty = float(forecast.get("uncertainty", 0.0))
        up = float(forecast.get("up", 0.0))
        down = float(forecast.get("down", 0.0))
        neutral = float(forecast.get("neutral", 0.0))
        return max(0.0, min(1.0, uncertainty + (1.0 - max(up, down, neutral))))

    def state(self, forecast: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "score": round(self.score(forecast), 3),
            "components": {
                "uncertainty": float(forecast.get("uncertainty", 0.0)),
                "direction_mass": round(max(float(forecast.get("up", 0.0)),
                                            float(forecast.get("down", 0.0)),
                                            float(forecast.get("neutral", 0.0))), 3),
            },
        }
