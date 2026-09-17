"""
system_health.py
────────────────
SystemHealthMonitor — the analytics dashboard's "System Health" tab data source.

Collects a single, JSON-ready health snapshot every ~2 s and broadcasts it as a
`system_health` frame to every /ws/brain_metrics subscriber (the shared socket
the Analytics Dashboard already consumes), so the panel is live with zero new
connections. The same snapshot is served on demand by GET /api/system/health
(see server/routers/system_health_router.py) as a fetch fallback.

Snapshot sections:
  server    — CPU (overall + per-core), RAM, swap, disk partitions, network
              I/O + connection count, load average, process RSS / threads /
              open files, server + system uptime, platform (all best-effort
              via psutil; missing keys omitted when psutil is absent).
  checks    — live health probes for core subsystems (brain, RAG, memory,
              voice, predictor, planner, autonomy daemon, swarm, meeting
              mode, security, prediction engine, filesystem/desktop twin,
              self-heal, runtime telemetry…). Probes are cheap, lazily
              imported and never raise.
  functions — auto-discovered "functions" from the AgentRegistry. When a new
              agent/function is added to the codebase, AgentScanner finds it,
              the registry records it, and the very next frame includes it —
              so the dashboard's Functions grid updates automatically.
  mobile    — mobile app performance + health, folded from the three live
              mobile swarm agents (gateway / analytics / dashboard WS). The
              panel shows this section only while the app is connected.
  history   — rolling window of CPU / RAM / mobile-client samples so the
              frontend can render sparklines without keeping its own store.

Extension: any module can register its own probe via
  from server.systems.system_health import get_system_health
  get_system_health().register_probe("my_feature", my_probe_fn)
A probe fn takes no args and returns
  {"status": "ok"|"warn"|"down"|"unknown", "detail": str,
   "latency_ms": float|None, "meta": dict|None}
Registered probes are included in every frame automatically — this is the
"new function added → automatically display its health" hook.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

logger = logging.getLogger("aariya.system_health")

# How often the monitor broadcasts a fresh frame (s).
BROADCAST_SECONDS = 2.0
# History window length (samples) for sparklines.
HISTORY_LEN = 60
# psutil-heavy probes (network rates / disk scan) run every Nth tick.
HEAVY_EVERY_N_TICKS = 10
# How often the auto-discovered function list is refreshed from the registry.
FUNCTIONS_REFRESH_SECONDS = 15.0

# Health thresholds used by the score + status derivation.
CPU_WARN = 80.0
CPU_CRIT = 95.0
RAM_WARN = 82.0
RAM_CRIT = 95.0
DISK_WARN = 85.0
DISK_CRIT = 95.0


# ── Status helpers ────────────────────────────────────────────────────────────

def _status_for(value: float, warn: float, crit: float, invert: bool = False) -> str:
    """Map a utilization value to ok/warn/crit. invert=True → low is bad."""
    if invert:
        return "warn" if value < warn else "ok"  # crit never triggers for inverted
    if value >= crit:
        return "crit"
    if value >= warn:
        return "warn"
    return "ok"


def _ok(detail: str, latency_ms: Optional[float] = None, meta: Optional[dict] = None) -> dict:
    return {"status": "ok", "detail": detail, "latency_ms": latency_ms, "meta": meta or {}}


def _warn(detail: str, latency_ms: Optional[float] = None, meta: Optional[dict] = None) -> dict:
    return {"status": "warn", "detail": detail, "latency_ms": latency_ms, "meta": meta or {}}


def _down(detail: str, latency_ms: Optional[float] = None, meta: Optional[dict] = None) -> dict:
    return {"status": "down", "detail": detail, "latency_ms": latency_ms, "meta": meta or {}}


def _unknown(detail: str = "not checked", latency_ms: Optional[float] = None) -> dict:
    return {"status": "unknown", "detail": detail, "latency_ms": latency_ms, "meta": {}}


# ── Subsystem probes (all best-effort; never raise) ───────────────────────────

def _probe_brain() -> dict:
    try:
        from server.systems.brain_v2 import _registry  # type: ignore[attr-defined]
        count = len(_registry) if _registry else 0
        if count > 0:
            return _ok(f"{count} brain instance(s) live")
        return _warn("no brain instance registered yet")
    except Exception:
        return _unknown("module not imported")


def _probe_rag_indexer() -> dict:
    try:
        from server.systems.rag.obsidian_indexer import get_obsidian_indexer
        idx = get_obsidian_indexer()
        dev = bool(getattr(idx, "developer_vault", None))
        run = bool(getattr(idx, "runtime_vault", None))
        chunks = 0
        try:
            chunks = idx.count("obsidian_developer") + idx.count("obsidian_runtime")
        except Exception:
            pass
        if dev or run:
            return _ok(
                f"vaults: {'dev ✓' if dev else 'dev ✗'} / {'runtime ✓' if run else 'runtime ✗'}",
                meta={"developer_vault": dev, "runtime_vault": run, "chunks": chunks},
            )
        return _warn("no Obsidian vault configured", meta={"chunks": chunks})
    except Exception as exc:
        return _unknown(f"indexer unavailable ({type(exc).__name__})")


def _probe_memory_hierarchy() -> dict:
    try:
        from server.systems.memory_hierarchy import MemoryHierarchy  # noqa: F401
        return _ok("MemoryHierarchy module loaded")
    except Exception:
        return _unknown("not loaded")


def _probe_emotion_predictor() -> dict:
    try:
        from server.systems.emotion import predictor
        meta = predictor.read_training_meta(predictor.MODEL_PATH) or {}
        trained_at = meta.get("trained_at") or 0.0
        trained = bool(trained_at)
        if trained:
            return _ok(
                "LSTM checkpoint loaded",
                meta={"status": "trained", "count": meta.get("count", 0),
                      "seed_count": meta.get("seed_count", 0)},
            )
        return _warn("predictor present, no trained checkpoint yet")
    except Exception:
        return _unknown("not loaded")


def _probe_planner() -> dict:
    try:
        from server.systems.planner import plan  # noqa: F401
        return _ok("planner module loaded")
    except Exception:
        return _unknown("not loaded")


def _probe_autonomy_daemon() -> dict:
    try:
        from server.autonomy.daemon import get_daemon
        daemon = get_daemon()
        running = bool(getattr(daemon, "is_running", False))
        # The daemon tracks its last real activity on private timestamps;
        # _last_learning is a reliable "alive and ticking" signal.
        last_activity = getattr(daemon, "_last_learning", None) or getattr(
            daemon, "_last_user_message", None
        )
        age = (time.time() - last_activity) if last_activity else None
        if running:
            age_s = f"{age:.0f}s ago" if age is not None else "n/a"
            return _ok(f"running (last activity {age_s})", meta={"last_activity_age_s": age})
        return _warn("daemon not started", meta={"last_activity_age_s": age})
    except Exception:
        return _unknown("not loaded")


def _probe_swarm() -> dict:
    try:
        from server.systems.swarm.orchestrator import get_swarm_system  # noqa: F401
        from server.infrastructure.agent_registry import get_registry
        stats = get_registry().stats()
        total = int(stats.get("total", 0))
        return _ok(f"{total} discovered agent(s)", meta=stats)
    except Exception:
        return _unknown("not loaded")


def _probe_meeting_mode() -> dict:
    try:
        from server.systems.meeting_mode import get_meeting_mode
        mm = get_meeting_mode()
        active = bool(getattr(mm, "active", False))
        return _ok("active" if active else "inactive", meta={"active": active})
    except Exception:
        return _unknown("not loaded")


def _probe_security() -> dict:
    try:
        from server.systems.swarm.orchestrator import get_swarm_system  # noqa: F401
        from server.systems.security.agents.network_agent import (  # noqa: F401
            NetworkAgent,
        )
        return _ok("security agents module loaded")
    except Exception:
        return _unknown("not loaded")


def _probe_prediction_engine() -> dict:
    try:
        from server.systems.prediction.prediction_core import get_prediction_engine
        engine = get_prediction_engine()
        n = len(getattr(engine, "trajectories", {}) or {})
        return _ok(f"{n} trajectory(ies) tracked", meta={"trajectories": n})
    except Exception:
        return _unknown("not loaded")


def _probe_filesystem() -> dict:
    try:
        from server.systems.filesystem.background_service import get_filesystem_service
        svc = get_filesystem_service("user_default")
        running = bool(getattr(svc, "is_running", False) or getattr(svc, "running", False))
        if running:
            return _ok("filesystem background service running")
        return _warn("filesystem service present but not running")
    except Exception:
        return _unknown("not loaded")


def _probe_desktop_twin() -> dict:
    try:
        from server.systems.desktop_twin import get_desktop_twin  # type: ignore
        twin = get_desktop_twin()
        running = bool(getattr(twin, "is_running", False) or getattr(twin, "running", False))
        return _ok("desktop twin running" if running else "desktop twin present, idle")
    except Exception:
        try:
            import server.systems.desktop_twin  # noqa: F401
            return _warn("desktop twin module loaded, singleton unavailable")
        except Exception:
            return _unknown("not loaded")


def _probe_self_heal() -> dict:
    try:
        from server.systems.self_heal.loop import get_healing_engine
        engine = get_healing_engine()
        last = getattr(engine, "last_action_taken", None)
        detail = f"last action: {last}" if last else "monitoring (no anomalies)"
        return _ok(detail)
    except Exception:
        return _unknown("not loaded")


def _probe_meta_cognition() -> dict:
    try:
        from server.systems.meta_cognition import MetaCognitionEngine  # noqa: F401
        return _ok("meta-cognition module loaded")
    except Exception:
        return _unknown("not loaded")


def _probe_runtime_telemetry() -> dict:
    try:
        from server.systems.rag.runtime_telemetry import _loop_started  # type: ignore
        if _loop_started:
            return _ok("runtime telemetry logger running")
        return _warn("runtime telemetry not started")
    except Exception:
        return _unknown("not loaded")


def _probe_gev() -> dict:
    """GEV health: on-demand agent status, last fetch age, and server reachability."""
    try:
        from server.systems.gev.gev_agent import get_gev_agent
        agent = get_gev_agent()
        last_fetch = getattr(agent, "_last_fetch_at", 0)
        last_snapshot = getattr(agent, "_last_snapshot", {})
        age_s = round(time.time() - last_fetch, 1) if last_fetch else None

        # Count layers that returned live data (not {"available": False})
        live_layers = sum(
            1 for v in last_snapshot.values()
            if isinstance(v, dict) and v.get("available") is not False
        )
        total_layers = len(last_snapshot) if last_snapshot else 0

        if not last_snapshot:
            return _warn(
                "on-demand mode — no data fetched yet",
                meta={"mode": "on_demand", "live_layers": 0},
            )

        if age_s is not None and age_s > 300:
            return _warn(
                f"data stale — last fetch {age_s:.0f}s ago",
                meta={"age_s": age_s, "live_layers": live_layers, "total_layers": total_layers},
            )

        age_label = f"{age_s:.0f}s ago" if age_s is not None else "never"
        return _ok(
            f"on-demand · {live_layers}/{total_layers} layers live · fetched {age_label}",
            meta={"mode": "on_demand", "age_s": age_s, "live_layers": live_layers, "total_layers": total_layers},
        )
    except Exception:
        return _unknown("not loaded")


# ── Probe registry ────────────────────────────────────────────────────────────

#: name -> callable(). The canonical list of health checks. Registering an
#: additional probe makes it appear on the dashboard automatically.
PROBES: dict[str, Callable[[], dict]] = {
    "brain": _probe_brain,
    "rag_indexer": _probe_rag_indexer,
    "memory_hierarchy": _probe_memory_hierarchy,
    "emotion_predictor": _probe_emotion_predictor,
    "planner": _probe_planner,
    "autonomy_daemon": _probe_autonomy_daemon,
    "swarm": _probe_swarm,
    "meeting_mode": _probe_meeting_mode,
    "security": _probe_security,
    "prediction_engine": _probe_prediction_engine,
    "filesystem": _probe_filesystem,
    "desktop_twin": _probe_desktop_twin,
    "self_heal": _probe_self_heal,
    "meta_cognition": _probe_meta_cognition,
    "runtime_telemetry": _probe_runtime_telemetry,
    "gev": _probe_gev,
}

#: Human-friendly labels for the probe names (frontend falls back to the name).
PROBE_LABELS: dict[str, str] = {
    "brain": "Brain",
    "rag_indexer": "RAG Indexer",
    "memory_hierarchy": "Memory Hierarchy",
    "emotion_predictor": "Emotion Predictor",
    "planner": "Planner",
    "autonomy_daemon": "Autonomy Daemon",
    "swarm": "Swarm",
    "meeting_mode": "Meeting Mode",
    "security": "Security",
    "prediction_engine": "Prediction Engine",
    "filesystem": "Filesystem",
    "desktop_twin": "Desktop Twin",
    "self_heal": "Self-Healing",
    "meta_cognition": "Meta-Cognition",
    "runtime_telemetry": "Runtime Telemetry",
    "gev": "GEV (God's Eye View)",
}


# ── Server performance collection ─────────────────────────────────────────────

# psutil's Process().cpu_percent(interval=None) compares against the LAST call
# on the SAME Process object. A fresh psutil.Process() each tick has no prior
# sample and always reports 0.0 — so cache one handle at module level.
_PROC_HANDLE = None
_PROC_PID = None


def _get_proc_handle():
    """Return a cached psutil.Process() handle, refreshed if the PID changes."""
    global _PROC_HANDLE, _PROC_PID
    try:
        import psutil
        pid = os.getpid()
        if _PROC_HANDLE is None or _PROC_PID != pid:
            _PROC_HANDLE = psutil.Process(pid)
            _PROC_PID = pid
        return _PROC_HANDLE
    except Exception:
        return None


def _collect_server_perf() -> dict:
    """Best-effort psutil snapshot of the server's host machine."""
    out: dict[str, Any] = {}
    try:
        import psutil
        proc = _get_proc_handle() or psutil.Process()

        out["cpu_percent"] = round(psutil.cpu_percent(interval=None), 1)
        out["cpu_count"] = psutil.cpu_count(logical=True) or 0
        try:
            out["cpu_per_core"] = [round(p, 1) for p in psutil.cpu_percent(interval=None, percpu=True)]
        except Exception:
            pass

        vm = psutil.virtual_memory()
        out["ram_percent"] = round(vm.percent, 1)
        out["ram_used_gb"] = round(vm.used / (1024**3), 2)
        out["ram_total_gb"] = round(vm.total / (1024**3), 2)
        out["ram_available_gb"] = round(vm.available / (1024**3), 2)
        try:
            sm = psutil.swap_memory()
            out["swap_percent"] = round(sm.percent, 1)
        except Exception:
            pass

        out["server_uptime_s"] = round(time.time() - proc.create_time())
        out["system_uptime_s"] = round(time.time() - psutil.boot_time())
        try:
            out["load_avg"] = [round(x, 2) for x in os.getloadavg()]
        except Exception:
            pass

        mem = proc.memory_info()
        out["process"] = {
            "rss_mb": round(mem.rss / (1024**2)),
            "vms_mb": round(getattr(mem, "vms", 0) / (1024**2)),
            "threads": proc.num_threads(),
            "cpu_percent": round(proc.cpu_percent(interval=None), 1),
            "python": sys.version.split()[0],
        }
        try:
            out["process"]["open_files"] = len(proc.open_files())
        except Exception as exc:
            logger.debug("[SystemHealth] open_files count unavailable: %s", exc)

        try:
            import platform as _platform
            out["platform"] = f"{_platform.system()}-{_platform.release()}-{_platform.machine()}"
        except Exception as exc:
            logger.debug("[SystemHealth] platform info unavailable: %s", exc)
        try:
            out["hostname"] = os.uname().nodename
        except Exception as exc:
            logger.debug("[SystemHealth] hostname unavailable: %s", exc)
    except Exception as exc:
        logger.debug("system_health: psutil unavailable: %s", exc)

    return out


