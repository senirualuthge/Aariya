"""Meta-policy decision model (NEWPredictionPRT2 §"Meta-Policy").

    @dataclass
    class PolicyDecision:
        action: str
        confidence: float
        explanation: str
"""

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class PolicyDecision:
    action: str
    confidence: float
    explanation: str
    reasons: list = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "confidence": round(float(self.confidence), 3),
            "explanation": self.explanation,
            "reasons": list(self.reasons),
        }
