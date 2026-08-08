"""
PostgreSQL connection manager for persistent data storage.
Provides connection pooling, migration runner, and fallback to SQLite.
"""

import os
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
