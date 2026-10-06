"""
mobile_gateway_agent.py
───────────────────────
MobileGatewayAgent — a swarm-registered agent that tracks the connected
mobile devices (every channel of one phone counts as a single device), command
throughput, latency, and health in real-time.

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


# ── Device registry ────────────────────────────────────────────────────────────

_ANON_PREFIX = "anon:"


class DeviceRegistry:
    """Counts connected mobile DEVICES, not raw sockets.

    One phone opens several channels to the backend — chat ``/ws/mobile``,
    control ``/ws/mobile/control`` and analytics ``/ws/mobile/analytics`` — so
    a plain connect/disconnect counter reported "2 devices connected" for a
    single phone. Clients announce a stable per-install id via the
    ``client_id`` query param, and every channel of one install shares it, so
    the channels are refcounted under that id and the phone is counted once.
    The device leaves only when its last channel closes.

    A client that omits ``client_id`` (an older app build) cannot be grouped
    honestly, so each of its sockets is tracked under its own synthetic key
    and counts as one client — the truthful reading when identity is unknown.
    """

    def __init__(self, label: str) -> None:
        self._label = label
        self._channels: dict[str, int] = {}   # client key → open channels
        self._anon_seq = 0

    def connect(self, client_id: Optional[str] = None) -> str:
        """Register one channel and return the key to pass to [disconnect]."""
        key = self._key(client_id)
        self._channels[key] = self._channels.get(key, 0) + 1
        return key

    def disconnect(self, key: Optional[str] = None) -> None:
        """Release one channel. The device drops out when its last one goes.

        [key] is the value returned by [connect]. When a legacy call site has
        no key, the most recent un-identified socket is released so the count
        stays truthful; an identified device is never guessed away, because
        dropping a live phone would understate the real connection.
        """
        if key is not None:
            self._release(key)
            return
        for candidate in reversed(list(self._channels)):
            if candidate.startswith(_ANON_PREFIX):
                self._release(candidate)
                return
        logger.warning(
            f"[{self._label}] disconnect without a client key and no "
            f"un-identified sockets to release — ignored"
        )

    @property
    def devices(self) -> int:
        """Distinct connected devices."""
        return len(self._channels)

    @property
    def sockets(self) -> int:
        """Total open channels across every device."""
        return sum(self._channels.values())

    def _key(self, client_id: Optional[str]) -> str:
        if isinstance(client_id, str) and client_id.strip():
            return client_id.strip()
        self._anon_seq += 1
        return f"{_ANON_PREFIX}{self._anon_seq}"

    def _release(self, key: str) -> None:
        remaining = self._channels.get(key)
        if remaining is None:
            logger.debug(
                f"[{self._label}] disconnect for unknown client {key!r} — ignored"
            )
            return
        if remaining <= 1:
            del self._channels[key]
        else:
            self._channels[key] = remaining - 1


# ── Telemetry model ────────────────────────────────────────────────────────────

@dataclass
class MobileTelemetry:
    """Live snapshot of mobile load tracked by MobileGatewayAgent."""
    connected_clients: int = 0
    connected_channels: int = 0
    peak_clients: int = 0
    commands_processed: int = 0
    commands_per_second: float = 0.0
    interrupts_sent: int = 0
    remote_inputs_forwarded: int = 0
    avg_latency_ms: float = 0.0
    last_activity_ts: float = field(default_factory=time.time)
    uptime_seconds: float = 0.0
    # Latest phone-reported device metrics (battery / CPU / memory / model)
    # pushed by the app via /ws/mobile/control `device_metrics` frames.
    device: dict = field(default_factory=dict)
    device_last_ts: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


# ── Agent ────────────────────────────────────────────────────────────────

@register_agent
class MobileGatewayAgent(BaseSwarmAgent):
    """
    Monitors and manages the mobile client connection pool.

    Responsibilities:
      - Track connected mobile devices (all channels of one phone collapse
        into a single client, see [DeviceRegistry])
      - Count command throughput and compute rolling CPS (commands-per-second)
      - Detect mobile client disconnections and emit log warnings
      - Expose live telemetry for the Agent Discovery Panel
      - Broadcast periodic health pings over the metrics WebSocket
    """

    agent_id = "mobile_gateway"
    description = "Manages mobile WebSocket load, throughput, and health telemetry."

    def __init__(self) -> None:
        self._telemetry = MobileTelemetry()
        self._registry = DeviceRegistry("MobileGatewayAgent")
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

    def on_client_connected(self, client_id: Optional[str] = None) -> str:
        """Count one channel for a device and return its disconnect key.

        [client_id] is the per-install id the app sends on every channel, so
        the phone's chat + control sockets collapse into a single device.
        """
        key = self._registry.connect(client_id)
        self._sync_counts()
        self._telemetry.last_activity_ts = time.time()
        logger.info(
            f"[MobileGatewayAgent] Client connected "
            f"(devices={self._telemetry.connected_clients}, "
            f"channels={self._telemetry.connected_channels})"
        )
        return key

    def on_client_disconnected(self, client_key: Optional[str] = None) -> None:
        """Release one channel; the device is dropped when its last one goes."""
        self._registry.disconnect(client_key)
        self._sync_counts()
        logger.info(
            f"[MobileGatewayAgent] Client disconnected "
            f"(devices={self._telemetry.connected_clients}, "
            f"channels={self._telemetry.connected_channels})"
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

    def record_device_metrics(self, device: dict, ts: float = 0.0) -> None:
        """Store the phone's latest reported device metrics (battery, CPU,
        memory, model…). Kept as the most recent sample so the System Health
        tab can render the phone's own performance. Also counts as proof of
        life, so it refreshes last_activity_ts.

        Defensive by design: this runs inside the /ws/mobile/control handler
        (which has no generic exception guard), so a malformed payload from a
        buggy or malicious client must never raise.
        """
        if not isinstance(device, dict):
            device = {}
        try:
            ts_f = float(ts) if ts else time.time()
        except (TypeError, ValueError):
            ts_f = time.time()
        self._telemetry.device = dict(device)
        self._telemetry.device_last_ts = ts_f
        self._telemetry.last_activity_ts = time.time()

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

    def _sync_counts(self) -> None:
        """Mirror the registry into telemetry, keeping the device peak."""
        self._telemetry.connected_clients = self._registry.devices
        self._telemetry.connected_channels = self._registry.sockets
        if self._telemetry.connected_clients > self._telemetry.peak_clients:
            self._telemetry.peak_clients = self._telemetry.connected_clients

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
