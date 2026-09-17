"""
test_system_health.py
─────────────────────
Tests for server/systems/system_health.py — the System Health tab's data
source (server performance, subsystem checks, auto-discovered functions,
mobile telemetry, health score, probe registry).
"""

import pytest

from server.systems.system_health import (
    PROBES,
    SystemHealthMonitor,
    get_system_health,
    _collect_functions,
    _collect_mobile,
    _compute_score,
    _ok,
    _warn,
    _down,
    _unknown,
)


@pytest.fixture(autouse=True)
def _fresh_monitor():
    """Give every test a clean monitor (no shared state leakage)."""
    old = get_system_health()
    import server.systems.system_health as sh
    sh._instance = SystemHealthMonitor()
    yield
    sh._instance = old


def test_snapshot_has_all_sections():
    snap = get_system_health().collect()

    assert set(snap) >= {"ts", "server", "checks", "functions", "mobile", "score", "history"}
    assert isinstance(snap["ts"], float)
    assert isinstance(snap["score"], int) and 0 <= snap["score"] <= 100
    assert isinstance(snap["checks"], list)
    assert isinstance(snap["functions"], list)
    assert isinstance(snap["mobile"], dict)
    assert set(snap["history"]) >= {"cpu", "ram", "mobile_clients"}


def test_server_perf_shape():
    server = get_system_health().collect()["server"]

    # CPU / RAM are the invariants psutil provides (or are omitted gracefully).
    if "cpu_percent" in server:
        assert isinstance(server["cpu_percent"], (int, float))
    if "ram_percent" in server:
        assert 0 <= server["ram_percent"] <= 100
        assert "ram_used_gb" in server and "ram_total_gb" in server
    # disks + network are always present as lists/dicts (possibly empty).
    assert isinstance(server.get("disks"), list)
    assert isinstance(server.get("network"), dict)


def test_every_probe_returns_typed_result():
    snap = get_system_health().collect()
    by_name = {c["name"]: c for c in snap["checks"]}

    # Every registered probe produced a row.
    assert set(by_name) == set(PROBES)

    for name, check in by_name.items():
        assert check["status"] in {"ok", "warn", "down", "unknown"}, name
        assert isinstance(check["detail"], str), name
        assert "latency_ms" in check, name
        assert check["label"], name


def test_register_probe_appears_automatically():
    monitor = get_system_health()
    monitor.register_probe(
        "custom_feature",
        lambda: _ok("my new function is healthy", latency_ms=1.2, meta={"version": 2}),
    )
    checks = {c["name"]: c for c in monitor.collect()["checks"]}

    assert "custom_feature" in checks
    assert checks["custom_feature"]["status"] == "ok"
    assert checks["custom_feature"]["detail"] == "my new function is healthy"
    assert checks["custom_feature"]["meta"] == {"version": 2}


def test_broken_probe_never_raises():
    monitor = get_system_health()
    monitor.register_probe("exploding", lambda: 1 / 0)  # type: ignore

    checks = {c["name"]: c for c in monitor.collect()["checks"]}
    assert checks["exploding"]["status"] == "down"
    assert "raised" in checks["exploding"]["detail"].lower()


def test_functions_from_registry():
    functions = _collect_functions()

    # Either the registry has real discoveries, or it degrades to an empty
    # list — it must never raise and always be list-shaped.
    assert isinstance(functions, list)
    for f in functions:
        assert f["name"]
        assert f["status"] in {"new", "existing", "removed"}
        assert f["kind"] in {"class", "function", "geospatial"}  # GEV agent


def test_mobile_folding_is_safe():
    mobile = _collect_mobile()

    assert isinstance(mobile, dict)
    assert "connected" in mobile and isinstance(mobile["connected"], bool)
    assert set(mobile) >= {
        "clients", "peak_clients", "commands_processed", "commands_per_second",
        "avg_latency_ms", "uptime_s", "channels",
    }
    # Channel snapshots are dicts (empty when agents are unstarted).
    assert isinstance(mobile["channels"].get("analytics"), dict)
    assert isinstance(mobile["channels"].get("dashboard"), dict)


def test_mobile_connected_state_tracks_clients():
    # Simulate a connected mobile client through the gateway agent.
    from server.systems.agent.mobile_gateway_agent import get_mobile_gateway
    gateway = get_mobile_gateway()
    gateway.on_client_connected()
    try:
        mobile = _collect_mobile()
        assert mobile["connected"] is True
        assert mobile["clients"] >= 1
        assert mobile["peak_clients"] >= 1
    finally:
        gateway.on_client_disconnected()