def _collect_disks() -> list[dict]:
    disks: list[dict] = []
    try:
        import psutil
        for part in psutil.disk_partitions(all=True):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except Exception:
                continue
            if usage.total == 0:
                continue
            disks.append({
                "mount": part.mountpoint,
                "fs": part.fstype,
                "device": part.device,
                "percent": round(usage.percent, 1),
                "used_gb": round(usage.used / (1024**3), 1),
                "total_gb": round(usage.total / (1024**3), 1),
            })
    except Exception as exc:
        logger.debug("[SystemHealth] disk collection failed: %s", exc)
    return disks


def _collect_network() -> dict:
    out: dict[str, Any] = {}
    try:
        import psutil
        net = psutil.net_io_counters()
        out["bytes_sent_mb"] = round(net.bytes_sent / (1024**2), 1)
        out["bytes_recv_mb"] = round(net.bytes_recv / (1024**2), 1)
        try:
            out["connections"] = len(psutil.net_connections(kind="inet"))
        except Exception as exc:
            logger.debug("[SystemHealth] net_connections count unavailable: %s", exc)
    except Exception as exc:
        logger.debug("[SystemHealth] network stats unavailable: %s", exc)
    return out


# ── Auto-discovered functions (AgentRegistry) ─────────────────────────────────

