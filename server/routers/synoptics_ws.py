"""
Synoptics v2 WebSocket (Agents Swarm Visualize §238).

Delivers the documented `synoptics_update` frame contract to connected UI
clients (predictive ghost layer + anomaly overlay consumers):

    {
      "type": "synoptics_update",
      "timestamp": ...,
      "state":    [...],      # per-domain activations
      "prediction": [...],    # one-step velocity forecast (ghost layer)
      "anomalies":  [...],    # detected deviations (heatmap / shock waves)
      "features":   {...},    # density / entropy / avg_velocity
      "meta":       {"model_version": "synoptics-v2", "latency_ms": ...}
    }

`build_synoptics_frame(brain_state, latency_ms)` is the pure builder used by
brain_v2; the WebSocket endpoint just fans frames out to subscribers.
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# ── Connection manager ─────────────────────────────────────────────────────────
_subscribers: List[WebSocket] = []


@router.websocket("/ws/synoptics")
async def synoptics_websocket(ws: WebSocket):
    """Stream synoptics_update frames to a client (e.g. ghost/orbit overlay)."""
    await ws.accept()
    _subscribers.append(ws)
    try:
        while True:
            await ws.receive_text()  # keepalive / ping; ignore content
    except WebSocketDisconnect:
        if ws in _subscribers:
            _subscribers.remove(ws)
    except Exception:
        if ws in _subscribers:
            _subscribers.remove(ws)


async def broadcast_synoptics_frame(frame: Dict[str, Any]) -> None:
    """Push a prepared synoptics_update frame to all subscribers."""
    if not _subscribers:
        return
    payload = json.dumps(frame)
    dead = []
    for ws in list(_subscribers):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _subscribers:
            _subscribers.remove(ws)


def build_synoptics_frame(
    synoptic: Dict[str, Any],
    latency_ms: float = 0.0,
) -> Dict[str, Any]:
    """
    Build the §238 frame from a BrainState.synoptic dict.

    Maps existing keys: domains → state, predicted → prediction,
    anomalies → anomalies, trend → features. Never raises.
    """
    synoptic = synoptic or {}
    domains: Dict[str, float] = synoptic.get("domains", {}) or {}

    state = [
        {"id": k, "x": round(float(v) * 100, 2), "y": round(50.0, 2),
         "vx": round(float(synoptic.get("trend", {}).get(k, 0.0)) * 20, 2),
         "vy": round(0.0, 2)}
        for k, v in domains.items()
    ]

    prediction = [
        {"id": k, "x": round(float(v) * 100, 2), "y": round(50.0, 2),
         "confidence": round(min(1.0, max(0.5, abs(v))), 2)}
        for k, v in (synoptic.get("predicted", {}) or {}).items()
    ]

    anomalies = synoptic.get("anomalies", []) or []
    if isinstance(anomalies, list):
        anomalies = [a for a in anomalies if isinstance(a, dict)]

    trend = synoptic.get("trend", {}) or {}
    vals = list(trend.values())
    features = {
        "density": len(domains),
        "entropy": round(float(__entropy(domains)), 4),
        "avg_velocity": round(float(sum(abs(v) for v in vals)) / max(1, len(vals)), 4),
    }

    # New cognition/causal/desktop/skills layers (§36-50 additions) ride along
    # so the dashboard can render focus, ghost-cause links, and desktop state.
    meta = {
        "model_version": "synoptics-v2",
        "latency_ms": round(latency_ms, 1),
    }
    cognition = synoptic.get("cognition") or {}
    causal = synoptic.get("causal") or {}
    desktop = synoptic.get("desktop") or {}
    user_model = synoptic.get("user_model") or {}
    skills = synoptic.get("skills") or {}
    if cognition:
        meta["focus"] = cognition.get("focus")
    if causal:
        meta["stability"] = causal.get("stability")
    if desktop:
        meta["active_app"] = desktop.get("active_app")
    if user_model:
        meta["habits"] = len(user_model.get("habits", []))
    if skills:
        meta["skills"] = skills.get("registered", [])

    return {
        "type": "synoptics_update",
        "timestamp": time.time(),
        "state": state,
        "prediction": prediction,
        "anomalies": anomalies,
        "features": features,
        "cognition": cognition,
        "causal": causal,
        "causal_learned": synoptic.get("causal_learned"),
        "strategic": synoptic.get("strategic"),
        "desktop": desktop,
        "user_model": user_model,
        "goal": synoptic.get("goal"),
        "plan": synoptic.get("plan"),
        "hierarchical_goals": synoptic.get("hierarchical_goals", []),
        "hierarchical_plan": synoptic.get("hierarchical_plan"),
        "arcs": synoptic.get("arcs", []),
        "task_plan": synoptic.get("task_plan"),
        "executor": synoptic.get("executor"),
        "last_plan_action": synoptic.get("last_plan_action"),
        "swarm_stability": synoptic.get("swarm_stability"),
        "narrative_drift": synoptic.get("narrative_drift"),
        "intent": synoptic.get("intent"),
        "gnn": synoptic.get("gnn"),
        "prediction_g": synoptic.get("prediction"),
        "prediction_metrics": synoptic.get("prediction_metrics"),
        "predicted_trajectory": synoptic.get("predicted_trajectory"),
        "selected_action": synoptic.get("selected_action"),
        "rl_style": synoptic.get("rl_style"),
        "social_action": synoptic.get("social_action"),
        "proactive_alerts": synoptic.get("proactive_alerts"),
        "society": synoptic.get("society"),
        "reused_plan": synoptic.get("reused_plan"),
        "recovery": synoptic.get("recovery"),
        "trend_meta": synoptic.get("trend_meta", {}),
        "meta": meta,
    }


def __entropy(domains: Dict[str, float]) -> float:
    import math
    vals = [abs(float(v)) for v in domains.values()]
    total = sum(vals)
    if total <= 0:
        return 0.0
    probs = [v / total for v in vals]
    return -sum(p * math.log(p) for p in probs if p > 0)