def test_phone_device_metrics_fold_into_snapshot():
    # The Flutter app pushes battery/CPU/memory on /ws/mobile/control; the
    # gateway stores them and the health snapshot must surface them.
    from server.systems.agent.mobile_gateway_agent import get_mobile_gateway
    gateway = get_mobile_gateway()
    gateway.on_client_connected()
    try:
        gateway.record_device_metrics({
            "platform": "android",
            "battery": 87,
            "charging": True,
            "cpu_percent": 12.5,
            "ram_percent": 61.0,
            "ram_used_gb": 4.2,
            "ram_total_gb": 8.0,
            "model": "Pixel 7",
            "manufacturer": "Google",
            "os_version": "Android 14",
        }, ts=1712345678.0)

        mobile = _collect_mobile()
        assert mobile["device"]["battery"] == 87
        assert mobile["device"]["cpu_percent"] == 12.5
        assert mobile["device"]["ram_total_gb"] == 8.0
        assert mobile["device"]["model"] == "Pixel 7"
        assert mobile["device_last_ts"] == 1712345678.0

        # And the full snapshot's mobile section carries it too.
        snap = get_system_health().collect()
        assert snap["mobile"]["device"]["charging"] is True
        assert snap["mobile"]["device_last_ts"] == 1712345678.0
    finally:
        gateway.on_client_disconnected()


def test_phone_device_metrics_absent_when_never_reported():
    from server.systems.agent.mobile_gateway_agent import get_mobile_gateway
    gateway = get_mobile_gateway()
    gateway.on_client_connected()
    try:
        # The gateway is a module singleton shared across tests — reset its
        # device fields so this test really starts from "never reported".
        gateway._telemetry.device = {}
        gateway._telemetry.device_last_ts = 0.0
        mobile = _collect_mobile()
        assert mobile["device"] == {}
        assert mobile["device_last_ts"] is None
    finally:
        gateway.on_client_disconnected()


def test_score_bounds_and_penalties():
    checks_ok = [_ok("fine"), _warn("warm"), _down("dead"), _unknown("?"), _ok("ok2")]
    base = _compute_score(
        {"cpu_percent": 5.0, "ram_percent": 20.0},
        [{"percent": 30.0}],
        checks_ok,
        {"connected": True},
    )
    assert 0 <= base <= 100

    # A heavily loaded machine with a dead subsystem scores lower.
    loaded = _compute_score(
        {"cpu_percent": 100.0, "ram_percent": 100.0},
        [{"percent": 100.0}],
        checks_ok,
        {"connected": True},
    )
    assert loaded < base


def test_history_accumulates():
    monitor = get_system_health()
    for _ in range(5):
        monitor.collect()

    hist = monitor.snapshot()["history"]
    assert len(hist["cpu"]) == 5
    assert len(hist["ram"]) == 5
    assert len(hist["mobile_clients"]) == 5
    # Every sample within sane utilization bounds.
    assert all(0 <= v <= 100 for v in hist["cpu"])
    assert all(0 <= v <= 100 for v in hist["ram"])


# ── Real Event Log feed (no synthetic events) ────────────────────────────────

import asyncio

from server.systems.signal_bus import bus as admin_signal_bus


class _FakeWS:
    """Captures frames broadcast by broadcast_brain_metrics."""

    def __init__(self):
        self.frames = []

    async def send_text(self, text: str) -> None:
        import json
        self.frames.append(json.loads(text))


async def _collect_real_events(monitor, snapshot, fake):
    # broadcast_brain_metrics fans out to the admin signal bus's connected
    # sockets (the real /ws/brain_metrics registry owned by server.main) —
    # attach the fake there so the broadcast path is exercised end-to-end.
    admin_signal_bus._connected_sockets.append(fake)
    try:
        await monitor._emit_real_events(snapshot)
    finally:
        if fake in admin_signal_bus._connected_sockets:
            admin_signal_bus._connected_sockets.remove(fake)


def test_first_frame_seeds_baseline_silently():
    """The very first frame must not burst events (baseline only)."""
    monitor = get_system_health()
    fake = _FakeWS()

    asyncio.run(_collect_real_events(monitor, {
        "ts": 1.0, "score": 90,
        "checks": [{"name": "brain", "status": "ok", "label": "Brain", "detail": "fine"}],
        "functions": [{"name": "agent_a"}, {"name": "brand_new_agent"}],
        "mobile": {"connected": True},
    }, fake))
    assert fake.frames == []
    assert monitor._seeded is True
    assert monitor._prev_functions == {"agent_a", "brand_new_agent"}
    assert monitor._prev_checks == {"brain": "ok"}
    assert monitor._prev_mobile_connected is True
    assert monitor._prev_score == 90


