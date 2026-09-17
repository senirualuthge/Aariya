"""
test_evolution_events.py
────────────────────────
Tests for server/meta/evolution_loop.py's real Event Log emission — the Darwin
engine must push genuine `signal` frames into the dashboard Event Log when it
actually self-improves:

  • spawn     — a new agent module was written (trigger_spawner ok, not skipped)
  • retire    — an agent transitioned into the REWRITE lifecycle state
  • rewrite   — a decaying agent was successfully rewritten (version bump)

Also verifies the Functions grid refresh hook (invalidate_functions) so the
System Health Functions grid reflects self-improvement on the next frame.
"""

import asyncio

import pytest

from server.meta import evolution_loop as evo
from server.systems.system_health import get_system_health


class _FakeLogSocket:
    """Captures frames pushed by admin_signal_bus.emit_signal."""

    def __init__(self):
        self.frames = []

    async def send_json(self, obj):
        self.frames.append(obj)


def _signal_events(sock):
    return [f["signal"] for f in sock.frames if f.get("type") == "signal"]


# ── Evolution loop event emission ────────────────────────────────────────────

class _FakeRegistry:
    """Registry stub that returns a fixed active-agent list."""

    def __init__(self, agents):
        self._agents = agents

    def get_active_agents(self):
        return list(self._agents)


class _StopLoop(Exception):
    """Raised by the stubbed asyncio.sleep to end the infinite evolution loop."""


@pytest.fixture(autouse=True)
def _reset_transitions():
    """Reset module-level transition tracking between tests."""
    evo._last_lifecycle.clear()
    yield


async def _run_one_evolution_tick(monkeypatch, agents=None, gap_result=None):
    """
    Drive evolution_tick() through exactly one pass by stubbing every real
    dependency with the monkeypatch fixture (auto-restored after the test), then
    stop the loop (the stubbed asyncio.sleep raises after the body).

    Never mutates module or process globals — every stub is scoped to the test.
    """
    import server.meta.evolution_loop as evo_mod

    # Fitness: one weak agent that classifies as REWRITE.
    weak = {"name": "DecayingAgent"}
    monkeypatch.setattr(evo_mod, "get_registry", lambda: _FakeRegistry(agents or [weak]))
    monkeypatch.setattr(evo_mod, "compute_score", lambda name: 0.1)
    monkeypatch.setattr(evo_mod, "classify_state", lambda score: "REWRITE")
    # Rewriter: succeed (records version bump + emits rewrite event).
    monkeypatch.setattr(evo_mod.PolicyEngine, "can_rewrite", staticmethod(lambda agent: True))
    monkeypatch.setattr(evo_mod, "rewrite_agent", lambda agent: True)
    # §71 verification gate: pass (these tests cover EVENT emission, not
    # verification — test_accessfiles_final_gaps.py covers the real gate).
    monkeypatch.setattr(evo_mod, "_verify_rewritten_agent",
                        lambda agent: {"ok": True, "checks": [], "failures": []})
    # Spawner: either a real spawn or a skipped one (already on disk).
    monkeypatch.setattr(evo_mod, "scan_for_gaps",
                        lambda _a: ["memory_retrieval"] if gap_result is not None else [])
    if gap_result is not None:
        monkeypatch.setattr(evo_mod, "trigger_spawner", lambda _gap: dict(gap_result))
    # Redis publish: never touches real Redis in tests.
    monkeypatch.setattr(evo_mod, "publish", lambda *_a, **_k: None)
    # Stop after one body pass. Patched via monkeypatch so asyncio.sleep is
    # restored for every other test in the process afterwards.
    async def _stop(*_a, **_k):
        raise _StopLoop()
    monkeypatch.setattr(evo_mod.asyncio, "sleep", _stop)

    sock = _FakeLogSocket()
    from server.systems.signal_bus import bus as admin_signal_bus
    admin_signal_bus._connected_sockets.append(sock)
    try:
        with pytest.raises(_StopLoop):
            await evo_mod.evolution_tick()
    finally:
        if sock in admin_signal_bus._connected_sockets:
            admin_signal_bus._connected_sockets.remove(sock)
    return sock


