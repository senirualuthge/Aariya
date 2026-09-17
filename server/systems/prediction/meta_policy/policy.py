"""Meta-policy engine (NEWPredictionPRT2 §"Meta-Policy" / meta_policy/policy.py).

    class MetaPolicy:
        def decide(self, forecast, memory, risk, conflict, uncertainty):
            if uncertainty > 0.55:  return "REQUEST_MORE_DATA"
            if risk > 0.45:         return "CAUTION"
            if conflict:            return "ABSTAIN"
            return "ACCEPT"

The gate turns a bare forecast into a governed decision so the brain can say
"forecast withheld / requires more data" instead of confidently acting on a
weak signal. Defaults per input keep decide() safe when pieces are missing.
"""

import logging
from typing import Any, Dict, List, Optional

from server.systems.prediction.meta_policy.conflict import ConflictDetector
from server.systems.prediction.meta_policy.decision import PolicyDecision
from server.systems.prediction.meta_policy.risk import RiskEngine
from server.systems.prediction.meta_policy.uncertainty import Uncertainty

logger = logging.getLogger("aariya.meta_policy")

REQUEST_MORE_DATA = "REQUEST_MORE_DATA"
CAUTION = "CAUTION"
ABSTAIN = "ABSTAIN"
ACCEPT = "ACCEPT"


class MetaPolicy:
    def __init__(self, *, uncertainty_threshold: float = 0.55,
                 risk_threshold: float = 0.45):
        self.uncertainty_threshold = float(uncertainty_threshold)
        self.risk_threshold = float(risk_threshold)
        self.uncertainty = Uncertainty()
        self.risk = RiskEngine()
        self.conflict = ConflictDetector()

    def decide(self, forecast: Optional[Dict[str, Any]] = None, *,
               memory: Optional[List[Dict[str, Any]]] = None,
               risk: Optional[float] = None,
               conflict: Optional[bool] = None,
               uncertainty: Optional[float] = None) -> PolicyDecision:
        """Apply the gate. Returns the doc's PolicyDecision with an action,
        confidence and explanation (+ granular reasons for the UI)."""
        forecast = forecast or {}
        patterns = list(memory or forecast.get("patterns", []))
        unc = float(uncertainty) if uncertainty is not None else self.uncertainty.score(forecast)
        vol = float(forecast.get("volatility", 0.0))
        conf = float(forecast.get("confidence", 0.5))
        rsk = float(risk) if risk is not None else self.risk.score(vol, conf)
        has_conflict = bool(conflict) if conflict is not None else self.conflict.detect(patterns)

        reasons: List[str] = []
        if unc > self.uncertainty_threshold:
            reasons.append(f"forecast uncertainty elevated ({unc:.2f})")
        if rsk > self.risk_threshold:
            reasons.append(f"risk elevated (volatility {vol:.2f} × doubt {1 - conf:.2f})")
        if has_conflict:
            reasons.append("conflicting directional evidence")

        if unc > self.uncertainty_threshold:
            action = REQUEST_MORE_DATA
            confidence = max(0.05, min(0.7, 1.0 - unc))
        elif rsk > self.risk_threshold:
            action = CAUTION
            confidence = max(0.1, min(0.85, conf * (1.0 - rsk * 0.5)))
        elif has_conflict:
            action = ABSTAIN
            confidence = max(0.1, min(0.6, conf * 0.8))
        else:
            action = ACCEPT
            confidence = max(0.3, min(0.99, conf))

        if not reasons:
            reasons.append("forecast within governed bounds")
        explanation = "; ".join(reasons)
        logger.debug("[MetaPolicy] decide → %s (conf %.2f): %s", action, confidence, explanation)
        return PolicyDecision(action=action, confidence=round(confidence, 3),
                              explanation=explanation, reasons=reasons)

    def explain(self, forecast: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """decide() + full component breakdown, for the dashboard."""
        decision = self.decide(forecast, **kwargs)
        return {
            "decision": decision.to_dict(),
            "components": {
                "uncertainty": self.uncertainty.state(forecast or {}),
                "risk": self.risk.state(float((forecast or {}).get("volatility", 0.0)),
                                        float((forecast or {}).get("confidence", 0.5))),
                "conflict": self.conflict.state(list(kwargs.get("memory")
                                                    or (forecast or {}).get("patterns", []))),
            },
        }
