"""Process-local registry of live, authenticated device WebSockets.

Patch 1 enforces one Uvicorn worker, so a process-local registry is sufficient
for immediate revocation. Connections are keyed by the server-side device id
from the authenticated principal — never by a client-supplied id.

The registry lock and the revoked check in ``register`` close the race where a
ticket is redeemed just before revocation and the socket tries to register just
after it: registration either sees the revocation and refuses, or revoke sees
the registered socket and closes it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from typing import Dict, List, Set

from fastapi import WebSocket

from server.db import get_db_connection

logger = logging.getLogger("aariya.security.device_connections")

CLOSE_DEVICE_REVOKED = 4001


class DeviceConnectionRegistry:
    def __init__(self) -> None:
        # Weak references avoid an unregister hook in every WebSocket handler;
        # a live endpoint keeps its socket strongly referenced while connected.
        self._connections: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _device_is_active(device_id: str) -> bool:
        """Read revoked_at inside the registry lock (fail closed on DB error)."""
        if not device_id:
            return False
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT revoked_at FROM aariya_personal_devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            return row is not None and row["revoked_at"] is None
        except Exception as exc:  # noqa: BLE001 - fail closed on any storage error
            logger.warning("Device registry lookup failed: %s", exc)
            return False
        finally:
            conn.close()

    async def register(self, device_id: str, websocket: WebSocket) -> bool:
        """Track a newly accepted socket; False if the device is revoked."""
        async with self._lock:
            if not self._device_is_active(device_id):
                return False
            bucket = self._connections.get(device_id)
            if bucket is None:
                bucket = weakref.WeakSet()
                self._connections[device_id] = bucket
            bucket.add(websocket)
            return True

    async def unregister(self, device_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            bucket = self._connections.get(device_id)
            if bucket is not None:
                bucket.discard(websocket)
                if not bucket:
                    self._connections.pop(device_id, None)

    async def disconnect_device(
        self,
        device_id: str,
        close_code: int = CLOSE_DEVICE_REVOKED,
        reason: str = "Device revoked",
    ) -> int:
        """Notify and close every live socket for one device."""
        async with self._lock:
            bucket = self._connections.pop(device_id, None)
            sockets: List[WebSocket] = list(bucket) if bucket is not None else []

        payload = json.dumps(
            {
                "type": "device.revoked",
                "reason": reason,
                "close_code": close_code,
            }
        )
        closed = 0
        for websocket in sockets:
            try:
                await websocket.send_text(payload)
            except Exception:
                pass
            try:
                await websocket.close(code=close_code, reason=reason)
                closed += 1
            except Exception:
                pass
        if closed:
            logger.info("Closed %d live socket(s) for revoked device %s", closed, device_id)
        return closed

    def count(self, device_id: str) -> int:
        bucket = self._connections.get(device_id)
        return len(bucket) if bucket is not None else 0

    def clear(self) -> None:
        self._connections.clear()


device_connections = DeviceConnectionRegistry()
