import logging

logger = logging.getLogger("aariya.self_heal.diagnosis")

CAUSE_MAP = {
    "HIGH_LATENCY": ["cpu_pressure", "downstream_slow", "poor_retrieval_strategy"],
    "HIGH_ERROR_RATE": ["bad_deploy", "dependency_down"],
    "RAG_DEGRADATION": ["bad_strategy", "empty_index"],
    "HIGH_HALLUCINATION_RISK": ["bad_strategy", "insufficient_context"]
}

class DiagnosisEngine:
    def diagnose(self, issues: list, metrics: dict):
        """
        Maps observed symptoms to probable root causes based on validation heuristics.
        """
        root_causes = []
        for issue in issues:
            candidates = CAUSE_MAP.get(issue, [])
            for cause in candidates:
                if self._validate_cause(cause, metrics):
                    root_causes.append(cause)
                    
        return list(set(root_causes))

    def _validate_cause(self, cause: str, metrics: dict) -> bool:
        """
        Validates if a candidate cause is physically represented in the telemetry metrics.
        """
        if cause == "cpu_pressure":
            return metrics.get("cpu_usage", 0.0) > 0.9

        if cause == "poor_retrieval_strategy":
            return metrics.get("latency", 0) > 1500 and metrics.get("rag_confidence", 1.0) < 0.6
            
        if cause == "bad_strategy" or cause == "insufficient_context":
            return metrics.get("rag_confidence", 1.0) < 0.5 or metrics.get("hallucination_risk", 0.0) > 0.6
            
        # Default fallback to assume the cause is valid if we lack specific metric validators
        return True
