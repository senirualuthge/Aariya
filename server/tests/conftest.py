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
