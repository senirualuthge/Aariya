"""Shared pytest fixtures for the server/tests suite.

Makes the project root importable (tests use `from server...`), and provides
isolation helpers so tests never touch real LLM endpoints or dev databases.
"""

import os
import sys

import pytest

# Make the project root importable regardless of where pytest is invoked from.
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import server.db as server_db  # noqa: E402  (needs the path bootstrap above)


@pytest.fixture()
def offline_llm(monkeypatch):
    """Point every LLM call at an unreachable port so tests exercise the
    template/fallback paths instead of the network. Restored after the test."""
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1/v1")


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """Redirect server.db to a throwaway SQLite file and initialize it.

    Anything that goes through get_db_connection() (the autonomy store, etc.)
    reads DB_PATH at call time, so patching the module constant covers it.
    Restored after the test — dev data (data/brain_v4.db) is never touched.
    """
    monkeypatch.setattr(server_db, "DB_PATH", str(tmp_path / "brain_test.db"))
    server_db.init_db()
    return server_db


def _tmp_postgres_sqlite(self, tmp_path):
    import sqlite3
    # Hermetic test store: force the SQLite fallback dialect. Without this, a
    # developer machine running live Postgres (per .env) would silently bind
    # the fixture to it — the exact mismatch that hid the pattern_memory bug.
    self.use_fallback = True
    self.pool = None
    conn = sqlite3.connect(str(tmp_path / "analytics.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    self.sqlite_conn = conn


def _tmp_postgres_init(self):
    """Replacement Postgres init: never connects, always uses the tmp store."""
    # Called from __init__ when use_fallback is False; must force fallback.
    _tmp_postgres_sqlite(self, self._pytest_tmp_path)


@pytest.fixture()
def fresh_postgres_store(tmp_path, monkeypatch):
    """Point the PostgresManager singleton at a throwaway SQLite file and
    reset dependent singletons (memory hierarchy) so they bind to it."""
    import server.infrastructure.postgres_manager as pgm
    import server.systems.memory_hierarchy as mh_mod

    old_singleton = pgm._postgres_manager
    old_mh = mh_mod._memory_hierarchy
    # Patch the POSTGRES init path (not just the fallback): when a live
    # Postgres is reachable, __init__ takes that path and would silently bind
    # tests to the developer's real database. Both paths now land on the
    # throwaway SQLite store.
    pgm.PostgresManager._pytest_tmp_path = tmp_path
    monkeypatch.setattr(pgm.PostgresManager, "_init_postgres_pool",
                        lambda self: _tmp_postgres_init(self))
    monkeypatch.setattr(pgm.PostgresManager, "_init_sqlite_fallback",
                        lambda self: _tmp_postgres_sqlite(self, tmp_path))
    pgm._postgres_manager = None
    mh_mod._memory_hierarchy = None
    yield
    pgm._postgres_manager = old_singleton
    mh_mod._memory_hierarchy = old_mh
    if hasattr(pgm.PostgresManager, "_pytest_tmp_path"):
        del pgm.PostgresManager._pytest_tmp_path


@pytest.fixture()
def mock_security_safe(monkeypatch):
    """Stub the security-agent swarm to always return SAFE so that tests
    asserting on exact reply text aren't polluted by the security-prefix
    injection that fires when run_security_agents detects a HIGH-risk event
    (e.g. an unexpected network connection on the CI runner)."""
    from server.systems.swarm.orchestrator import SwarmSystem

    async def _always_safe(self, data):  # noqa: ARG001
        return {"risk": {"risk_level": "SAFE"}, "issues": []}

    monkeypatch.setattr(SwarmSystem, "run_security_agents", _always_safe)
