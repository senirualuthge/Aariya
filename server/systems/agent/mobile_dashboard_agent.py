"""
mobile_dashboard_agent.py
───────────────────────
Agent that tracks Mobile Dashboard WS connection load and telemetry streaming.
"""
from __future__ import annotations

import asyncio
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

from server.systems.agent.mobile_gateway_agent import BaseSwarmAgent, register_agent

logger = logging.getLogger("aariya.mobile_dashboard_agent")

@dataclass
class DashboardTelemetry:
    connected_clients: int = 0
    peak_clients: int = 0
    payloads_sent: int = 0
    payloads_per_second: float = 0.0
    avg_latency_ms: float = 0.0
    last_activity_ts: float = field(default_factory=time.time)
    uptime_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

@register_agent
class MobileDashboardAgent(BaseSwarmAgent):
    agent_id = "mobile_dashboard"
    description = "Manages and monitors the Dashboard WebSocket streaming load."

    def __init__(self) -> None:
        self._telemetry = DashboardTelemetry()
        self._start_time: float = time.time()
        self._tick_task: Optional[asyncio.Task] = None
        self._running = False
        self._payload_timestamps: list[float] = []
        self._cps_window_seconds = 10

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._start_time = time.time()
        self._tick_task = asyncio.ensure_future(self._tick_loop())
        logger.info("[MobileDashboardAgent] Started")

    def stop(self) -> None:
        self._running = False
        if self._tick_task and not self._tick_task.done():
            self._tick_task.cancel()
        logger.info("[MobileDashboardAgent] Stopped")

    def on_client_connected(self) -> None:
        self._telemetry.connected_clients += 1
        if self._telemetry.connected_clients > self._telemetry.peak_clients:
            self._telemetry.peak_clients = self._telemetry.connected_clients
        self._telemetry.last_activity_ts = time.time()

    def on_client_disconnected(self) -> None:
        self._telemetry.connected_clients = max(0, self._telemetry.connected_clients - 1)

    def on_payload_sent(self) -> None:
        now = time.time()
        self._telemetry.payloads_sent += 1
        self._telemetry.last_activity_ts = now
        self._payload_timestamps.append(now)

    def record_latency(self, latency_ms: float) -> None:
        alpha = 0.2
        self._telemetry.avg_latency_ms = alpha * latency_ms + (1 - alpha) * self._telemetry.avg_latency_ms

    def snapshot(self) -> dict:
        t = self._telemetry.to_dict()
        t["agent_id"] = self.agent_id
        t["description"] = self.description
        t["status"] = "active" if self._telemetry.connected_clients > 0 else "idle"
        return t

    async def _tick_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(1)
                now = time.time()
                cutoff = now - self._cps_window_seconds
                self._payload_timestamps = [ts for ts in self._payload_timestamps if ts >= cutoff]
                self._telemetry.payloads_per_second = round(len(self._payload_timestamps) / self._cps_window_seconds, 2)
                self._telemetry.uptime_seconds = round(now - self._start_time)
                
                try:
                    from server.routers.metrics_ws import broadcast_brain_metrics
                    await broadcast_brain_metrics({
                        "type": "mobile_dashboard_health",
                        "data": self.snapshot(),
                    })
                except Exception:
                    pass
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"[MobileDashboardAgent] tick error: {exc}")

_instance: Optional[MobileDashboardAgent] = None

def get_mobile_dashboard() -> MobileDashboardAgent:
    global _instance
    if _instance is None:
        _instance = MobileDashboardAgent()
    return _instance
