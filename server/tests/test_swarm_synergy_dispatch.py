"""Tests for server/systems/gev/swarm_synergy.py.

Covers the dispatch seam added so GEV triggers can actually reach the agent
swarm: rule matching, cooldown, template fill, the callback contract, and the
honest status returned by ``execute_dispatch`` (ok / unsupported / error).

Trigger *events* here are test fixtures; nothing is fabricated about runtime
state — handlers are injected fakes, and execution status is asserted directly.
"""

import asyncio
import types

import pytest

from server.systems.gev import swarm_synergy as ss


class _FakeGeofence:
    """Minimal stand-in for GeofenceEngine (records the trigger callback)."""

    def __init__(self):
        self.callback = None

    def on_trigger(self, callback):
        self.callback = callback


def _quake_event(magnitude=6.7, place="Testville"):
    return {
        "layer": "earthquakes",
        "rule_name": "quake-watch",
        "entities": [{"data": {"magnitude": magnitude, "place": place, "lat": 1.0, "lon": 2.0}}],
    }


@pytest.fixture()
def bridge(monkeypatch):
    monkeypatch.delenv("AARIYA_SWARM_SYNERGY_DISPATCH", raising=False)
    return ss.SwarmSynergyBridge(geofence_engine=_FakeGeofence())


# ── Rule matching / dispatch spec generation ─────────────────────────────────

def test_trigger_builds_dispatch_requests_and_fills_templates(bridge):
    events = []
    bridge.on_dispatch(events.append)

    bridge._on_geofence_trigger(_quake_event())

    assert len(events) == 1
    event = events[0]
    assert event["synergy_rule"] == "earthquake_major"
    assert event["priority"] == "critical"
    assert len(event["dispatch_requests"]) == 2

    web = next(r for r in event["dispatch_requests"] if r["agent_type"] == "web_search")
    # {place} / {magnitude} are substituted from the real entity data.
    assert "Testville" in web["params"]["query_template"]
    assert "6.7" in web["params"]["query_template"]


def test_cooldown_suppresses_immediate_redispatch(bridge):
    events = []
    bridge.on_dispatch(events.append)

    bridge._on_geofence_trigger(_quake_event())
    bridge._on_geofence_trigger(_quake_event())

    assert len(events) == 1  # second trigger inside the 600s cooldown


def test_condition_mismatch_does_not_dispatch(bridge):
    events = []
    bridge.on_dispatch(events.append)

    bridge._on_geofence_trigger(_quake_event(magnitude=4.0))  # below the M6.0 gate

    assert events == []


def test_layer_mismatch_does_not_dispatch(bridge):
    events = []
    bridge.on_dispatch(events.append)

    bridge._on_geofence_trigger({"layer": "no_such_layer", "entities": []})

    assert events == []


def test_conditional_rule_without_entities_does_not_dispatch(bridge):
    """A conditional rule can't be evaluated without an entity — it must not fire."""
    events = []
    bridge.on_dispatch(events.append)

    bridge._on_geofence_trigger({"layer": "vessels", "entities": []})

    assert events == []


def test_conditional_rule_matching_condition_dispatches(bridge):
    events = []
    bridge.on_dispatch(events.append)

    bridge._on_geofence_trigger({
        "layer": "vessels",
        "rule_name": "restricted-zone",
        "entities": [{"data": {"zone_type": "restricted", "name": "ShipA", "zone_name": "Z1"}}],
    })

    assert len(events) == 1
    assert events[0]["synergy_rule"] == "vessel_restricted_zone"


def test_callback_error_is_isolated(bridge):
    good = []
    bridge.on_dispatch(lambda _e: (_ for _ in ()).throw(RuntimeError("boom")))
    bridge.on_dispatch(good.append)

    bridge._on_geofence_trigger(_quake_event())  # must not raise

    assert len(good) == 1


# ── Honest execution ─────────────────────────────────────────────────────────

