"""PostgresManager SQL dialect conversion (SQLite dialect → Postgres-native).

The project's SQL (migrations + memory hierarchy + trust system …) is written
in the SQLite dialect. The manager must convert it at the single choke point
so Postgres deployments get native SQL while the SQLite fallback keeps the
dialect it speaks natively. Regression for the silent pattern_memory /
episodic_memory write failures against live Postgres.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.infrastructure.postgres_manager import PostgresManager


def test_placeholders_become_percent_s_outside_literals():
    sql = "INSERT INTO t (a, b) VALUES (?, ?)"
    assert PostgresManager.sqlite_to_postgres(sql) == \
        "INSERT INTO t (a, b) VALUES (%s, %s)"


def test_question_mark_inside_string_literal_preserved():
    sql = "SELECT * FROM t WHERE note = 'what?' AND id = ?"
    out = PostgresManager.sqlite_to_postgres(sql)
    assert "'what?'" in out          # literal untouched
    assert out.count("%s") == 1      # only the real placeholder converted
    assert "?" not in out.replace("'what?'", "")


def test_autoincrement_pk_becomes_bigserial():
    sql = ("CREATE TABLE IF NOT EXISTS pattern_memory ("
           "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL)")
    out = PostgresManager.sqlite_to_postgres(sql)
    assert "BIGSERIAL PRIMARY KEY" in out
    assert "AUTOINCREMENT" not in out


def test_datetime_and_real_types_become_native():
    sql = ("CREATE TABLE t (ts DATETIME DEFAULT CURRENT_TIMESTAMP, "
           "score REAL DEFAULT 0.5)")
    out = PostgresManager.sqlite_to_postgres(sql)
    assert "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" in out
    assert "DOUBLE PRECISION DEFAULT 0.5" in out
    assert "DATETIME" not in out and " REAL" not in out


def test_full_migration_statement_converts_end_to_end():
    sql = """
    CREATE TABLE IF NOT EXISTS trust_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        trust_score REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """
    out = PostgresManager.sqlite_to_postgres(sql)
    assert "BIGSERIAL PRIMARY KEY" in out
    assert "DOUBLE PRECISION NOT NULL" in out
    assert "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" in out
    assert "AUTOINCREMENT" not in out


def test_insert_record_converts_like_migration_runner():
    sql = "INSERT INTO schema_migrations (migration_name) VALUES (?)"
    assert PostgresManager.sqlite_to_postgres(sql) == \
        "INSERT INTO schema_migrations (migration_name) VALUES (%s)"


def test_limit_placeholder_converts():
    sql = "SELECT * FROM episodic_memory WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?"
    out = PostgresManager.sqlite_to_postgres(sql)
    assert out.count("%s") == 2


def test_convert_sql_passthrough_on_sqlite_fallback():
    """SQLite fallback must receive the SQLite dialect UNCHANGED.

    Built via __new__ so no DB connection is opened (the env may have a live
    Postgres; these are pure routing tests).
    """
    m = PostgresManager.__new__(PostgresManager)
    m.use_fallback = True
    sql = "INSERT INTO t VALUES (?, ?)"
    assert m._convert_sql(sql) == sql


def test_convert_sql_converts_in_postgres_mode():
    """In Postgres mode _convert_sql must convert (no DB round-trip needed —
    use_fallback is consulted, not the connection)."""
    m = PostgresManager.__new__(PostgresManager)
    m.use_fallback = False
    assert m._convert_sql("VALUES (?)") == "VALUES (%s)"
    m.use_fallback = True
    assert m._convert_sql("VALUES (?)") == "VALUES (?)"