def _collect_functions() -> list[dict]:
    """Every auto-discovered function/agent from the registry.

    New code added to the project is picked up by AgentScanner → registry, so
    this list is the "new function appears automatically" feed.
    """
    try:
        from server.infrastructure.agent_registry import get_registry
        agents = get_registry().get_active_agents()
        out = []
        for a in agents:
            out.append({
                "name": a.get("name", "Unknown"),
                "display_name": a.get("display_name", a.get("name", "Unknown")),
                "kind": a.get("kind", "class"),
                "status": a.get("status", "existing"),
                "detection": a.get("detection", []),
                "file": a.get("file", ""),
                "first_seen": a.get("first_seen", ""),
                "last_seen": a.get("last_seen", ""),
            })
        # Keep display stable: newest discoveries first. Cap so a very large
        # codebase never bloats the 2 s broadcast frame.
        out.sort(key=lambda f: f.get("first_seen") or "", reverse=True)
        return out[:60]
    except Exception:
        return []


# ── Mobile telemetry ───────────────────────────────────────────────────────────

def _collect_mobile() -> dict:
    """Fold the three live mobile swarm agents into one section."""
    out: dict[str, Any] = {
        "connected": False,
        "clients": 0,
        "peak_clients": 0,
        "commands_processed": 0,
        "commands_per_second": 0.0,
        "avg_latency_ms": 0.0,
        "interrupts_sent": 0,
        "remote_inputs_forwarded": 0,
        "uptime_s": 0,
        "last_activity_ts": None,
        "device": {},
        "device_last_ts": None,
        "channels": {},
    }
    try:
        from server.systems.agent.mobile_gateway_agent import get_mobile_gateway
        g = get_mobile_gateway().snapshot()
        out["connected"] = bool(g.get("connected_clients", 0) > 0)
        out["clients"] = int(g.get("connected_clients", 0))
        out["peak_clients"] = int(g.get("peak_clients", 0))
        out["commands_processed"] = int(g.get("commands_processed", 0))
        out["commands_per_second"] = round(float(g.get("commands_per_second", 0.0)), 2)
        out["avg_latency_ms"] = round(float(g.get("avg_latency_ms", 0.0)), 1)
        out["interrupts_sent"] = int(g.get("interrupts_sent", 0))
        out["remote_inputs_forwarded"] = int(g.get("remote_inputs_forwarded", 0))
        out["uptime_s"] = int(g.get("uptime_seconds", 0))
        out["last_activity_ts"] = g.get("last_activity_ts")
        # Phone-reported device metrics (battery / CPU / memory / model).
        out["device"] = g.get("device") or {}
        out["device_last_ts"] = g.get("device_last_ts") or None
    except Exception:
        pass

    for channel, getter in (
        ("analytics", "get_mobile_analytics"),
        ("dashboard", "get_mobile_dashboard"),
    ):
        try:
            module = __import__(
                f"server.systems.agent.{'mobile_analytics_agent' if channel == 'analytics' else 'mobile_dashboard_agent'}",
                fromlist=[getter],
            )
            snapshot = getattr(module, getter)().snapshot()
            out["channels"][channel] = snapshot
        except Exception:
            out["channels"][channel] = {}
    return out


