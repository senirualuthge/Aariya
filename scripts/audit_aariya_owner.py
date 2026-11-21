#!/usr/bin/env python3
"""Read-only audit: does AARIYA_OWNER_ID match the real data owners?

Discovers every table that carries a ``user_id`` or ``owner_id`` column and
reports the identity distribution, marking rows that match the configured
owner. It never prints conversation text, memory content, pairing codes,
credential hashes, or any other row payload.

The database is opened with SQLite's ``mode=ro`` URI plus ``PRAGMA
query_only``, so the audit cannot mutate the installation.

Usage (from the repository root):

    python scripts/audit_aariya_owner.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

IDENTITY_COLUMNS = {"user_id", "owner_id"}
DEFAULT_DB = Path("data/brain_v4.db")


def quote_identifier(name: str) -> str:
    """Quote a SQL identifier for interpolation into PRAGMA/pragma queries."""
    return '"' + name.replace('"', '""') + '"'


def open_read_only(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(db_path.resolve()))}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    # Belt and braces: even a writable handle must refuse writes.
    connection.execute("PRAGMA query_only = ON")
    return connection


def list_tables(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    return [row["name"] for row in rows]


def identity_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
    return [
        row["name"]
        for row in rows
        if row["name"].lower() in IDENTITY_COLUMNS
    ]


def load_environment() -> None:
    """Load .env via python-dotenv when present, otherwise a tiny fallback."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None  # type: ignore[assignment]

    if load_dotenv is not None:
        load_dotenv()
        return

    env_path = Path(".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    load_environment()

    configured_owner = os.getenv("AARIYA_OWNER_ID", "").strip()
    db_path = Path(os.getenv("AARIYA_DB_PATH", str(DEFAULT_DB)))

    if not configured_owner:
        print("ERROR: AARIYA_OWNER_ID is not configured.")
        return 1
    if not db_path.exists():
        print(f"ERROR: Database not found: {db_path}")
        return 1

    print(f"Configured owner: {configured_owner!r}")
    print(f"Database: {db_path}")
    print()

    try:
        connection = open_read_only(db_path)
    except sqlite3.Error as exc:
        print(f"ERROR: Could not open the database read-only: {exc}")
        return 1

    try:
        matched_columns = 0
        mismatched_columns = 0
        tables_with_identity = 0

        for table in list_tables(connection):
            columns = identity_columns(connection, table)
            if not columns:
                continue
            tables_with_identity += 1

            for column in columns:
                identifier = quote_identifier(column)
                display = quote_identifier(table)
                rows = connection.execute(
                    f"""
                    SELECT {identifier} AS identity_value,
                           COUNT(*) AS row_count
                    FROM {display}
                    WHERE {identifier} IS NOT NULL
                      AND TRIM(CAST({identifier} AS TEXT)) != ''
                    GROUP BY {identifier}
                    ORDER BY row_count DESC, identity_value
                    """
                ).fetchall()

                print(f"Table: {table}.{column}")
                if not rows:
                    print("  No non-empty identity values found.")
                    print()
                    continue

                for row in rows:
                    identity = str(row["identity_value"])
                    count = row["row_count"]
                    matches = identity == configured_owner
                    if matches:
                        matched_columns += 1
                    else:
                        mismatched_columns += 1
                    marker = "MATCH" if matches else "different"
                    print(f"  {identity!r}: {count} rows [{marker}]")
                print()

        if tables_with_identity == 0:
            print("WARNING: No user_id or owner_id columns were discovered.")
            return 2

        print("-" * 60)
        print(f"Tables with identity columns: {tables_with_identity}")
        print(f"Identity groups matching the configured owner: {matched_columns}")
        print(f"Identity groups belonging to other ids: {mismatched_columns}")
        print("AUDIT COMPLETE — database opened read-only.")
        print("No records, credentials, messages, or memories were changed.")
        print("Do not change AARIYA_OWNER_ID until the results are reviewed.")
        return 0
    except sqlite3.Error as exc:
        print(f"ERROR: Database inspection failed: {exc}")
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
