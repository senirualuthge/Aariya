"""
Dashboard stream helpers.

The live /ws/dashboard/stream WebSocket lives in server/main.py
(_run_cognitive_loop — it handles chat frames, file-access telemetry, and
state updates). This module deliberately defines NO routes: it only provides
the shared snapshot helpers that /ws/mobile/analytics reuses plus the
brain-log ring that server-side activity feeds.
"""
import asyncio
import json
import time
from collections import deque
from typing import Any

from server.infrastructure.observability import logger
from server.infrastructure.session_manager import manager
from server.systems.agent.mobile_dashboard_agent import get_mobile_dashboard

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

