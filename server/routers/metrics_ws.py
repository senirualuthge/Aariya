"""
Metrics WebSocket helpers + MetricsTracker

  broadcast_brain_metrics() → pushes a data dict to every /ws/brain_metrics client
  MetricsTracker             → tracks per-turn reward and aggregates PPO learning curve

The live /ws/brain_metrics endpoint lives in server/main.py
(websocket_brain_metrics); it registers each connection with the admin signal
bus (server.systems.signal_bus.bus._connected_sockets).

This module previously defined its OWN duplicate /ws/brain_metrics route plus a
private `connected_dashboards` list — but the router was never mounted, so the
list stayed empty and every broadcast_brain_metrics() call (from
system_health, the mobile telemetry agents, MetricsTracker) was silently
dropped. The duplicate route and list are gone; broadcasts now fan out to the
real registry, the single source of truth for connected dashboard sockets.
"""

import json
from collections import deque
from typing import Optional

# ── Broadcast to the real /ws/brain_metrics registry ─────────────────────────
# server.main's /ws/brain_metrics handler registers / unregisters sockets here.
# There is deliberately NO parallel list in this module — a second registry is
# exactly the duplication that made these broadcasts dead.
def _metrics_sockets() -> list:
    try:
        from server.systems.signal_bus import bus as admin_signal_bus
        return admin_signal_bus._connected_sockets
    except Exception:
        return []


async def broadcast_brain_metrics(data: dict) -> None:
    """
    Push any data dict to all connected /ws/brain_metrics clients.

    Called by system_health, the mobile telemetry agents, and MetricsTracker.
    """
    payload = json.dumps(data)
    sockets = list(_metrics_sockets())
    dead = []
    for ws in sockets:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    if dead:
        try:
            from server.systems.signal_bus import bus as admin_signal_bus
            for ws in dead:
                if ws in admin_signal_bus._connected_sockets:
                    admin_signal_bus._connected_sockets.remove(ws)
        except Exception:
            pass


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
