"""
Analytics WebSocket — /ws/mobile/analytics

Streams real-time system + brain metrics every second:
  - CPU / RAM / thread count (psutil)
  - Trust score   (brain_v2.trust_sys)
  - Emotion state  (brain_v2.emotion_sys)
  - Active agent list with name / kind / status (agent_registry)

Falls back gracefully when brain is not yet running.
"""
import asyncio
import json
import time

import psutil
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from server.infrastructure.observability import logger
from server.infrastructure.session_manager import manager
from server.systems.agent.mobile_analytics_agent import get_mobile_analytics
from server.systems.security.auth import verify_ws_token

router = APIRouter()


# ── System stats ───────────────────────────────────────────────────────────────
def _get_system_stats() -> dict:
    vm = psutil.virtual_memory()
    return {
        "cpu": round(psutil.cpu_percent(interval=None), 1),
        "ram": round(vm.percent, 1),
        "ram_used_gb": round(vm.used / (1024 ** 3), 2),
        "ram_total_gb": round(vm.total / (1024 ** 3), 2),
        "threads": psutil.cpu_count(logical=True),
    }


# ── Brain snapshot (best-effort — returns defaults when brain not running) ─────
def _get_brain_snapshot() -> dict:
    trust = 0.5
    emotion_state = "neutral"

    try:
        from server.systems.brain_v2 import _registry  # type: ignore[attr-defined]
        if _registry:
            brain = next(iter(_registry.values()))
            trust_sys = getattr(brain, "trust_sys", None)
            if trust_sys is not None:
                get_state = getattr(trust_sys, "get_state", None)
                if callable(get_state):
                    state = get_state("user_default")
                    if isinstance(state, dict):
                        trust = state.get("trust", 0.5)  # type: ignore[assignment]
            emotion_state = getattr(brain, "_last_emotion", "neutral")
    except Exception as exc:
        logger.debug(f"[AnalyticsWS] brain state read failed: {exc}")

    # Pull full agent list from AgentRegistry
    agents_list: list[dict] = []
    try:
        from server.infrastructure.agent_registry import AgentRegistry
        registry = AgentRegistry()
        active = registry.get_active_agents()
        for a in active:
            agents_list.append({
                "name": a.get("name", "Unknown"),
                "kind": a.get("kind", "unknown"),
                "status": a.get("status", "existing"),
                "first_seen": a.get("first_seen", ""),
            })
    except Exception as exc:
        logger.debug(f"[AnalyticsWS] agent registry read failed: {exc}")

    return {
        "trust": round(trust, 3),
        "emotion": emotion_state,
        "agents_active": len(agents_list),
        "agents": agents_list,
    }


# ── WebSocket endpoint ─────────────────────────────────────────────────────────
@router.websocket("/ws/mobile/analytics")
async def analytics_ws(websocket: WebSocket) -> None:
    if not await verify_ws_token(websocket):
        return

    await websocket.accept()
    manager.analytics_clients.add(websocket)
    agent = get_mobile_analytics()
    agent.on_client_connected()
    logger.info("Mobile Analytics client connected")

    try:
        from server.routers.dashboard_ws import _get_swarm_activations, _get_metrics_snapshot, _brain_log_ring
    except ImportError:
        _get_swarm_activations = lambda: []
        _get_metrics_snapshot = lambda: {}
        _brain_log_ring = []

    try:
        while True:
            t0 = time.monotonic()
            stats = _get_system_stats()
            brain = _get_brain_snapshot()

            payload = {
                "type": "analytics",
                "server_ts": time.time(),   # epoch seconds — mobile computes RTT
                "swarm_activations": _get_swarm_activations(),
                "metrics": _get_metrics_snapshot(),
                "brain_logs": list(_brain_log_ring),
                **stats,
                **brain,
            }

            await websocket.send_json(payload)
            agent.on_payload_sent()
            agent.record_latency((time.monotonic() - t0) * 1000)
            await asyncio.sleep(1.0)

    except WebSocketDisconnect:
        logger.info("Mobile Analytics client disconnected")
    except Exception as exc:
        logger.error(f"Mobile Analytics WebSocket error: {exc}")
    finally:
        manager.analytics_clients.discard(websocket)
        agent.on_client_disconnected()
