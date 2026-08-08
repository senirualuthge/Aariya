"""
Dashboard WebSocket — /ws/dashboard/stream

Mirrors the AI Brain state at ~100 ms intervals to connected clients:
  - swarm_activations : list of active agent IDs + states
  - brain_logs        : last N brain activity log entries
  - metrics snapshot  : reward history from MetricsTracker

Uses the redis_bus swarm channel and the AgentRegistry for live agent data.
Falls back gracefully when neither Redis nor agent data is available.
"""
import asyncio
import json
import time
from collections import deque
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.infrastructure.observability import logger
from server.infrastructure.session_manager import manager
from server.systems.agent.mobile_dashboard_agent import get_mobile_dashboard

router = APIRouter()

# ── Shared ring buffer for recent brain log lines ─────────────────────────────
_brain_log_ring: deque[str] = deque(maxlen=20)


def push_brain_log(line: str) -> None:
    """Call from any server module to append a log line to the dashboard ring."""
    _brain_log_ring.appendleft(line)


# ── Swarm snapshot helpers ────────────────────────────────────────────────────
def _get_swarm_activations() -> list[dict[str, Any]]:
    """Return agent status list from AgentRegistry (best-effort)."""
    try:
        from server.infrastructure.agent_registry import AgentRegistry  # type: ignore
        registry = AgentRegistry()
        return [
            {
                "id": a.get("name", a.get("id", "unknown")),
                "status": a.get("status", "active"),
                "type": a.get("type", "agent"),
            }
            for a in registry.get_active_agents()[:30]  # cap at 30 nodes
        ]
    except Exception:
        return []


def _get_metrics_snapshot() -> dict[str, Any]:
    """Pull latest MetricsTracker snapshot (best-effort)."""
    try:
        from server.routers.metrics_ws import get_metrics_tracker  # type: ignore
        return get_metrics_tracker().snapshot()
    except Exception:
        return {}


def _build_payload() -> dict[str, Any]:
    return {
        "type": "dashboard.update",
        "swarm_activations": _get_swarm_activations(),
        "brain_logs": list(_brain_log_ring),
        "metrics": _get_metrics_snapshot(),
    }


# ── WebSocket endpoint ─────────────────────────────────────────────────────────
@router.websocket("/ws/dashboard/stream")
async def dashboard_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    manager.dashboard_clients.add(websocket)
    agent = get_mobile_dashboard()
    agent.on_client_connected()
    logger.info("Dashboard Stream client connected")

    try:
        # Send initial snapshot immediately on connect
        await websocket.send_json(_build_payload())

        while True:
            t0 = time.monotonic()
            await asyncio.sleep(0.1)  # 10 Hz refresh
            await websocket.send_json(_build_payload())
            agent.on_payload_sent()
            agent.record_latency((time.monotonic() - t0) * 1000)

    except WebSocketDisconnect:
        logger.info("Dashboard Stream client disconnected")
    except Exception as exc:
        logger.error(f"Dashboard Stream WebSocket error: {exc}")
    finally:
        manager.dashboard_clients.discard(websocket)
        agent.on_client_disconnected()
