"""
Ingest Router — /ingest/* for external clients (mobile / desktop / web).

POST /ingest/signal   → validate, persist to the real `signals` table and
                        mirror onto the admin signal bus (dashboard Event Log).
GET  /ingest/signals  → persisted history, newest first.
POST /ingest/device   → upsert the device registry (`devices` table).
"""

import json
import time
from typing import List, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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