def test_evolution_emits_retire_and_rewrite_events(monkeypatch):
    sock = asyncio.run(_run_one_evolution_tick(monkeypatch, gap_result=None))

    signals = _signal_events(sock)
    evo_sigs = [s for s in signals if s["source"]["system"] == "EVOLUTION"]
    # The weak agent decayed to REWRITE (retire) and the rewrite landed (version).
    assert len(evo_sigs) == 2, evo_sigs

    retire = next(s for s in evo_sigs if "Retiring weak agent" in s["payload"]["title"])
    assert retire["severity"] == "warn"
    assert retire["payload"]["agent"] == "DecayingAgent"
    assert retire["payload"]["state"] == "REWRITE"

    rewrite = next(s for s in evo_sigs if "Rewrote weak agent" in s["payload"]["title"])
    assert rewrite["severity"] == "info"
    assert rewrite["payload"]["version"] == 2  # 1 + 1 from the successful rewrite
    assert rewrite["timestamp"] > 0


def test_evolution_does_not_reemit_retire_every_tick(monkeypatch):
    # First tick: agent already retired (recorded in _last_lifecycle).
    # A second pass over the same state must NOT emit the retire event again.
    async def _two_passes():
        sock1 = await _run_one_evolution_tick(monkeypatch, gap_result=None)
        # Module state now says DecayingAgent was REWRITE — run again.
        sock2 = await _run_one_evolution_tick(monkeypatch, gap_result=None)
        return sock1, sock2

    sock1, sock2 = asyncio.run(_two_passes())

    def _retires(sock):
        return [s for s in _signal_events(sock)
                if s["source"]["system"] == "EVOLUTION"
                and "Retiring weak agent" in s["payload"]["title"]]

    assert len(_retires(sock1)) == 1   # transition reported once
    assert len(_retires(sock2)) == 0   # same state → no re-fire
    # The rewrite DOES re-fire per pass (each pass re-runs the rewriter) —
    # but only if a rewrite actually happened; assert at least one rewrite.
    assert any("Rewrote weak agent" in s["payload"]["title"]
               for s in _signal_events(sock2))


def test_evolution_emits_spawn_event_for_real_spawn(monkeypatch):
    gap_result = {
        "ok": True,
        "capability": "memory_retrieval",
        "method": "template",
        "agent_name": "MemoryRetrievalAgent",
        "file": "/tmp/generated/memory_retrieval_agent.py",
    }
    sock = asyncio.run(_run_one_evolution_tick(monkeypatch, gap_result=gap_result))

    evo_sigs = [s for s in _signal_events(sock) if s["source"]["system"] == "EVOLUTION"]
    spawn = next(s for s in evo_sigs if "Spawned new agent" in s["payload"]["title"])
    assert spawn["severity"] == "info"
    assert spawn["payload"]["capability"] == "memory_retrieval"
    assert spawn["payload"]["agent_name"] == "MemoryRetrievalAgent"
    assert spawn["payload"]["method"] == "template"


def test_evolution_skips_spawn_event_when_already_on_disk(monkeypatch):
    # skipped=True means the file already existed — NOT a new spawn, so no event.
    gap_result = {"ok": True, "skipped": True, "capability": "dialogue",
                  "file": "/tmp/generated/dialogue_agent.py"}
    sock = asyncio.run(_run_one_evolution_tick(monkeypatch, gap_result=gap_result))

    spawns = [s for s in _signal_events(sock)
              if s["source"]["system"] == "EVOLUTION"
              and "Spawned new agent" in s["payload"]["title"]]
    assert spawns == []


def test_evolution_emits_nothing_on_failed_spawn(monkeypatch):
    gap_result = {"ok": False, "error": "cooldown", "capability": "dialogue"}
    sock = asyncio.run(_run_one_evolution_tick(monkeypatch, gap_result=gap_result))

    spawns = [s for s in _signal_events(sock)
              if s["source"]["system"] == "EVOLUTION"
              and "Spawned new agent" in s["payload"]["title"]]
    assert spawns == []


# ── Functions grid refresh hook ──────────────────────────────────────────────

def test_invalidate_functions_forces_next_collect_refresh():
    monitor = get_system_health()
    monitor.collect()  # populates the cached functions list + timestamp
    assert monitor._functions_cache  # non-empty after a real collect

    monitor.invalidate_functions()
    assert monitor._functions_cache == []
    assert monitor._last_functions_refresh == 0.0

    # Next collect rebuilds the cache from the registry.
    snap = monitor.collect()
    assert monitor._functions_cache  # rebuilt
    assert snap["functions"] is monitor._functions_cache


def test_bump_functions_grid_calls_invalidate():
    monitor = get_system_health()
    monitor.collect()
    assert monitor._functions_cache

    # Simulate what evolution_loop._bump_functions_grid does.
    import server.meta.evolution_loop as evo_mod
    evo_mod._bump_functions_grid()
    assert monitor._functions_cache == []
    assert monitor._last_functions_refresh == 0.0