def test_real_events_emitted_on_check_flip():
    monitor = get_system_health()
    fake = _FakeWS()

    # Steady state first: all checks ok — nothing emitted.
    monitor._seeded = True
    monitor._prev_checks = {name: "ok" for name in PROBES}
    monitor._prev_functions = {"agent_a"}
    monitor._prev_mobile_connected = False
    monitor._prev_score = 90
    asyncio.run(_collect_real_events(monitor, {
        "ts": 1.0, "score": 90,
        "checks": [{"name": "brain", "status": "ok", "label": "Brain", "detail": "fine"}],
        "functions": [{"name": "agent_a"}],
        "mobile": {"connected": False},
    }, fake))
    assert fake.frames == []

    # A check flips down → exactly one HEALTH critical event.
    asyncio.run(_collect_real_events(monitor, {
        "ts": 2.0, "score": 90,
        "checks": [{"name": "brain", "status": "down", "label": "Brain", "detail": "dead"}],
        "functions": [{"name": "agent_a"}],
        "mobile": {"connected": False},
    }, fake))
    assert len(fake.frames) == 1
    ev = fake.frames[0]
    assert ev["type"] == "log_event" and ev["tag"] == "HEALTH"
    assert ev["severity"] == "critical"
    assert "brain" in ev["message"].lower() and "down" in ev["message"].lower()

    # Recovery flips back → info event.
    asyncio.run(_collect_real_events(monitor, {
        "ts": 3.0, "score": 90,
        "checks": [{"name": "brain", "status": "ok", "label": "Brain", "detail": "fine"}],
        "functions": [{"name": "agent_a"}],
        "mobile": {"connected": False},
    }, fake))
    assert len(fake.frames) == 2
    assert fake.frames[-1]["severity"] == "info"


def test_real_event_new_function_discovered():
    monitor = get_system_health()
    fake = _FakeWS()

    monitor._seeded = True
    monitor._prev_checks = {name: "ok" for name in PROBES}
    monitor._prev_functions = {"agent_a"}
    monitor._prev_mobile_connected = False
    monitor._prev_score = 90

    # First sight of a brand-new function → FUNCTIONS event (agent_a was
    # already known, so only brand_new_agent is reported).
    asyncio.run(_collect_real_events(monitor, {
        "ts": 1.0, "score": 90,
        "checks": [{"name": "brain", "status": "ok", "label": "Brain", "detail": "fine"}],
        "functions": [{"name": "agent_a"}, {"name": "brand_new_agent"}],
        "mobile": {"connected": False},
    }, fake))
    assert len(fake.frames) == 1
    ev = fake.frames[0]
    assert ev["tag"] == "FUNCTIONS" and ev["severity"] == "info"
    assert "brand_new_agent" in ev["message"]


def test_real_event_mobile_connect_disconnect():
    monitor = get_system_health()
    fake = _FakeWS()

    monitor._seeded = True
    monitor._prev_checks = {name: "ok" for name in PROBES}
    monitor._prev_functions = {"agent_a"}
    monitor._prev_mobile_connected = False
    monitor._prev_score = 90

    base = {
        "ts": 1.0, "score": 90,
        "checks": [{"name": "brain", "status": "ok", "label": "Brain", "detail": "fine"}],
        "functions": [{"name": "agent_a"}],
    }

    # Connect → info event.
    asyncio.run(_collect_real_events(monitor, {**base, "ts": 2.0, "mobile": {"connected": True}}, fake))
    assert len(fake.frames) == 1
    assert fake.frames[0]["tag"] == "MOBILE" and fake.frames[0]["severity"] == "info"
    assert "connected" in fake.frames[0]["message"].lower()

    # Steady connected → nothing new.
    asyncio.run(_collect_real_events(monitor, {**base, "ts": 3.0, "mobile": {"connected": True}}, fake))
    assert len(fake.frames) == 1

    # Disconnect → warn event.
    asyncio.run(_collect_real_events(monitor, {**base, "ts": 4.0, "mobile": {"connected": False}}, fake))
    assert len(fake.frames) == 2
    assert fake.frames[-1]["severity"] == "warn"
    assert "disconnected" in fake.frames[-1]["message"].lower()


def test_real_event_score_crossing_threshold():
    monitor = get_system_health()
    fake = _FakeWS()

    monitor._seeded = True
    monitor._prev_checks = {name: "ok" for name in PROBES}
    monitor._prev_functions = {"agent_a"}
    monitor._prev_mobile_connected = False
    monitor._prev_score = 90

    base = {
        "checks": [{"name": "brain", "status": "ok", "label": "Brain", "detail": "fine"}],
        "functions": [{"name": "agent_a"}],
        "mobile": {"connected": False},
    }

    # Drop below 60 → critical SYSTEM event.
    asyncio.run(_collect_real_events(monitor, {**base, "ts": 1.0, "score": 45}, fake))
    assert len(fake.frames) == 1
    ev = fake.frames[0]
    assert ev["tag"] == "SYSTEM" and ev["severity"] == "critical"
    assert "45" in ev["message"]

    # Recovery above 60 → info event.
    asyncio.run(_collect_real_events(monitor, {**base, "ts": 2.0, "score": 80}, fake))
    assert len(fake.frames) == 2
    assert fake.frames[-1]["severity"] == "info"
    assert "recovered" in fake.frames[-1]["message"].lower()
