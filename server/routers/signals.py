from fastapi import APIRouter, Depends, Request, HTTPException
from typing import Optional, Literal, List
from server.infrastructure.signal_bus import Signal, get_signal_bus, SignalBus
from server.db import get_db_connection
import json

router = APIRouter(prefix="/ingest", tags=["ingest"])

@router.post("/signal")
async def ingest_signal(signal: Signal, bus: SignalBus = Depends(get_signal_bus)):
    """
    Ingest a new signal from an external client (mobile, desktop, web).
    """
    try:
        await bus.emit(signal)
        return {"ok": True, "id": signal.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/signals", response_model=List[dict])
async def get_signals(limit: int = 100, offset: int = 0):
    """
    Get historical signals from the database.
    """
    conn = get_db_connection()
    try:
        cur = conn.execute("""
            SELECT * FROM signals 
            ORDER BY timestamp DESC 
            LIMIT ? OFFSET ?
        """, (limit, offset))
        rows = cur.fetchall()
        
        results = []
        for row in rows:
            d = dict(row)
            # Reconstruct nested objects (source, context, payload)
            # For simplicity, we just parse the payload JSON
            d["payload"] = json.loads(d["payload"])
            # In a full TypeScript-like implementation, we'd reconstruct source/context too
            results.append(d)
        
        return results
    finally:
        conn.close()

@router.post("/device")
async def register_device(device_id: str, user_id: str, platform: str, model: str, os_version: str, app_version: str):
    """
    Track or update a device connecting to the system.
    """
    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO devices (device_id, user_id, platform, model, os_version, app_version)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                user_id = excluded.user_id,
                os_version = excluded.os_version,
                app_version = excluded.app_version,
                last_seen = CURRENT_TIMESTAMP
        """, (device_id, user_id, platform, model, os_version, app_version))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
