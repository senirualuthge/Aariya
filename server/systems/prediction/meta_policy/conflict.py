"""Conflict detection (NEWPredictionPRT2 §"Meta-Policy" / meta_policy/conflict.py).

    class ConflictDetector:
        def detect(self, patterns):
            up, down = 0, 0
            for p in patterns:
                if p.direction == "up":  up += 1
                if p.direction == "down": down += 1
            return up > 0 and down > 0
"""

from typing import Any, Dict, List


class ConflictDetector:
    """Detects when independent signals disagree on direction — up AND down
    patterns exist simultaneously. Conflicting evidence ⇒ the model should
    abstain rather than force a confident forecast."""

    def detect(self, patterns: List[Dict[str, Any]]) -> bool:
        up = 0
        down = 0
        for p in patterns:
            direction = str(p.get("direction", "")).lower()
            if direction == "up":
                up += 1
            elif direction == "down":
                down += 1
        return up > 0 and down > 0

    def state(self, patterns: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "conflict": self.detect(patterns),
            "up_count": sum(1 for p in patterns if str(p.get("direction", "")).lower() == "up"),
            "down_count": sum(1 for p in patterns if str(p.get("direction", "")).lower() == "down"),
        }
