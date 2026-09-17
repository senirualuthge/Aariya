"""
agents_router.py
────────────────
FastAPI router exposing the Agent Registry to the React frontend.

Endpoints:
  GET  /api/agents              — full registry snapshot
  GET  /api/agents/stats        — quick stats summary
  POST /api/agents/scan         — manual scan trigger
  POST /api/agents/{id}/ack     — acknowledge a "new" agent as "existing"
  POST /api/agents/ack-all      — acknowledge all new agents
  WS   /ws/agents               — real-time push of registry updates

Mount in main.py:
  from server.routers.agents_router import router as agents_router
  app.include_router(agents_router)
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import JSONResponse

from ..infrastructure.agent_watcher import get_watcher
from ..infrastructure.agent_registry import get_registry

logger = logging.getLogger("aariya.agents_router")
router = APIRouter(prefix="/api/agents", tags=["Agent Registry"])

# ── REST endpoints ────────────────────────────────────────────────────────────

@router.get("")
async def get_all_agents():
    """Return the full registry including status, detection method, etc."""
    registry = get_registry()
    return {
        "agents": registry.get_active_agents(),
        "stats": registry.stats(),
    }


@router.get("/stats")
async def get_stats():
    """Quick stats — used by dashboard counters."""
    return get_registry().stats()


@router.post("/scan")
async def manual_scan():
    """
    Trigger a manual scan immediately.
    Diff is also broadcast to all connected WebSocket clients.
    """
    watcher = get_watcher()
    diff = await asyncio.get_event_loop().run_in_executor(
        None, watcher.trigger_manual_scan
    )
    return {
        "message": "Scan complete",
        "diff": {
            "new": len(diff.get("new", [])),
            "updated": len(diff.get("updated", [])),
            "removed": len(diff.get("removed", [])),
        },
        "stats": get_registry().stats(),
    }


@router.post("/{agent_id}/ack")
async def acknowledge_agent(agent_id: str):
    """Mark a single 'new' agent as 'existing' after the UI has highlighted it."""
    registry = get_registry()
    # agent_id in URL may be URL-encoded — decode colon
    decoded_id = agent_id.replace("%3A", ":")
    success = registry.acknowledge_new(decoded_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Agent '{decoded_id}' not found")
    return {"acknowledged": decoded_id}


@router.post("/ack-all")
async def acknowledge_all():
    """Dismiss all 'new' badges in the visualization."""
    get_registry().acknowledge_all_new()
    return {"message": "All new agents acknowledged"}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def agent_registry_ws(websocket: WebSocket):
    """
    Real-time agent registry stream.

    On connect:  sends full snapshot immediately
    On change:   sends diff + updated agent list
    Client can send: {"action": "scan"} | {"action": "ack_all"} | {"action": "ack", "id": "..."}
    """
    await websocket.accept()
    watcher = get_watcher()
    registry = get_registry()

    # Create a send callback for the broadcaster
    async def send_update(payload: str):
        try:
            await websocket.send_text(payload)
        except Exception as exc:
            logger.debug("[AgentsRouter] broadcast send failed: %s", exc)

    watcher.broadcaster.register(send_update)

    # Send initial full snapshot
    try:
        await websocket.send_text(json.dumps({
            "type": "agent_registry_snapshot",
            "agents": registry.get_active_agents(),
            "stats": registry.stats(),
        }))

        # Listen for client messages — timeout triggers a keepalive ping every 20 s
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
                msg = json.loads(raw)
                action = msg.get("action")

                if action == "scan":
                    diff = await asyncio.get_event_loop().run_in_executor(
                        None, watcher.trigger_manual_scan
                    )
                    await websocket.send_text(json.dumps({
                        "type": "scan_result",
                        "diff": diff,
                        "stats": registry.stats(),
                    }))

                elif action == "ack_all":
                    registry.acknowledge_all_new()
                    await websocket.send_text(json.dumps({"type": "ack_all_done"}))

                elif action == "ack" and "id" in msg:
                    registry.acknowledge_new(msg["id"])
                    await websocket.send_text(json.dumps({
                        "type": "ack_done",
                        "id": msg["id"],
                    }))

                elif action == "pong":
                    # Client heartbeat response — connection is alive, do nothing
                    pass

            except asyncio.TimeoutError:
                # No message in 20 s — send a ping to keep the connection alive
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    # Socket is dead — break out and let finally unregister the client
                    break

    except WebSocketDisconnect:
        logger.debug("[agents_router] WebSocket client disconnected")
    finally:
        watcher.broadcaster.unregister(send_update)


# ── Lifespan helper (call from main.py) ───────────────────────────────────────

def setup_agent_watcher(app, project_root: str = "."):
    """
    Call this in your FastAPI app setup to wire the watcher into the lifespan.

    Example in main.py:
        from server.routers.agents_router import setup_agent_watcher
        setup_agent_watcher(app, project_root="/path/to/project")
    """
    from contextlib import asynccontextmanager

    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan_with_watcher(app):
        watcher = get_watcher(root=project_root)
        loop = asyncio.get_event_loop()
        watcher.start(loop)
        try:
            if original_lifespan:
                async with original_lifespan(app):
                    yield
            else:
                yield
        finally:
            watcher.stop()

    app.router.lifespan_context = lifespan_with_watcher
