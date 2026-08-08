import logging
import asyncio
from typing import Optional
from server.systems.self_heal.monitor import AnomalyMonitor
from server.systems.self_heal.diagnosis import DiagnosisEngine
from server.systems.self_heal.action import ActionEngine

logger = logging.getLogger("aariya.self_heal.loop")

class SelfHealingEngine:
    """
    Coordinates the autonomous Detect -> Diagnose -> Act -> Verify loop.
    """
    def __init__(self):
        self.monitor = AnomalyMonitor()
        self.diagnosis = DiagnosisEngine()
        self.action_engine = ActionEngine()
        self.last_metrics = None
        self.last_action_taken = None

    async def ingest_and_evaluate(self, rag_trace: dict):
        """
        To be called whenever a new RAG query completes.
        """
        # 1. Detect
        # We simulate system metrics here since we don't have PromQL in this local instance
        system_metrics = {"error_rate": 0.0, "cpu": 0.4} 
        
        current_metrics = self.monitor.collect_signals(rag_trace, system_metrics)
        anomalies = self.monitor.detect_anomalies(current_metrics)

        # 4. Verify previous action (if any)
        if self.last_action_taken and self.last_action_taken != "none" and self.last_metrics is not None:
            self.action_engine.verify(self.last_action_taken, self.last_metrics, current_metrics)
            self.last_action_taken = None

        if not anomalies:
            self.last_metrics = current_metrics
            return {"status": "healthy", "anomalies": []}

        # 2. Diagnose
        root_causes = self.diagnosis.diagnose(anomalies, current_metrics)
        logger.warning(f"[Self-Healing] Diagnosed Causes: {root_causes}")

        # 3. Act
        actions = []
        for cause in root_causes:
            action = self.action_engine.execute_action(cause)
            actions.append(action)
            # Track the latest action to verify on the next ingest
            if action != "none":
                self.last_action_taken = action
                
        self.last_metrics = current_metrics
        
        return {
            "status": "healing_engaged",
            "anomalies": anomalies,
            "root_causes": root_causes,
            "actions_taken": actions
        }

# Singleton instance
engine = SelfHealingEngine()

def get_healing_engine() -> SelfHealingEngine:
    return engine
