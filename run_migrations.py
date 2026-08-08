"""
Database migration runner script.
Run this from the project root: python run_migrations.py
"""

import sys
import os

# Add server directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'server'))

from server.migrations import run_migrations

if __name__ == "__main__":
    print("[MIGRATION] Starting database migrations...")
    run_migrations()
    print("[MIGRATION] Complete!")
