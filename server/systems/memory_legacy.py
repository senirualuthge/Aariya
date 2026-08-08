from typing import List, Dict, Optional
import json
from server.db import get_db_connection

class MemorySystem:
    def __init__(self, user_id: str = "user_default"):
        self.user_id = user_id

    def store_memory(self, content: str, memory_type: str = "short_term", importance: float = 0.5, emotion_context: Optional[Dict] = None) -> int:
        """Stores a new memory."""
        conn = get_db_connection()
        try:
            cursor = conn.execute("""
                INSERT INTO memories (user_id, type, content, importance, emotion_context)
                VALUES (?, ?, ?, ?, ?)
            """, (self.user_id, memory_type, content, importance, json.dumps(emotion_context) if emotion_context else None))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def recall_recent(self, limit: int = 5) -> List[Dict]:
        """Recalls most recent memories."""
        conn = get_db_connection()
        try:
            rows = conn.execute("""
                SELECT content, type, timestamp, importance
                FROM memories
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (self.user_id, limit)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def search_memories(self, query: str, limit: int = 5) -> List[Dict]:
        """Simple keyword search for memories."""
        conn = get_db_connection()
        try:
            # Simple LIKE query for now; switch to FTS later if needed
            rows = conn.execute("""
                SELECT content, type, timestamp, importance
                FROM memories
                WHERE user_id = ? AND content LIKE ?
                ORDER BY importance DESC, timestamp DESC
                LIMIT ?
            """, (self.user_id, f"%{query}%", limit)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
