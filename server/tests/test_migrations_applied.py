"""
Migration runner wiring + analytics-store schema integrity:

The SQL migrations under server/migrations/ define trust_history,
contradiction_history, episodic_memory, pattern_memory, audit_logs,
router_logs, interaction_outcomes and memory_recall_log. Until the startup
hook existed, NOTHING ever ran them — every module querying those tables
(postgres-manager users: memory hierarchy, compliance export, trust system)
failed with "no such table".
"""

import json

import pytest


def test_migrations_create_all_analytics_tables(fresh_postgres_store):
    from server.migrations import MigrationRunner

    runner = MigrationRunner()
    applied = runner.run_pending_migrations()
    assert applied >= 2  # both migration files apply cleanly

    conn = runner.db.get_connection()
    names = {r[0] for r in conn.execute(  # type: ignore
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for table in ("trust_history", "contradiction_history", "episodic_memory",
                  "pattern_memory", "audit_logs", "interaction_outcomes"):
        assert table in names, f"{table} missing after migrations"
    conn.close()  # type: ignore

    # Idempotent — second run applies nothing.
    assert MigrationRunner().run_pending_migrations() == 0


def test_memory_hierarchy_survives_roundtrip(fresh_postgres_store):
    """store_episodic → recall_episodic must work now that the table exists."""
    from server.migrations import MigrationRunner
    MigrationRunner().run_pending_migrations()

    from server.systems.memory_hierarchy import get_memory_hierarchy

    mh = get_memory_hierarchy()
    mh.store_episodic("user_default", "sess-1", "walked along the pier",
                      emotional_context="content", importance=0.7)
    rows = mh.recall_episodic("user_default", limit=5)
    assert any("pier" in (r.get("summary") or "") for r in rows)


def test_lifespan_runs_migrations():
    """Startup source must invoke the migration runner (regression guard)."""
    import inspect
    from server import main as main_module
    src = inspect.getsource(main_module.lifespan)
    assert "run_pending_migrations" in src
