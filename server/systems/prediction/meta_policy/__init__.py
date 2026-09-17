"""Meta-policy gate (NEWPredictionPRT2 §"Meta-Policy" / server/prediction/meta_policy).

When the forecast is too uncertain, risky, or contradictory, the engine must
NOT barrel ahead with the same confidence. Instead it returns a governed
decision: REQUEST_MORE_DATA / CAUTION / ABSTAIN / ACCEPT.

The doc's decision model:

    @dataclass
    class PolicyDecision:
        action: str
        confidence: float
        explanation: str

Components (mirroring the doc directory):
    uncertainty.py  → Uncertainty.score(forecast)
    conflict.py     → ConflictDetector.detect(patterns)
    risk.py         → RiskEngine.score(volatility, confidence)
    policy.py       → MetaPolicy.decide(forecast, memory, risk, conflict, uncertainty)

Example output:
    {"action": "CAUTION", "confidence": 0.58, "reason": "forecast uncertainty elevated"}
"""

from server.systems.prediction.meta_policy.decision import PolicyDecision
from server.systems.prediction.meta_policy.policy import MetaPolicy

__all__ = ["PolicyDecision", "MetaPolicy"]
