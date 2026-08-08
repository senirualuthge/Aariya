import logging

logger = logging.getLogger("aariya.self_heal.monitor")

class AnomalyMonitor:
    def __init__(self):
        self.metrics_history: list = []
        # Configurable thresholds — lower in tests to trip anomalies faster
        self.anomaly_threshold_latency: float   = 1500.0  # ms
        self.anomaly_threshold_error_rate: float = 0.05
        self.anomaly_threshold_confidence: float = 0.5
        self.anomaly_threshold_hallucination: float = 0.6

    def collect_signals(self, rag_trace: dict, system_metrics: dict):
        """
        Collect signals from the latest RAG trace and system CPU/Memory. 
        """
        rag_metrics = rag_trace.get("metrics", {})
        combined = {
            "latency": rag_metrics.get("total_latency", 0),
            "error_rate": system_metrics.get("error_rate", 0),
            "rag_confidence": rag_metrics.get("retrieval_confidence", 1.0),
            "cpu_usage": system_metrics.get("cpu", 0.5),
            "hallucination_risk": rag_metrics.get("hallucination_risk", 0.0)
        }
        self.metrics_history.append(combined)
        
        # Keep only recent history
        if len(self.metrics_history) > 100:
            self.metrics_history.pop(0)
            
        return combined

    def detect_anomalies(self, metrics: dict):
        """
        Threshold-based detection algorithm.
        """
        issues = []

        if metrics.get("error_rate", 0) > self.anomaly_threshold_error_rate:
            issues.append("HIGH_ERROR_RATE")

        if metrics.get("latency", 0) > self.anomaly_threshold_latency:
            issues.append("HIGH_LATENCY")

        if metrics.get("rag_confidence", 1.0) < self.anomaly_threshold_confidence:
            issues.append("RAG_DEGRADATION")

        if metrics.get("hallucination_risk", 0.0) > self.anomaly_threshold_hallucination:
            issues.append("HIGH_HALLUCINATION_RISK")

        if issues:
            logger.warning(f"Self-Healing Monitor detected anomalies: {issues}")

        return issues