# ── Health score ──────────────────────────────────────────────────────────────

def _compute_score(server: dict, disks: list[dict], checks: list[dict], mobile: dict) -> int:
    score = 100.0

    cpu = server.get("cpu_percent") or 0.0
    score -= max(0.0, (cpu - 60.0)) * 0.35   # up to ~12 pts
    ram = server.get("ram_percent") or 0.0
    score -= max(0.0, (ram - 60.0)) * 0.35
    for d in disks:
        score -= max(0.0, (d.get("percent", 0.0) - 70.0)) * 0.2

    for c in checks:
        if c.get("status") == "down":
            score -= 8.0
        elif c.get("status") == "warn":
            score -= 3.0
        elif c.get("status") == "unknown":
            score -= 1.0

    if not mobile.get("connected") and mobile.get("last_activity_ts"):
        score -= 2.0  # was connected before, now silent

    return max(0, min(100, round(score)))


# ── Monitor ───────────────────────────────────────────────────────────────────

class SystemHealthMonitor:
    """Collects + broadcasts the full system health snapshot on an interval."""

    def __init__(self) -> None:
        self._latest: dict[str, Any] = {}
        self._history_cpu: deque[float] = deque(maxlen=HISTORY_LEN)
        self._history_ram: deque[float] = deque(maxlen=HISTORY_LEN)
        self._history_mobile: deque[int] = deque(maxlen=HISTORY_LEN)
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._tick = 0
        self._last_functions_refresh = 0.0
        self._functions_cache: list[dict] = []
        # Guards the mutable history/_latest section — the broadcast loop runs
        # on the event loop while the REST endpoint may be called from a
        # FastAPI threadpool thread.
        self._lock = threading.Lock()
        # ── Real transition tracking (drives the Event Log) ────────────────
        # Previous observed state so the monitor can emit REAL log_event
        # frames when something genuinely changes — no synthetic events, only
        # actual transitions: a health check flipping status, a brand-new
        # function appearing, or the mobile app connecting/disconnecting.
        self._prev_checks: dict[str, str] = {}
        self._prev_functions: set[str] = set()
        self._prev_mobile_connected: Optional[bool] = None
        self._prev_score: Optional[int] = None
        # True once the first snapshot has been seen — the first frame only
        # seeds the previous-state baseline so startup never bursts events.
        self._seeded = False

    # ── Probe registry (extensibility hook) ──────────────────────────────────

    def register_probe(self, name: str, fn: Callable[[], dict]) -> None:
        """Add a health probe that appears on the dashboard automatically."""
        PROBES[name] = fn

    def invalidate_functions(self) -> None:
        """
        Force the next broadcast to re-read the AgentRegistry immediately.

        The evolution loop calls this right after spawning / retiring an agent
        so the dashboard's Functions grid reflects the self-improvement on the
        very next 2 s frame instead of waiting for the 15 s refresh cadence.
        """
        self._functions_cache = []
        self._last_functions_refresh = 0.0

    # ── Collection ────────────────────────────────────────────────────────────

    def collect(self) -> dict:
        """Build a full snapshot. Fast path + cached functions list."""
        self._tick += 1
        heavy = (self._tick % HEAVY_EVERY_N_TICKS) == 0

        t0 = time.monotonic()
        server = _collect_server_perf()
        # Disks + network are the psutil-heavy collectors — throttle to every
        # HEAVY_EVERY_N_TICKS ticks, reusing the last cached values between.
        if heavy:
            disks = _collect_disks()
            network = _collect_network()
        else:
            disks = self._latest.get("server", {}).get("disks", [])
            network = self._latest.get("server", {}).get("network", {})
        server["disks"] = disks
        server["network"] = network

        # Probes (cheap after first import — lazily imported, never raise).
        checks = []
        for name, fn in PROBES.items():
            p0 = time.monotonic()
            try:
                result = fn()
                result.setdefault("latency_ms", round((time.monotonic() - p0) * 1000, 2))
            except Exception as exc:
                result = _down(f"probe raised {type(exc).__name__}: {exc}")
            result["name"] = name
            result["label"] = PROBE_LABELS.get(name, name)
            checks.append(result)

        # Functions: refresh from registry on a slower cadence.
        now = time.time()
        if not self._functions_cache or (now - self._last_functions_refresh) >= FUNCTIONS_REFRESH_SECONDS:
            self._functions_cache = _collect_functions()
            self._last_functions_refresh = now
        functions = self._functions_cache

        mobile = _collect_mobile()

        # Rolling history for sparklines (locked — shared with REST callers).
        with self._lock:
            self._history_cpu.append(round(server.get("cpu_percent") or 0.0, 1))
            self._history_ram.append(round(server.get("ram_percent") or 0.0, 1))
            self._history_mobile.append(int(mobile.get("clients", 0)))
            snapshot = {
                "ts": time.time(),
                "collection_ms": round((time.monotonic() - t0) * 1000, 1),
                "server": server,
                "checks": checks,
                "functions": functions,
                "mobile": mobile,
                "score": _compute_score(server, disks, checks, mobile),
                "history": {
                    "cpu": list(self._history_cpu),
                    "ram": list(self._history_ram),
                    "mobile_clients": list(self._history_mobile),
                },
            }
            self._latest = snapshot
        return snapshot

    def snapshot(self) -> dict:
        """Return the latest collected snapshot (collects on first call)."""
        if not self._latest:
            self.collect()
        return self._latest

    # ── Broadcast loop ────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the 2 s broadcast loop (call from FastAPI lifespan)."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._run())
        logger.info("[SystemHealthMonitor] Started — broadcasting every %.0fs", BROADCAST_SECONDS)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while self._running:
            try:
                snapshot = self.collect()
                try:
                    from server.routers.metrics_ws import broadcast_brain_metrics
                    await broadcast_brain_metrics({"type": "system_health", "data": snapshot})
                    # Real Event Log feed: emit genuine transition events.
                    await self._emit_real_events(snapshot)
                except Exception as exc:
                    logger.debug("system_health broadcast skipped: %s", exc)
            except Exception as exc:
                logger.warning("system_health tick error: %s", exc)
            await asyncio.sleep(BROADCAST_SECONDS)

    async def _emit_real_events(self, snapshot: dict) -> None:
        """Emit `log_event` frames only when the observed state genuinely
        changed since the last tick: a health check flipped status, a new
        function was auto-discovered, or the mobile app connected / left.
        Pure steady state emits nothing — the Event Log stays clean and real."""
        events: list[dict] = []

        # First frame: seed the baseline silently. The Event Log only reports
        # transitions observed AFTER the monitor has seen one stable frame —
        # so a freshly booted server doesn't burst "new function discovered"
        # events for every agent already in the registry.
        if not self._seeded:
            self._prev_checks = {c.get("name"): c.get("status") for c in snapshot.get("checks", [])}
            self._prev_functions = {f.get("name") for f in snapshot.get("functions", [])}
            self._prev_mobile_connected = bool(snapshot.get("mobile", {}).get("connected"))
            self._prev_score = snapshot.get("score")
            self._seeded = True
            return

        # 1) Health check status flips.
        for c in snapshot.get("checks", []):
            name = c.get("name")
            status = c.get("status")
            prev = self._prev_checks.get(name)
            if prev is not None and prev != status:
                sev = {"down": "critical", "warn": "warn", "unknown": "warn"}.get(status, "info")
                if status == "ok":
                    sev = "info"  # recovery is good news, not an alert
                events.append({
                    "type": "log_event",
                    "tag": "HEALTH",
                    "severity": sev,
                    "message": f"{PROBE_LABELS.get(name, name)} → {status.upper()}: {c.get('detail', '')}",
                    "timestamp": snapshot.get("ts", time.time()),
                })
            self._prev_checks[name] = status

        # 2) Newly auto-discovered functions (new code added → first frame).
        cur_functions = {f.get("name") for f in snapshot.get("functions", [])}
        new_functions = sorted(cur_functions - self._prev_functions)
        for name in new_functions[:5]:  # cap burst of names in one frame
            events.append({
                "type": "log_event",
                "tag": "FUNCTIONS",
                "severity": "info",
                "message": f"New function auto-discovered: {name}",
                "timestamp": snapshot.get("ts", time.time()),
            })
        self._prev_functions = cur_functions

        # 3) Mobile app connect / disconnect.
        connected = bool(snapshot.get("mobile", {}).get("connected"))
        if self._prev_mobile_connected is not None and connected != self._prev_mobile_connected:
            events.append({
                "type": "log_event",
                "tag": "MOBILE",
                "severity": "info" if connected else "warn",
                "message": "Mobile app connected" if connected else "Mobile app disconnected",
                "timestamp": snapshot.get("ts", time.time()),
            })
        self._prev_mobile_connected = connected

        # 4) Health score drops below the warning line (or recovers above it).
        score = snapshot.get("score")
        if score is not None:
            prev_score = self._prev_score
            if prev_score is not None and score < 60 and prev_score >= 60:
                events.append({
                    "type": "log_event",
                    "tag": "SYSTEM",
                    "severity": "critical",
                    "message": f"Health score dropped to {score}/100 — system under stress",
                    "timestamp": snapshot.get("ts", time.time()),
                })
            elif prev_score is not None and score >= 60 and prev_score < 60:
                events.append({
                    "type": "log_event",
                    "tag": "SYSTEM",
                    "severity": "info",
                    "message": f"Health score recovered to {score}/100",
                    "timestamp": snapshot.get("ts", time.time()),
                })
            self._prev_score = score

        if not events:
            return
        try:
            from server.routers.metrics_ws import broadcast_brain_metrics
            for ev in events:
                await broadcast_brain_metrics(ev)
        except Exception as exc:
            logger.debug("system_health log_event broadcast skipped: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[SystemHealthMonitor] = None


def get_system_health() -> SystemHealthMonitor:
    global _instance
    if _instance is None:
        _instance = SystemHealthMonitor()
    return _instance
