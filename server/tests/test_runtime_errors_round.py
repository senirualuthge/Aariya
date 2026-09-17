"""
Gap round: runtime errors surfaced by the live server after migrations ran.

  * RedisManager phantom methods — state_machine / contradiction_detector /
    TrustSystem called get_session_state / update_session_field /
    get_contradiction_history / set_contradiction_history, none of which
    existed (AttributeError at runtime).
  * ConsciousLoop tick crashed ('NoneType' has no generate_plan) whenever the
    observation-only daemon loop found insights — the autonomy daemon passes
    planner=None by design.
  * memory_hierarchy.decay used GREATEST() — Postgres-only; every decay pass
    failed against the SQLite fallback store.
"""

import asyncio
import time

import pytest


def test_redis_manager_phantom_methods_exist():
    from server.infrastructure.redis_manager import get_redis
    r = get_redis()

    # Session-state dict roundtrip + field update
    assert r.get_session_state("state:t-user") is None
    r.update_session_field("state:t-user", "current_tier", "established")
    st = r.get_session_state("state:t-user")
    assert isinstance(st, dict) and st["current_tier"] == "established"
    r.update_session_field("state:t-user", "current_tier", "trusted")
    st2 = r.get_session_state("state:t-user")
    assert st2 is not None and st2["current_tier"] == "trusted"

    # Contradiction EMA float roundtrip + coercion safety
    assert r.get_contradiction_history("c-user") is None
    r.set_contradiction_history("c-user", 0.42)
    ema = r.get_contradiction_history("c-user")
    assert ema is not None and abs(ema - 0.42) < 1e-9


def test_conscious_loop_tick_survives_without_planner():
    """The daemon registers sources with planner=None; a tick that finds an
    insight must emit it via on_tick instead of crashing."""
    from server.systems.cognition.conscious_loop import ConsciousLoop

    async def failing_source():
        return {"needs_attention": True, "detail": "disk almost full"}

    seen = []

    async def on_tick(result):
        seen.append(result)

    loop = ConsciousLoop(reflection=None, planner=None,
                         interval=1.0, on_tick=on_tick)
    loop.register_source("filesystem", failing_source)

    result = asyncio.new_event_loop().run_until_complete(loop.tick())
    assert result["actions"] == []
    assert "attention" in result["based_on"]
    assert seen and seen[0]["insights"][0]["source"] == "filesystem"


def test_decay_works_on_sqlite_store(fresh_postgres_store):
    """decay() must not blow up on GREATEST() and must actually lower old
    rows' importance while respecting the floor."""
    from server.migrations import MigrationRunner
    MigrationRunner().run_pending_migrations()

    from server.infrastructure.postgres_manager import get_postgres
    db = get_postgres()
    old_ts = time.time() - 400 * 86400  # far beyond one half-life
    ok = db.execute_update(
        "INSERT INTO episodic_memory (user_id, session_id, summary, "
        "importance, timestamp) VALUES (?, ?, ?, ?, ?)",
        ("u-decay", "s", "ancient event", 1.0, old_ts))
    assert ok, "episodic insert must succeed"
    db.execute_update(
        "INSERT INTO pattern_memory (user_id, pattern_type, "
        "pattern_description, confidence, last_observed) "
        "VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
        ("u-decay", "behavioral", "fresh pattern", 1.0))

    from server.systems.memory_hierarchy import MemoryHierarchy
    mh = MemoryHierarchy()
    result = mh.decay(days=30.0, floor=0.05)
    assert result["episodic_decayed"] >= 1

    rows_old = db.execute_query(
        "SELECT importance FROM episodic_memory WHERE summary='ancient event'")
    assert rows_old, "decayed row must exist"
    assert abs(rows_old[0]["importance"] - 0.05) < 0.02  # floored at the minimum

    rows_fresh = db.execute_query(
        "SELECT confidence FROM pattern_memory WHERE pattern_description='fresh pattern'")
    assert rows_fresh, "fresh pattern row must exist"
    assert float(rows_fresh[0]["confidence"]) >= 0.999  # recent → essentially untouched
