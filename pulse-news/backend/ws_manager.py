from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Set

from fastapi import WebSocket

logger = logging.getLogger("pulse.ws")

_HEARTBEAT_INTERVAL = 30
_BROADCAST_DEDUP_WINDOW = 300


class ConnectionManager:
    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._last_broadcast: Dict[str, float] = {}
        self._heartbeat_task: asyncio.Task | None = None
        self._running = False

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)
        logger.info("[WS] Client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)
        logger.info("[WS] Client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, message: Dict[str, Any]):
        dedup_key = message.get("id") or message.get("article_id") or message.get("title", "")
        now = time.time()
        if dedup_key:
            last = self._last_broadcast.get(dedup_key, 0)
            if now - last < _BROADCAST_DEDUP_WINDOW:
                return
            self._last_broadcast[dedup_key] = now

        payload = json.dumps(message, default=str)
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._connections.discard(ws)

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            stale: list[WebSocket] = []
            for ws in self._connections:
                try:
                    await ws.send_text('{"type":"ping"}')
                except Exception:
                    stale.append(ws)
            for ws in stale:
                self._connections.discard(ws)
            if stale:
                logger.info("[WS] Heartbeat cleaned %d stale connections", len(stale))

    def start_heartbeat(self):
        if self._heartbeat_task and not self._heartbeat_task.done():
            return
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        logger.info("[WS] Heartbeat started (every %ds)", _HEARTBEAT_INTERVAL)

    def stop_heartbeat(self):
        self._running = False
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    @property
    def count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()
