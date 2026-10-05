# server/routers/swarm_ws.py
"""
Swarm WebSocket — /api/swarm/ws

Streams real-time swarm events (AGENT_UPDATE / AGENT_EVOLVED) to connected
clients.  Uses a single global StreamSubscriber for the Redis channel instead
of one pub/sub subscription per WebSocket connection, so adding clients never
increases broker load.

When Redis is unavailable the subscriber falls back to the in-process ring
buffer in redis_bus — events are never silently dropped.
"""

import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.infrastructure.streaming import StreamSubscriber
from server.realtime.redis_bus import recent_events
from server.systems.security.auth import verify_ws_token

logger = logging.getLogger("aariya.swarm_ws")
router = APIRouter(prefix="/api/swarm", tags=["Swarm Events"])

CHANNEL = "swarm_events"

# ── Global subscriber (one Redis subscription for all WS clients) ────────────

_clients: set[WebSocket] = set()
_subscriber: StreamSubscriber | None = None
_listen_task: asyncio.Task | None = None


async def _fanout(payload: dict) -> None:
    """Send every connected WebSocket the serialised event."""
    text = json.dumps(payload)
    stale: list[WebSocket] = []
    for ws in list(_clients):
        try:
            await ws.send_text(text)
        except Exception:
            stale.append(ws)
    for ws in stale:
        _clients.discard(ws)


def _get_subscriber() -> StreamSubscriber:
    """Lazily create the shared subscriber and register the fan-out handler."""
    global _subscriber
    if _subscriber is None:
        _subscriber = StreamSubscriber(CHANNEL)
        _subscriber.add_handler(_fanout)
    return _subscriber


async def _ensure_listening() -> None:
    """Start the subscriber's Redis listener exactly once."""
    global _listen_task
    sub = _get_subscriber()
    if sub._running:
        return
    await sub.listen()
    # If Redis is available the subscriber started its own drain task.
    # If not, we poll the in-process ring buffer as a fallback.
    if not sub._running:
        _listen_task = asyncio.get_event_loop().create_task(_ring_poll_loop())


async def _ring_poll_loop() -> None:
    """Fallback: poll the in-process event ring when Redis is offline."""
    cursor = 0
    try:
        while True:
            for event in recent_events(since=cursor):
                cursor = max(cursor, event.get("seq", 0))
                await _fanout({"type": event["type"], "data": event["data"]})
            await asyncio.sleep(0.2)
    except asyncio.CancelledError:
        pass


# ── WebSocket endpoint ───────────────────────────────────────────────────────

@router.websocket("/ws")
async def swarm_websocket_endpoint(ws: WebSocket):
    """
    WebSocket endpoint serving real-time events from the Swarm Kernel.
    Connected clients (like the 3D Neural UI) receive AGENT_UPDATE and
    AGENT_EVOLVED pulses — live from Redis when available, otherwise from
    the in-process ring buffer.
    """
    if not await verify_ws_token(ws):
        return

    await ws.accept()
    _clients.add(ws)
    logger.info("Swarm WS client connected (%d total)", len(_clients))

    await _ensure_listening()

    try:
        # Keep the connection alive; events are pushed by the subscriber.
        while True:
            # Drain client messages (ping/pong, close frames) without acting
            # on them — the framework handles close internally.
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)
        logger.info("Swarm WS client disconnected (%d remaining)", len(_clients))
