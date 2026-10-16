"""
Ingest Router — /ingest/* for external clients (mobile / desktop / web).

POST /ingest/signal   → validate, persist to the real `signals` table and
                        mirror onto the admin signal bus (dashboard Event Log).
GET  /ingest/signals  → persisted history, newest first.
POST /ingest/device   → upsert the device registry (`devices` table).
"""

import json
import time
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError

from server.db import get_db_connection
from server.infrastructure.signal_bus import Signal, get_signal_bus, IngestBus

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/signal")
async def ingest_signal(signal: Signal,
                        bus: IngestBus = Depends(get_signal_bus)):
    """Ingest a new signal from an external client."""
    try:
        await bus.emit(signal)
        return {"ok": True, "id": signal.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals", response_model=List[dict])
async def get_signals(limit: int = 100, offset: int = 0):
    """Historical signals from the database, newest first."""
    conn = get_db_connection()
    try:
        cur = conn.execute("""
            SELECT id, type, severity, source, payload, timestamp
            FROM signals
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """, (max(1, min(limit, 500)), max(0, offset)))
        results = []
        for row in cur.fetchall():
            d = dict(row)
            try:
                d["payload"] = json.loads(d["payload"])
            except (json.JSONDecodeError, TypeError):
                d["payload"] = {}
            results.append(d)
        return results
    finally:
        conn.close()


class DeviceRegistration(BaseModel):
    device_id: str
    user_id: str = "user_default"
    platform: str = "unknown"
    model: str = ""
    os_version: str = ""
    app_version: str = ""


@router.post("/device")
async def register_device(device: DeviceRegistration):
    """Track or update a device connecting to the system."""
    now = time.time()
    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO devices (device_id, user_id, platform, model,
                                 os_version, app_version, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                user_id = excluded.user_id,
                platform = excluded.platform,
                model = excluded.model,
                os_version = excluded.os_version,
                app_version = excluded.app_version,
                last_seen = excluded.last_seen
        """, (device.device_id, device.user_id, device.platform, device.model,
              device.os_version, device.app_version, now, now))
        conn.commit()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ── /api/signals/ingest — external alert contract (pulse-news + clients) ──────
# This is the path external producers (e.g. pulse-news' aigirl_bridge) actually
# POST to. It accepts a superset of the internal Signal model, validates a
# `news.alert` payload, and feeds the same IngestBus so alerts are persisted and
# mirrored onto the admin bus AND the typed news feed. Back-compat: older
# `system`-type payloads are still accepted unchanged.

api_signals_router = APIRouter(prefix="/api/signals", tags=["signals"])


class IngestSource(BaseModel):
    system: str = "external"
    file: str = ""
    function: str = ""


class NewsAlert(BaseModel):
    """Formal `news.alert` payload. `importance` is normalised to [0, 1]."""
    headline: str
    summary: str = ""
    importance: float = Field(default=0.0, ge=0.0, le=1.0)
    category: str = "general"
    topics: List[str] = Field(default_factory=list)
    url: str = ""
    ts: float = Field(default_factory=time.time)


class ExternalSignal(BaseModel):
    """Superset of the internal Signal accepted at /api/signals/ingest."""
    type: str = "system"
    severity: str = "info"
    source: IngestSource | str = "external"
    payload: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    context: Dict[str, Any] = Field(default_factory=dict)
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = Field(default_factory=time.time)


@api_signals_router.post("/ingest")
async def ingest_external_signal(sig: ExternalSignal,
                                 bus: IngestBus = Depends(get_signal_bus)):
    """Ingest an external signal. A malformed `news.alert` fails 422; a valid one
    is normalised and persisted (and reaches the news feed via the mirror)."""
    src = sig.source.system if isinstance(sig.source, IngestSource) else str(sig.source)

    if sig.type == "news.alert":
        try:
            alert = NewsAlert(**sig.payload)
        except ValidationError as ve:
            raise HTTPException(status_code=422, detail=ve.errors())
        if not alert.headline.strip():
            raise HTTPException(
                status_code=422,
                detail=[{"loc": ["payload", "headline"], "msg": "headline must be non-empty"}],
            )
        sig.payload = alert.model_dump()

    internal = Signal(
        id=sig.id, type=sig.type, severity=sig.severity,
        source=src, payload=sig.payload, timestamp=sig.timestamp,
    )
    await bus.emit(internal)
    return {"ok": True, "id": internal.id, "type": internal.type}
