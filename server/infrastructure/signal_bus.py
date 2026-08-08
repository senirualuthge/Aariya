import time
from typing import List, Dict, Any

class SignalBus:
    def __init__(self):
        self.history: List[Dict[str, Any]] = []

    def emit(self, stype: str, payload: Dict[str, Any], severity: str = "info"):
        signal = {
            "id": str(time.time_ns()),
            "type": stype,
            "severity": severity,
            "timestamp": time.time(),
            "payload": payload
        }
        self.history.append(signal)
        # In real system, this would publish to Redis/NATS