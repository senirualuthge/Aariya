"""
Multi-user isolation tests (Track A — partials plan).

Verifies the identity plumbing added in A1/A2 actually isolates tenants:

  • AutonomyStore keeps goals and snapshots separate per user_id.
  • AutonomyDaemon honours an explicit user_id, then AARIYA_USER_ID, then the
    legacy 'user_default' fallback.
  • AutonomousManager drives the proactive loop with its configured user_id.

Uses the shared `isolated_db` fixture so the real dev database is never touched.

Run: python -m pytest server/tests/test_multi_user_isolation.py -v
"""

import asyncio

import pytest

from server.autonomy.state import AutonomyStore


@pytest.fixture()
def store(isolated_db):
    return AutonomyStore()


@pytest.fixture()
def clean_singletons():
    """Don't leak daemon / proactive-engine / guard singletons between tests."""
    yield
    from server.autonomy.daemon import set_daemon
    from server.systems.proactive import engine as _engine
    from server.safety import initiative_guard as _guard
    set_daemon(None)
    _engine._proactive_engines.clear()
    _guard._initiative_guard = None


# ── Store isolation ──────────────────────────────────────────────────────────

def test_goals_are_isolated_per_user(store):
    store.add_goal("alice's goal", "self", "test", user_id="alice")
    store.add_goal("bob's goal", "self", "test", user_id="bob")

    alice = store.list_goals(user_id="alice")
    bob = store.list_goals(user_id="bob")

    assert [g["description"] for g in alice] == ["alice's goal"]
    assert [g["description"] for g in bob] == ["bob's goal"]
    assert store.list_goals(user_id="carol") == []


def test_snapshots_are_isolated_per_user(store):
    store.save_snapshot("alice", valence=0.7, arousal=0.2, trust=0.8)
    store.save_snapshot("bob", valence=-0.6, arousal=0.9, trust=0.3)

    a = store.get_latest_snapshot("alice")
    b = store.get_latest_snapshot("bob")

    assert abs(a["valence"] - 0.7) < 1e-6
    assert abs(b["valence"] - (-0.6)) < 1e-6
    assert store.get_latest_snapshot("carol") is None


# ── Daemon user_id resolution ────────────────────────────────────────────────

def test_daemon_honours_explicit_user_id(clean_singletons):
    from server.autonomy.daemon import AutonomyDaemon
    daemon = AutonomyDaemon(broadcast=lambda msg: None, user_id="alice")
    assert daemon.user_id == "alice"


def test_daemon_honours_env_user_id(clean_singletons, monkeypatch):
    from server.autonomy.daemon import AutonomyDaemon
    monkeypatch.setenv("AARIYA_USER_ID", "env_user")
    daemon = AutonomyDaemon(broadcast=lambda msg: None)
    assert daemon.user_id == "env_user"


def test_daemon_defaults_to_legacy_id(clean_singletons, monkeypatch):
    from server.autonomy.daemon import AutonomyDaemon
    monkeypatch.delenv("AARIYA_USER_ID", raising=False)
    daemon = AutonomyDaemon(broadcast=lambda msg: None)
    assert daemon.user_id == "user_default"


# ── Manager drives the loop with its tenant ──────────────────────────────────

def test_manager_drives_loop_with_configured_user_id(monkeypatch):
    from server.autonomy.manager import AutonomousManager

    captured = {}

    async def fake_tick_user(uid):
        captured["uid"] = uid

    mgr = AutonomousManager(callback=lambda *a, **k: None, user_id="alice")
    monkeypatch.setattr(mgr.loop, "tick_user", fake_tick_user)
    mgr.is_running = True

    asyncio.run(mgr.tick())
    assert captured["uid"] == "alice"
