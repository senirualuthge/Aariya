"""
mobile_gateway_agent.py
───────────────────────
MobileGatewayAgent — a swarm-registered agent that tracks all mobile client
connections, command throughput, latency, and health in real-time.

Auto-detected by AgentScanner via:
  • FOLDER strategy  — lives in server/systems/agent/
  • INHERITANCE      — extends BaseSwarmAgent

Lifecycle:
  start()  — call once from lifespan (or import side-effect)
  stop()   — called on server shutdown
  tick()   — internal 1-second heartbeat; updates telemetry snapshot

The agent exposes a shared singleton:
    from server.systems.agent.mobile_gateway_agent import get_mobile_gateway
    agent = get_mobile_gateway()
"""

from __future__ import annotations

import asyncio
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("aariya.mobile_gateway_agent")


# ── Registration decorator (activates AgentScanner decorator strategy) ───────────────

def register_agent(cls):
    """Decorator: marks a class for automatic swarm agent discovery."""
    cls._is_registered_agent = True
    return cls


# ── Minimal base so AgentScanner inheritance strategy also fires ───────────────

class BaseSwarmAgent:
    """Lightweight marker base — all swarm sub-agents inherit from this."""
    agent_id: str = "base"
    description: str = ""


# ── Telemetry model ────────────────────────────────────────────────────────────

@dataclass
class MobileTelemetry:
    """Live snapshot of mobile load tracked by MobileGatewayAgent."""
    connected_clients: int = 0
    peak_clients: int = 0
    commands_processed: int = 0
    commands_per_second: float = 0.0
    interrupts_sent: int = 0
    remote_inputs_forwarded: int = 0
    avg_latency_ms: float = 0.0
    last_activity_ts: float = field(default_factory=time.time)
    uptime_seconds: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ── Agent ────────────────────────────────────────────────────────────────

@register_agent
class MobileGatewayAgent(BaseSwarmAgent):
    """
    Monitors and manages the mobile client connection pool.

    Responsibilities:
      - Track active /ws/mobile/control connections
      - Count command throughput and compute rolling CPS (commands-per-second)
      - Detect mobile client disconnections and emit log warnings
      - Expose live telemetry for the Agent Discovery Panel
      - Broadcast periodic health pings over the metrics WebSocket
    """

    agent_id = "mobile_gateway"
    description = "Manages mobile WebSocket load, throughput, and health telemetry."

    def __init__(self) -> None:
        self._telemetry = MobileTelemetry()
        self._start_time: float = time.time()
        self._tick_task: Optional[asyncio.Task] = None
        self._running = False

        # Rolling window for CPS calculation (ring buffer of timestamps)
        self._cmd_timestamps: list[float] = []
        self._cps_window_seconds = 10

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background telemetry tick (call from FastAPI lifespan)."""
        if self._running:
            return
        self._running = True
        self._start_time = time.time()
        self._tick_task = asyncio.ensure_future(self._tick_loop())
        logger.info("[MobileGatewayAgent] Started — monitoring mobile connections")

    def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._tick_task and not self._tick_task.done():
            self._tick_task.cancel()
        logger.info("[MobileGatewayAgent] Stopped")

    # ── Event hooks (public telemetry feed for the mobile control channel; the
    # live /ws/mobile/control handler lives in server/main.py) ─────────────────

    def on_client_connected(self) -> None:
        self._telemetry.connected_clients += 1
        if self._telemetry.connected_clients > self._telemetry.peak_clients:
            self._telemetry.peak_clients = self._telemetry.connected_clients
        self._telemetry.last_activity_ts = time.time()
        logger.info(
            f"[MobileGatewayAgent] Client connected "
            f"(active={self._telemetry.connected_clients})"
        )

    def on_client_disconnected(self) -> None:
        self._telemetry.connected_clients = max(
            0, self._telemetry.connected_clients - 1
        )
        logger.info(
            f"[MobileGatewayAgent] Client disconnected "
            f"(active={self._telemetry.connected_clients})"
        )

    def on_command(self, action: str) -> None:
        now = time.time()
        self._telemetry.commands_processed += 1
        self._telemetry.last_activity_ts = now
        self._cmd_timestamps.append(now)

        if action == "interrupt":
            self._telemetry.interrupts_sent += 1
        elif action in ("remote_input", "input.multimodal"):
            self._telemetry.remote_inputs_forwarded += 1

    def record_latency(self, latency_ms: float) -> None:
        """Exponential moving average of round-trip latency."""
        alpha = 0.2
        self._telemetry.avg_latency_ms = (
            alpha * latency_ms + (1 - alpha) * self._telemetry.avg_latency_ms
        )

    # ── Public read ───────────────────────────────────────────────────────────

    @property
    def telemetry(self) -> MobileTelemetry:
        return self._telemetry

    def snapshot(self) -> dict:
        """Full snapshot for the Agent Discovery Panel / WS broadcast."""
        t = self._telemetry.to_dict()
        t["agent_id"] = self.agent_id
        t["description"] = self.description
        t["status"] = "active" if self._telemetry.connected_clients > 0 else "idle"
        return t

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _tick_loop(self) -> None:
        """1-second heartbeat: update derived metrics and emit to metrics WS."""
        while self._running:
            try:
                await asyncio.sleep(1)
                self._update_derived()
                await self._broadcast_health()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"[MobileGatewayAgent] tick error: {exc}")

    def _update_derived(self) -> None:
        now = time.time()
        # Prune old timestamps outside the CPS window
        cutoff = now - self._cps_window_seconds
        self._cmd_timestamps = [ts for ts in self._cmd_timestamps if ts >= cutoff]
        self._telemetry.commands_per_second = round(
            len(self._cmd_timestamps) / self._cps_window_seconds, 2
        )
        self._telemetry.uptime_seconds = round(now - self._start_time)

    async def _broadcast_health(self) -> None:
        """Push a lightweight health ping over the brain_metrics WebSocket."""
        try:
            from server.routers.metrics_ws import broadcast_brain_metrics  # lazy import
            await broadcast_brain_metrics({
                "type": "mobile_gateway_health",
                "data": self.snapshot(),
            })
        except Exception:
            pass  # metrics WS may not be ready yet — best-effort


# ── Singleton ──────────────────────────────────────────────────────────────────

_instance: Optional[MobileGatewayAgent] = None


def get_mobile_gateway() -> MobileGatewayAgent:
    global _instance
    if _instance is None:
        _instance = MobileGatewayAgent()
    return _instance
