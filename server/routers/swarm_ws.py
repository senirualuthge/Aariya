# server/routers/swarm_ws.py
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.infrastructure.redis_manager import get_redis

logger = logging.getLogger("aariya.swarm_ws")
router = APIRouter(prefix="/api/swarm", tags=["Swarm Events"])

# Track active WebSocket connections
clients = set()

CHANNEL = "swarm_events"

@router.websocket("/ws")
async def swarm_websocket_endpoint(ws: WebSocket):
    """
    WebSocket endpoint serving real-time events from the Swarm Kernel.
    Connected clients (like the 3D Neural UI) will receive AGENT_UPDATE and AGENT_EVOLVED pulses.
    """
    await ws.accept()
    clients.add(ws)
    
    redis_mgr = get_redis()
    
    # If no Redis is available, fallback and just keep connection alive
    if redis_mgr.use_fallback or not redis_mgr.client:
        logger.warning("Swarm WS connected, but Redis is offline. No live events will be broadcast.")
        try:
            while True:
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            clients.remove(ws)
            return

    pubsub = redis_mgr.client.pubsub()  # type: ignore[union-attr]
    pubsub.subscribe(CHANNEL)
    
    try:
        while True:
            # Check for messages using pubsub
            # We use non-blocking sleeps so the async loop isn't locked by redis.
            # In a heavy production system async-redis (aioredis) is preferred.
            message = pubsub.get_message(ignore_subscribe_messages=True)
            
            if message:
                await ws.send_text(message["data"])
                
            await asyncio.sleep(0.01)
            
    except WebSocketDisconnect:
        logger.info("Swarm WS client disconnected.")
    except Exception as e:
        logger.error(f"Swarm WS error: {e}")
    finally:
        clients.discard(ws)
        pubsub.unsubscribe(CHANNEL)
        pubsub.close()
