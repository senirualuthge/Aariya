"""
PostgreSQL connection manager for persistent data storage.
Provides connection pooling, migration runner, and fallback to SQLite.
"""

import os
import re
from typing import Optional, Dict, Any, List
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import pool
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    print("[WARN] psycopg2 not installed. Using SQLite fallback for development.")

import sqlite3


class PostgresManager:
    """Manages PostgreSQL connections with fallback to SQLite."""
    
    def __init__(self, database_url: Optional[str] = None):
        self.database_url: Optional[str] = database_url or os.getenv('DATABASE_URL')
        self.use_fallback = not POSTGRES_AVAILABLE or not self.database_url
        self.pool: Optional[Any] = None
        self.sqlite_conn: Optional[sqlite3.Connection] = None
        
        if not self.use_fallback:
            self._init_postgres_pool()
        else:
            self._init_sqlite_fallback()

    # ── SQL dialect conversion (SQLite dialect → Postgres-native) ────────────
    #
    # The project's SQL (migrations + every module in server/systems that talks
    # to this manager) is written in the SQLITE dialect: '?' placeholders,
    # AUTOINCREMENT, TEXT/REAL/INTEGER columns, DATETIME columns with
    # CURRENT_TIMESTAMP defaults. While the SQLite fallback speaks that
    # dialect natively, Postgres needs '%s' placeholders and its own DDL —
    # and before this conversion layer existed, every '?'-parameterized
    # statement silently FAILED against a live Postgres (pattern_memory,
    # episodic_memory, trust_history … were never written). Conversion happens
    # HERE, at the single choke point, so the whole codebase keeps writing
    # SQLite-dialect SQL while Postgres deployments get native SQL.

    _PG_INT_IDENT = re.compile(
        r"\b(INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT)\b", re.IGNORECASE)

    @staticmethod
    def _is_identifier_char(ch: str) -> bool:
        return ch.isalnum() or ch == '_'

    @classmethod
    def _replace_placeholders_outside_quotes(cls, sql: str) -> str:
        """Replace every '?' outside single-quoted literals with %s."""
        out: List[str] = []
        in_str = False
        for ch in sql:
            if ch == "'":
                in_str = not in_str
                out.append(ch)
            elif ch == '?' and not in_str:
                out.append('%s')
            else:
                out.append(ch)
        return "".join(out)

    @classmethod
    def sqlite_to_postgres(cls, sql: str) -> str:
        """Convert one SQLite-dialect statement to Postgres-native SQL.

        Handles the dialect features this project actually uses:
          * '?' placeholders → %s (skipping string literals)
          * INTEGER PRIMARY KEY AUTOINCREMENT → BIGSERIAL PRIMARY KEY
          * AUTOINCREMENT / DATETIME / REAL / TEXT column types → native
          * CREATE INDEX IF NOT EXISTS / CREATE TABLE IF NOT EXISTS stay
            (Postgres ≥ 9.5 supports both)
        """
        converted = cls._PG_INT_IDENT.sub("BIGSERIAL PRIMARY KEY", sql)

        # Remaining standalone AUTOINCREMENT (defensive; the INT-PK form is
        # the only one this project emits).
        converted = re.sub(
            r"\bAUTOINCREMENT\b", "", converted, flags=re.IGNORECASE)

        # Type mapping — only inside CREATE TABLE column defs matters, but a
        # global word-boundary swap is safe for these type words.
        converted = re.sub(r"\bDATETIME\b", "TIMESTAMP",
                           converted, flags=re.IGNORECASE)
        converted = re.sub(r"\bREAL\b", "DOUBLE PRECISION",
                           converted, flags=re.IGNORECASE)

        # TEXT is a valid Postgres type; INTEGER stays INTEGER. No swap needed.

        # 'id INTEGER PRIMARY KEY' (no autoincrement) is a valid Postgres
        # integer PK — left untouched.

        return cls._replace_placeholders_outside_quotes(converted)

    def _convert_sql(self, sql: str) -> str:
        """Dialect-convert `sql` only when the active backend is Postgres."""
        if getattr(self, "use_fallback", False):
            return sql
        return self.sqlite_to_postgres(sql)
    
    def _init_postgres_pool(self):
        """Initialize PostgreSQL connection pool."""
        if not POSTGRES_AVAILABLE:
            return
            
        try:
            # Re-import locally to ensure psycopg2 is in scope if POSTGRES_AVAILABLE is true
            import psycopg2.pool
            self.pool = psycopg2.pool.SimpleConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=self.database_url # type: ignore
            )
            print("[OK] PostgreSQL connection pool initialized")
        except Exception as e:
            print(f"[WARN] PostgreSQL connection failed: {e}. Using SQLite fallback.")
            self.use_fallback = True
            self._init_sqlite_fallback()
    
    def _init_sqlite_fallback(self):
        """Initialize SQLite fallback."""
        db_dir = Path.home() / ".aariya"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "data.db"
        
        self.sqlite_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.sqlite_conn.row_factory = sqlite3.Row
        print(f"[OK] SQLite fallback initialized: {db_path}")
    
    def get_connection(self):
        """Get a database connection."""
        if self.use_fallback:
            return self.sqlite_conn
        
        if self.pool is None:
            return None
            
        try:
            return self.pool.getconn()
        except Exception as e:
            print(f"[ERROR] Failed to get Postgres connection: {e}")
            return None
    
    def return_connection(self, conn):
        """Return connection to pool (Postgres only)."""
        if not self.use_fallback and self.pool and conn:
            try:
                self.pool.putconn(conn)
            except Exception as e:
                print(f"[ERROR] Failed to return connection: {e}")
    
    def execute_query(self, query: str, params: Optional[tuple] = None) -> Optional[List[Dict]]:
        """Execute a SELECT query and return results."""
        query = self._convert_sql(query)
        conn = self.get_connection()
        if not conn:
            return None
        
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            
            if self.use_fallback:
                # SQLite returns Row objects
                results = [dict(row) for row in cursor.fetchall()]
            else:
                # Postgres needs manual dict conversion
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            
            cursor.close()
            return results
        except Exception as e:
            print(f"[ERROR] Query execution failed: {e}")
            return None
        finally:
            if not self.use_fallback:
                self.return_connection(conn)
    
    def execute_update(self, query: str, params: Optional[tuple] = None) -> bool:
        """Execute an INSERT/UPDATE/DELETE query."""
        query = self._convert_sql(query)
        conn = self.get_connection()
        if not conn:
            return False
        
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"[ERROR] Update execution failed: {e}")
            if conn:
                try: conn.rollback()
                except: pass
            return False
        finally:
            if not self.use_fallback:
                self.return_connection(conn)
    
    def execute_many(self, query: str, params_list: List[tuple]) -> bool:
        """Execute batch INSERT/UPDATE."""
        query = self._convert_sql(query)
        conn = self.get_connection()
        if not conn:
            return False
        
        try:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)
            conn.commit()
            cursor.close()
            return True
        except Exception as e:
            print(f"[ERROR] Batch execution failed: {e}")
            if conn:
                try: conn.rollback()
                except: pass
            return False
        finally:
            if not self.use_fallback:
                self.return_connection(conn)
    
    def health_check(self) -> bool:
        """Check if database is healthy."""
        conn = self.get_connection()
        if not conn:
            return False
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.close()
            return True
        except:
            return False
        finally:
            if not self.use_fallback:
                self.return_connection(conn)
    
    def close(self):
        """Close all connections."""
        if self.use_fallback and self.sqlite_conn:
            self.sqlite_conn.close()
        elif self.pool:
            self.pool.closeall()


# Global instance
_postgres_manager: Optional[PostgresManager] = None


def get_postgres() -> PostgresManager:
    """Get or create global Postgres manager instance."""
    global _postgres_manager
    if _postgres_manager is None:
        _postgres_manager = PostgresManager()
    return _postgres_manager
