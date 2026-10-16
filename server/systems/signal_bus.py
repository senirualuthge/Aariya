import time
import uuid
import logging
import collections
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


# ── News alerts (typed projection of the ingest stream) ───────────────────────
# BrainV2 grounds its context in REAL world events that pulse-news ingested —
# nothing is ever fabricated into this feed. Bounded ring, newest last.
NEWS_FEED_MAXLEN = 50
news_alerts: "collections.deque[Dict[str, Any]]" = collections.deque(maxlen=NEWS_FEED_MAXLEN)


def record_news_alert(alert: Dict[str, Any]) -> Dict[str, Any]:
    """Store one real news alert (validated at the ingest boundary).

    Missing fields normalise to neutral values; the headline is required, so an
    alert without one is returned but NOT stored — we never invent a story.
    """
    entry = {
        "headline": str(alert.get("headline", "")).strip(),
        "summary": str(alert.get("summary", "")).strip(),
        "importance": float(alert.get("importance", 0.0) or 0.0),
        "category": str(alert.get("category", "general") or "general"),
        "topics": [str(t).strip() for t in (alert.get("topics") or []) if str(t).strip()],
        "url": str(alert.get("url", "") or ""),
        "ts": float(alert.get("ts") or time.time()),
        "received_at": time.time(),
    }
    if entry["headline"]:
        news_alerts.append(entry)
    return entry


def recent_news_alerts(max_age_seconds: float = 3600.0,
                       min_importance: float = 0.0) -> list:
    """Real alerts newer than `max_age_seconds` at/above `min_importance`,
    newest first. Pure read — unknown values are not defaulted into existence."""
    now = time.time()
    fresh = [
        a for a in news_alerts
        if now - float(a.get("received_at", a.get("ts", 0.0))) <= max_age_seconds
        and float(a.get("importance", 0.0)) >= min_importance
    ]
    fresh.sort(key=lambda a: float(a.get("ts", 0.0)), reverse=True)
    return fresh
