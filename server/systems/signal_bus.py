import time
import uuid
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("Aariya.SignalBus")

class SignalBus:
    """
    Central observability emitter for Aariya GUI / Mobile dashboard.
    Converts logs, errors, and system states into formatted JSON signals.
    """
    def __init__(self):
        self.active_signals = []
        self._connected_sockets = []

    def set_sockets(self, sockets_list: list):
        self._connected_sockets = sockets_list

    async def emit_signal(self, signal_type: str, severity: str, source: str, payload: Dict[str, Any]):
        """
        Emits a structured JSON signal over all connected Admin dashboards.
        types: 'bug', 'error', 'telemetry', 'qos', 'anomaly'
        severity: 'info', 'medium', 'high', 'critical'
        """
        signal_obj = {
            "id": f"sig_{uuid.uuid4().hex[:8]}",
            "timestamp": time.time(),
            "type": signal_type,
            "severity": severity,
            "source": {"system": source},
            "status": "new",
            "payload": payload
        }
        
        self.active_signals.append(signal_obj)
        if len(self.active_signals) > 1000:
            self.active_signals.pop(0)

        # Broadcast via WebSocket
        message = {"type": "signal", "signal": signal_obj}
        dead_sockets = []
        
        for ws in self._connected_sockets:
            try:
                await ws.send_json(message)
            except Exception as e:
                dead_sockets.append(ws)

        for dead in dead_sockets:
            if dead in self._connected_sockets:
                self._connected_sockets.remove(dead)

# Global singleton
bus = SignalBus()

async def emit_test_signals():
    """Fires a burst of deterministic startup signals to populate the dashboard visually"""
    await bus.emit_signal(
        signal_type="qos", 
        severity="medium", 
        source="server.main.SignalBus",
        payload={"title": "Dashboard Connected", "description": "Admin UI successfully subscribed to unified observability."}
    )
    await bus.emit_signal(
        signal_type="telemetry", 
        severity="info", 
        source="core.AariyaBrain",
        payload={"title": "Models Loaded", "description": "Tensor engines loaded in 1.42s."}
    )
