"""
Database migration runner.
Applies SQL migrations in order and tracks migration history.
"""

import os
from pathlib import Path
from typing import List, Tuple
from server.infrastructure.postgres_manager import get_postgres


class MigrationRunner:
    """Manages database schema migrations."""
    
    def __init__(self):
        self.db = get_postgres()
        self.migrations_dir = Path(__file__).parent
        self._ensure_migration_table()
    
    def _ensure_migration_table(self):
        """Create migrations tracking table if it doesn't exist."""
        query = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            migration_name TEXT NOT NULL UNIQUE,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
        self.db.execute_update(query)
    
    def get_applied_migrations(self) -> List[str]:
        """Get list of already applied migrations."""
        results = self.db.execute_query(
            "SELECT migration_name FROM schema_migrations ORDER BY migration_name"
        )
        return [row['migration_name'] for row in results] if results else []
    
    def get_pending_migrations(self) -> List[Tuple[str, Path]]:
        """Get list of migrations that haven't been applied yet."""
        applied = set(self.get_applied_migrations())
        all_migrations = []

        # Find all .sql files in migrations directory.
        # *_rollback.sql files are rollback scripts, NOT migrations — they
        # were previously applied as if they were migrations (dropping the
        # tables migration 001 had just created).
        for file_path in sorted(self.migrations_dir.glob("*.sql")):
            migration_name = file_path.stem
            if migration_name.endswith("_rollback"):
                continue
            if migration_name not in applied:
                all_migrations.append((migration_name, file_path))

        return all_migrations
    
    def apply_migration(self, migration_name: str, file_path: Path) -> bool:
        """Apply a single migration."""
        try:
            print(f"[MIGRATION] Applying {migration_name}...")
            
            # Read migration SQL.
            #
            # Comments must be stripped BEFORE splitting on ';' — a comment
            # containing a semicolon would otherwise split mid-comment and
            # produce garbage statements. The "-- TOLERANT" prefix is swapped
            # for a sentinel first so it survives this stripping: it marks
            # best-effort statements (e.g. ADD COLUMN on a legacy table that
            # already has the column) whose failure must not abort.
            _TOL = "\x01TOLERANT\x01"
            with open(file_path, 'r', encoding='utf-8') as f:
                raw_sql = f.read().replace("-- TOLERANT", _TOL)
            code_lines = []
            for line in raw_sql.splitlines():
                stripped = line.strip()
                if stripped.startswith(_TOL):
                    code_lines.append(_TOL + stripped[len(_TOL):].strip())
                elif not stripped or stripped.startswith("--"):
                    continue
                else:
                    code_lines.append(line)

            # Execute each statement — a failed statement must fail the whole
            # migration, otherwise it gets recorded as applied while its
            # tables are missing (the original "no such table" bug).
            for raw_statement in "\n".join(code_lines).split(';'):
                if not raw_statement.strip():
                    continue
                statement = raw_statement.strip()
                tolerant = statement.startswith(_TOL)
                if tolerant:
                    statement = statement.replace(_TOL, "", 1).strip()
                if not statement:
                    continue

                ok = self.db.execute_update(statement)
                if not ok and not tolerant:
                    raise RuntimeError(
                        f"Statement failed in {migration_name}: "
                        f"{statement[:80]}...")
                if not ok:
                    print(f"[TOLERANT] Skipped failing statement in {migration_name}")
            
            # Record migration as applied
            self.db.execute_update(
                "INSERT INTO schema_migrations (migration_name) VALUES (?)",
                (migration_name,)
            )
            
            print(f"[OK] Migration {migration_name} applied successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR] Migration {migration_name} failed: {e}")
            return False
    
    def run_pending_migrations(self) -> int:
        """Run all pending migrations. Returns number of migrations applied."""
        pending = self.get_pending_migrations()
        
        if not pending:
            print("[OK] No pending migrations")
            return 0
        
        print(f"[MIGRATION] Found {len(pending)} pending migrations")
        applied_count = 0
        
        for migration_name, file_path in pending:
            if self.apply_migration(migration_name, file_path):
                applied_count += 1
            else:
                print(f"[ERROR] Stopping migration process due to failure")
                break
        
        return applied_count
    
    def rollback_last_migration(self) -> bool:
        """Rollback the most recently applied migration (if rollback script exists)."""
        applied = self.get_applied_migrations()
        if not applied:
            print("[WARN] No migrations to rollback")
            return False
        
        last_migration = applied[-1]
        rollback_file = self.migrations_dir / f"{last_migration}_rollback.sql"
        
        if not rollback_file.exists():
            print(f"[ERROR] No rollback script found for {last_migration}")
            return False
        
        try:
            print(f"[MIGRATION] Rolling back {last_migration}...")
            
            with open(rollback_file, 'r', encoding='utf-8') as f:
                sql = f.read()
            
            statements = [s.strip() for s in sql.split(';') if s.strip()]
            
            for statement in statements:
                if statement:
                    self.db.execute_update(statement)
            
            # Remove from migrations table
            self.db.execute_update(
                "DELETE FROM schema_migrations WHERE migration_name = ?",
                (last_migration,)
            )
            
            print(f"[OK] Migration {last_migration} rolled back successfully")
            return True
            
        except Exception as e:
            print(f"[ERROR] Rollback failed: {e}")
            return False


def run_migrations():
    """CLI entry point for running migrations."""
    runner = MigrationRunner()
    count = runner.run_pending_migrations()
    print(f"\n[SUMMARY] Applied {count} migrations")


if __name__ == "__main__":
    run_migrations()
