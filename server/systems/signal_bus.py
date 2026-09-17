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


async def emit_real_event(source: str, severity: str, title: str,
                         payload: Optional[Dict[str, Any]] = None) -> None:
    """
    Push a REAL event into the dashboard Event Log (no synthetic data).

    Shared by every background system (autonomy daemon, evolution loop) that
    needs to surface a genuine action to the dashboard's Event Log without
    reaching into the bus internals. Best-effort: a missing bus / dead socket
    never breaks the caller's tick.

    Args:
        source:   event source tag — becomes the log chip (e.g. "DAEMON",
                  "PLANNER", "LEARNING", "MODEL", "EVOLUTION", "BRAIN").
        severity: "info" | "warn" | "critical" (frontend colors by this).
        title:    human-readable event text shown in the log.
        payload:  optional extra fields (surfaced in the signal object).
    """
    try:
        await bus.emit_signal(
            "telemetry",
            severity,
            source,
            {"title": title, **(payload or {})},
        )
    except Exception as exc:  # pragma: no cover — best-effort by design
        logging.getLogger("Aariya.SignalBus").debug(
            "event log emission skipped: %s", exc
        )
