"""Tests for the real event-log REST feed (mobile Companion activity strip).

The endpoint reads the SAME signal-bus ring the dashboard Event Log consumes
— no fabricated events. We push REAL signals through the bus, then assert the
endpoint returns them newest-first, shaped for the phone.

Follows the suite convention: sync `def test_` wrappers calling asyncio.run.
"""

import asyncio
import time

from server.routers.events_router import events_latest
from server.systems.signal_bus import bus


def _clear_ring() -> None:
    bus.active_signals.clear()


async def _emit(source: str, severity: str, title: str, **extra) -> None:
    """Emit a real event through the shared helper (the exact path producers use)."""
    from server.systems.signal_bus import emit_real_event
    await emit_real_event(source, severity, title, extra or None)


async def _returns_real_events_newest_first() -> None:
    _clear_ring()
    await _emit("GOVERNANCE", "warn", "Age policy set to 18+", age_band="18+")
    await _emit("PLANNER", "info", "New goal: write more tests", goal_type="growth")
    await _emit("DAEMON", "info", "Proactive (insight): hello")

    resp = await events_latest(limit=10)
    events = resp["events"]
    assert len(events) == 3

    # Newest first (DAEMON was emitted last).
    assert events[0]["tag"] == "DAEMON"
    assert events[0]["text"] == "Proactive (insight): hello"
    assert events[1]["tag"] == "PLANNER"
    assert events[2]["tag"] == "GOVERNANCE"

    # Every entry carries the phone strip's contract.
    for e in events:
        assert "id" in e and e["id"]
        assert isinstance(e["ts"], float) and e["ts"] > 0
        assert e["severity"] in ("info", "warn", "critical")
        assert e["text"]


async def _respects_limit() -> None:
    _clear_ring()
    for i in range(5):
        await _emit("MODEL", "info", f"Retrain {i}", snapshot_id=i)

    assert len((await events_latest(limit=2))["events"]) == 2
    assert len((await events_latest(limit=20))["events"]) == 5


async def _empty_ring_returns_empty_list() -> None:
    _clear_ring()
    resp = await events_latest(limit=10)
    assert resp == {"events": []}


async def _filters_by_sources() -> None:
    """The phone asks for autonomy/governance tags only — other systems
    (brain turns, mobile turns, health) must be excluded from the strip."""
    _clear_ring()
    await _emit("GOVERNANCE", "warn", "Consent revoked for memory storage")
    await _emit("PLANNER", "info", "New goal: learn more")
    await _emit("BRAIN", "info", "Turn complete — trust 0.71")
    await _emit("MOBILE", "info", "Mobile turn — calm")
    await _emit("HEALTH", "warn", "RAM crossing 90%")

    resp = await events_latest(limit=10, sources="DAEMON,PLANNER,GOVERNANCE")
    tags = [e["tag"] for e in resp["events"]]
    assert tags == ["PLANNER", "GOVERNANCE"]
    assert "BRAIN" not in tags and "MOBILE" not in tags and "HEALTH" not in tags

    # Empty sources = no filter (dashboard-like full log).
    resp_all = await events_latest(limit=10)
    assert len(resp_all["events"]) == 5


async def _surfaces_payload_via_title_not_fabricated() -> None:
    """The title comes from the real payload — the ring holds actual events,
    so a signal without a title still surfaces its type, never a fake line."""
    _clear_ring()
    bus.active_signals.append({
        "id": "sig_test",
        "timestamp": time.time(),
        "type": "telemetry",
        "severity": "info",
        "source": {"system": "HEALTH"},
        "status": "new",
        "payload": {"no_title": True},
    })
    events = (await events_latest(limit=10))["events"]
    assert events[0]["tag"] == "HEALTH"
    assert events[0]["text"] == "telemetry"


def test_events_latest_returns_real_events_newest_first() -> None:
    asyncio.run(_returns_real_events_newest_first())


def test_events_latest_respects_limit() -> None:
    asyncio.run(_respects_limit())


def test_events_latest_empty_ring_returns_empty_list() -> None:
    asyncio.run(_empty_ring_returns_empty_list())


def test_events_latest_filters_by_sources() -> None:
    asyncio.run(_filters_by_sources())


def test_events_latest_surfaces_payload_via_title_not_fabricated() -> None:
    asyncio.run(_surfaces_payload_via_title_not_fabricated())
