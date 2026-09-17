"""
Infrastructure signal bus — external telemetry ingest.

Two cooperating pieces:

1. `SignalBus` (sync, used by main.py's cognitive loop): records session /
   response events AND mirrors each one onto the admin signal bus
   (`server.systems.signal_bus.bus`) so they surface in the dashboard Event
   Log instead of vanishing into an unread list.

2. `Signal` + `get_signal_bus()` (async, used by /ingest/*): a validated
   ingest model and a singleton bus that persists signals to SQLite, mirrors
   them onto the admin bus, and keeps an in-memory history for quick reads.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List

from pydantic import BaseModel, Field

logger = logging.getLogger("aariya.infra.signals")


def _mirror_to_admin(stype: str, severity: str, source: str,
                     payload: Dict[str, Any]) -> None:
    """Best-effort forward onto the admin signal bus. Never raises; works
    from both loop and non-loop contexts."""
    try:
        from server.systems.signal_bus import emit_real_event
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(emit_real_event(
                source[:12].upper() or "INGEST", severity,
                f"{stype}: {json.dumps(payload)[:120]}", payload))
        except RuntimeError:
            # No loop in this thread — record without the live broadcast.
            from server.systems.signal_bus import bus as admin_bus
            admin_bus.active_signals.append({
                "id": f"sig_{uuid.uuid4().hex[:8]}",
                "timestamp": time.time(),
                "type": "telemetry",
                "severity": severity,
                "source": {"system": source},
                "status": "new",
                "payload": {"title": f"{stype}: {json.dumps(payload)[:120]}",
                            **payload},
            })
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[infra-signals] mirror failed: %s", exc)


class SignalBus:
    def __init__(self):
        self.history: List[Dict[str, Any]] = []

    def emit(self, stype: str, payload: Dict[str, Any],
             severity: str = "info"):
        signal = {
            "id": str(time.time_ns()),
            "type": stype,
            "severity": severity,
            "timestamp": time.time(),
            "payload": payload,
        }
        self.history.append(signal)
        if len(self.history) > 1000:
            self.history.pop(0)
        _mirror_to_admin(stype, severity, "cognitive-loop", payload)
        return signal


class Signal(BaseModel):
    """One externally ingested telemetry event."""
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    type: str
    severity: str = "info"
    source: str = "external"
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)


class IngestBus:
    """Receives /ingest/signal traffic: persist → mirror → remember."""

    def __init__(self):
        self.history: List[Dict[str, Any]] = []
        self._db_ready = False

    def _ensure_table(self):
        if self._db_ready:
            return
        from server.db import get_db_connection
        conn = get_db_connection()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                severity TEXT DEFAULT 'info',
                source TEXT DEFAULT 'external',
                payload TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        self._db_ready = True

    def persist(self, signal: Signal) -> None:
        """Synchronously write one signal to SQLite (table auto-created)."""
        self._ensure_table()
        from server.db import get_db_connection
        conn = get_db_connection()
        conn.execute(
            "INSERT OR REPLACE INTO signals "
            "(id, type, severity, source, payload, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (signal.id, signal.type, signal.severity, signal.source,
             json.dumps(signal.payload), signal.timestamp))
        conn.commit()
        conn.close()

    def record(self, signal: Signal) -> None:
        """Remember in-memory history and mirror onto the admin bus."""
        entry = signal.model_dump()
        self.history.append(entry)
        if len(self.history) > 1000:
            self.history.pop(0)

        _mirror_to_admin(signal.type, signal.severity, signal.source,
                         signal.payload)

    async def emit(self, signal: Signal) -> None:
        self.persist(signal)
        self.record(signal)


_ingest_bus: IngestBus | None = None


def get_signal_bus() -> IngestBus:
    global _ingest_bus
    if _ingest_bus is None:
        _ingest_bus = IngestBus()
    return _ingest_bus