def test_execute_dispatch_unsupported_without_handler(bridge):
    result = asyncio.run(bridge.execute_dispatch(
        {"agent_type": "data_analysis", "task": "pull data", "params": {}},
    ))

    assert result["status"] == "unsupported"
    assert result["agent_type"] == "data_analysis"
    assert "reason" in result


def test_execute_dispatch_runs_sync_handler(bridge):
    seen = {}

    def handler(request):
        seen["request"] = request
        return {"answer": 42}

    bridge.register_handler("web_search", handler)
    result = asyncio.run(bridge.execute_dispatch(
        {"agent_type": "web_search", "task": "find news", "params": {}},
    ))

    assert result["status"] == "ok"
    assert result["result"] == {"answer": 42}
    assert seen["request"]["task"] == "find news"
    assert bridge.get_execution_log()[-1]["status"] == "ok"


def test_execute_dispatch_runs_async_handler(bridge):
    async def handler(_request):
        return "async-result"

    bridge.register_handler("web_search", handler)
    result = asyncio.run(bridge.execute_dispatch(
        {"agent_type": "web_search", "task": "t", "params": {}},
    ))

    assert result["status"] == "ok"
    assert result["result"] == "async-result"


def test_execute_dispatch_reports_handler_error(bridge):
    def handler(_request):
        raise ValueError("handler exploded")

    bridge.register_handler("web_search", handler)
    result = asyncio.run(bridge.execute_dispatch(
        {"agent_type": "web_search", "task": "t", "params": {}},
    ))

    assert result["status"] == "error"
    assert "handler exploded" in result["error"]


def test_register_default_handlers_only_binds_real_agents(bridge):
    registered = bridge.register_default_handlers()

    # web_search is backed by the real research agent; the other preset types
    # have no genuine implementation and must stay unsupported.
    assert registered == ["web_search"]
    assert bridge.has_handler("web_search")
    assert not bridge.has_handler("data_analysis")
    assert set(ss.build_default_handlers()) == {"web_search"}


# ── Env gate ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("YES", True),
    ("0", False), ("false", False), ("off", False), ("", False),
])
def test_dispatch_enabled_env_gate(monkeypatch, value, expected):
    monkeypatch.setenv("AARIYA_SWARM_SYNERGY_DISPATCH", value)
    assert ss.synergy_dispatch_enabled() is expected


def test_dispatch_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AARIYA_SWARM_SYNERGY_DISPATCH", raising=False)
    assert ss.synergy_dispatch_enabled() is False


# ── GEVAgent scheduling (no agent construction) ──────────────────────────────

def test_gev_agent_schedules_dispatch_on_running_loop():
    from server.systems.gev.gev_agent import GEVAgent

    executed = []

    class _FakeSynergy:
        async def execute_dispatch(self, request):
            executed.append(request["agent_type"])
            return {"status": "ok"}

    fake = types.SimpleNamespace(_synergy=_FakeSynergy())
    # Bind the real helper so the scheduled task has something to await.
    fake._execute_dispatch_request = types.MethodType(
        GEVAgent._execute_dispatch_request, fake,
    )

    async def scenario():
        GEVAgent._on_synergy_dispatch(fake, {
            "synergy_rule": "earthquake_major",
            "dispatch_requests": [
                {"agent_type": "web_search", "task": "a", "params": {}},
                {"agent_type": "web_search", "task": "b", "params": {}},
            ],
        })
        await asyncio.sleep(0)  # let the scheduled tasks run

    asyncio.run(scenario())

    assert executed == ["web_search", "web_search"]


def test_gev_agent_scheduling_is_a_noop_without_requests():
    from server.systems.gev.gev_agent import GEVAgent

    fake = types.SimpleNamespace(_synergy=types.SimpleNamespace())
    # No running loop and no requests -> must return quietly, not raise.
    GEVAgent._on_synergy_dispatch(fake, {"dispatch_requests": []})
