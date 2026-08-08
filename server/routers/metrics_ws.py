"""
Metrics WebSocket Router + MetricsTracker

Provides:
  /ws/brain_metrics  → streams neural_update events to the 3D dashboard
  MetricsTracker     → tracks per-turn reward and aggregates PPO learning curve
  broadcast_brain_metrics() → pushes state events from brain/main

Dashboard consumers receive two event types:
  { type: "neural_update", trust, valence, arousal, agent_activations }
  { type: "metrics_update", avg_reward, reward_history, total_turns, session_rewards }
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json
import asyncio
from collections import deque
from typing import Optional

router = APIRouter()

# ── Connection manager ─────────────────────────────────────────────────────────
connected_dashboards: list[WebSocket] = []


async def broadcast_brain_metrics(data: dict) -> None:
    """
    Push any data dict to all connected dashboard WebSocket clients.
    Called by brain_v2 / main.py after each cognitive turn.
    """
    dead = []
    for ws in connected_dashboards:
        try:
            await ws.send_text(json.dumps(data))
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in connected_dashboards:
            connected_dashboards.remove(ws)


@router.websocket("/ws/brain_metrics")
async def brain_metrics_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_dashboards.append(websocket)
    # Send current metrics snapshot immediately on connect
    snapshot = _tracker.snapshot()
    await websocket.send_text(json.dumps({"type": "metrics_update", **snapshot}))
    try:
        while True:
            # Bidirectional: GUI can send mode-change commands through this socket
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            # ── GUI → Mobile mood sync ────────────────────────────────────────
            if msg.get("type") == "override_mode":
                mode = msg.get("mode", "")
                from server.infrastructure.session_manager import manager
                await manager.broadcast_mobile(
                    json.dumps({"type": "override_mode", "mode": mode})
                )
    except WebSocketDisconnect:
        if websocket in connected_dashboards:
            connected_dashboards.remove(websocket)


# ── MetricsTracker ─────────────────────────────────────────────────────────────

class MetricsTracker:
    """
    Lightweight in-memory tracker for PPO learning curve metrics.
    Maintains a rolling window of per-turn reward values and exposes
    a snapshot that gets broadcast to the 3D dashboard after every turn.
    """

    MAX_HISTORY = 100   # rolling window length shown in reward curve

    def __init__(self):
        self._rewards:        deque[float] = deque(maxlen=self.MAX_HISTORY)
        self._total_turns:    int          = 0
        self._session_sum:    float        = 0.0
        self._positive_turns: int          = 0

    def record(self, reward: float) -> None:
        """Log a reward observation from the PPO after a turn."""
        self._rewards.append(round(reward, 4))
        self._total_turns    += 1
        self._session_sum    += reward
        if reward > 0:
            self._positive_turns += 1

    def snapshot(self) -> dict:
        """
        Returns a JSON-ready dict for dashboard consumption.
        Includes reward history array for the learning curve chart.
        """
        history = list(self._rewards)
        n = len(history)
        avg = (sum(history) / n) if n > 0 else 0.0
        positive_rate = (self._positive_turns / self._total_turns) if self._total_turns > 0 else 0.0

        return {
            "avg_reward":      round(avg, 4),
            "reward_history":  history,           # array → plotted as line chart
            "total_turns":     self._total_turns,
            "session_reward":  round(self._session_sum, 4),
            "positive_rate":   round(positive_rate, 4),
            "last_reward":     history[-1] if history else 0.0,
        }

    async def broadcast_snapshot(self) -> None:
        """Push current metrics snapshot to all connected dashboards."""
        payload = {"type": "metrics_update", **self.snapshot()}
        await broadcast_brain_metrics(payload)

    def reset_session(self) -> None:
        self._session_sum    = 0.0
        self._positive_turns = 0


# ── Global singleton ───────────────────────────────────────────────────────────
_tracker = MetricsTracker()

def get_metrics_tracker() -> MetricsTracker:
    return _tracker
