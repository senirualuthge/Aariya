"""
Multi-Timescale Memory Hierarchy System.

Implements:
1. Short-term memory (active session)
2. Episodic memory (conversation summaries)
3. Pattern memory (behavioral patterns)
4. Contradiction memory (inconsistency patterns)
5. Personality bias memory (long-term user influence)

Memory retrieval is trust-gated (depth limited by trust level).
"""

from typing import Any, List, Dict, Optional
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from server.infrastructure.postgres_manager import get_postgres
from server.systems.trust_system import get_trust_system


@dataclass
class Memory:
    """Memory entry."""
    content: str
    memory_type: str
    importance: float
    timestamp: datetime
    emotional_context: Optional[str] = None


class MemoryHierarchy:
    """
    Hierarchical memory system with trust-based access control.
    
    Memory Types:
    - short_term: Active session context
    - episodic: Conversation summaries
    - pattern: Behavioral patterns
    - contradiction: Emotional inconsistency patterns
    - personality_bias: Long-term personality influence
    """
    
    def __init__(self):
        self.db = get_postgres()
        self.trust_system = get_trust_system()
        self.short_term_buffer: Dict[str, List[Memory]] = {}  # session_id -> memories
    
    def store_short_term(
        self,
        session_id: str,
        content: str,
        importance: float = 0.5,
        emotional_context: Optional[str] = None
    ):
        """Store in short-term memory (active session only)."""
        if session_id not in self.short_term_buffer:
            self.short_term_buffer[session_id] = []
        
        memory = Memory(
            content=content,
            memory_type='short_term',
            importance=importance,
            timestamp=datetime.now(),
            emotional_context=emotional_context
        )
        
        self.short_term_buffer[session_id].append(memory)
        
        # Keep only last 20 items
        if len(self.short_term_buffer[session_id]) > 20:
            self.short_term_buffer[session_id] = self.short_term_buffer[session_id][-20:]
    
    def store_episodic(
        self,
        user_id: str,
        session_id: str,
        summary: str,
        emotional_context: Optional[str] = None,
        importance: float = 0.5
    ):
        """Store episodic memory (conversation summary)."""
        trust = self.trust_system.get_trust_score(user_id)
        
        self.db.execute_update("""
            INSERT INTO episodic_memory (
                user_id, session_id, summary, emotional_context, importance, trust_level_at_time
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, session_id, summary, emotional_context, importance, trust))
    
    def store_pattern(
        self,
        user_id: str,
        pattern_type: str,
        pattern_description: str,
        confidence: float = 0.5
    ):
        """
        Store or update behavioral pattern.
        
        Pattern types: 'behavioral', 'emotional', 'conversational', 'contradiction'
        """
        # Check if pattern already exists
        existing = self.db.execute_query("""
            SELECT id, occurrences, confidence
            FROM pattern_memory
            WHERE user_id = ? AND pattern_type = ? AND pattern_description = ?
        """, (user_id, pattern_type, pattern_description))
        
        if existing:
            # Update existing pattern
            pattern_id = existing[0]['id']
            new_occurrences = existing[0]['occurrences'] + 1
            new_confidence = min(1.0, existing[0]['confidence'] + 0.1)  # Increase confidence
            
            self.db.execute_update("""
                UPDATE pattern_memory
                SET occurrences = ?, confidence = ?, last_observed = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_occurrences, new_confidence, pattern_id))
        else:
            # Create new pattern
            self.db.execute_update("""
                INSERT INTO pattern_memory (user_id, pattern_type, pattern_description, confidence)
                VALUES (?, ?, ?, ?)
            """, (user_id, pattern_type, pattern_description, confidence))
    
    def recall_short_term(self, session_id: str, limit: int = 10) -> List[Memory]:
        """Recall recent short-term memories."""
        memories = self.short_term_buffer.get(session_id, [])
        return memories[-limit:]
    
    def recall_episodic(
        self,
        user_id: str,
        trust: Optional[float] = None,
        limit: Optional[int] = None
    ) -> List[Dict]:
        """
        Recall episodic memories with trust-based depth limiting.
        
        Trust gates memory depth:
        - Low trust: Only recent memories
        - High trust: Access to older episodic memory
        """
        if trust is None:
            trust = self.trust_system.get_trust_score(user_id)
        
        # Trust-based depth limit
        gates = self.trust_system.get_trust_gates(trust)
        max_depth = gates.memory_depth
        
        if limit is None:
            limit = max_depth * 3  # 3 memories per depth level
        
        results = self.db.execute_query("""
            SELECT *
            FROM episodic_memory
            WHERE user_id = ?
            ORDER BY importance DESC, timestamp DESC
            LIMIT ?
        """, (user_id, limit))
        
        return results or []
    
    def recall_patterns(
        self,
        user_id: str,
        pattern_type: Optional[str] = None,
        min_confidence: float = 0.5
    ) -> List[Dict]:
        """Recall behavioral patterns above confidence threshold."""
        if pattern_type:
            results = self.db.execute_query("""
                SELECT *
                FROM pattern_memory
                WHERE user_id = ? AND pattern_type = ? AND confidence >= ?
                ORDER BY confidence DESC, last_observed DESC
            """, (user_id, pattern_type, min_confidence))
        else:
            results = self.db.execute_query("""
                SELECT *
                FROM pattern_memory
                WHERE user_id = ? AND confidence >= ?
                ORDER BY confidence DESC, last_observed DESC
            """, (user_id, min_confidence))
        
        return results or []
    
    def detect_pattern(
        self,
        user_id: str,
        session_id: str,
        behavior_description: str,
        pattern_type: str = 'behavioral'
    ):
        """
        Detect if a behavior is becoming a pattern.
        
        Pattern detection threshold: 3+ occurrences
        """
        # Check recent sessions for similar behavior
        # This is simplified - in production, use NLP similarity
        
        recent_memories = self.db.execute_query("""
            SELECT summary
            FROM episodic_memory
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT 10
        """, (user_id,))
        
        # Simple keyword matching (replace with semantic similarity in production)
        count = sum(1 for mem in (recent_memories or [])
                    if behavior_description.lower() in mem['summary'].lower())
        
        if count >= 3:
            # Pattern detected!
            self.store_pattern(
                user_id=user_id,
                pattern_type=pattern_type,
                pattern_description=behavior_description,
                confidence=min(1.0, count / 10.0)
            )
    
    def clear_session_memory(self, session_id: str):
        """Clear short-term memory for ended session."""
        if session_id in self.short_term_buffer:
            del self.short_term_buffer[session_id]

    # ── Consolidation + decay (AdvancedPrediction §Memory-Decay) ──────────────

    @staticmethod
    def _parse_ts(val):
        """Epoch float or DATETIME string → epoch seconds.

        SQLite's CURRENT_TIMESTAMP is UTC but returns naive strings; parsing
        them as *local* time skewed every age by the machine's TZ offset.
        Naive strings are therefore interpreted as UTC.
        """
        if isinstance(val, (int, float)):
            return float(val)
        if val is None:
            return None
        try:
            dt = datetime.fromisoformat(str(val))
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    def decay(self, days: float = 30.0, floor: float = 0.05) -> Dict[str, Any]:
        """
        Age-based importance decay (Ebbinghaus curve): episodic and pattern
        memories lose importance the older they get, unless recently accessed.
        Computed in Python for Postgres/SQLite portability. Returns counts.
        """
        result = {"episodic_decayed": 0, "patterns_decayed": 0}
        half_life_secs = days * 86400.0

        def _factor(ts) -> float:
            age = max(0.0, (datetime.now().timestamp() - ts))
            return 0.5 ** (age / half_life_secs)

        for table, time_col in (("episodic_memory", "timestamp"), ("pattern_memory", "last_observed")):
            rows = self.db.execute_query(f"SELECT id, {time_col} AS ts, importance FROM {table}" if table == "episodic_memory" else f"SELECT id, {time_col} AS ts, confidence FROM {table}")
            for r in rows or []:
                ts = self._parse_ts(r.get("ts"))
                if ts is None:
                    continue
                factor = _factor(ts)
                if factor >= 1.0:
                    continue
                # Floor computed here — GREATEST() is Postgres-only and fails
                # on the SQLite fallback store.
                if table == "episodic_memory":
                    new_val = max(floor, float(r.get("importance") or 0.0) * factor)
                    self.db.execute_update(
                        "UPDATE episodic_memory SET importance = ? WHERE id = ?",
                        (new_val, r["id"]))
                else:
                    new_val = max(floor, float(r.get("confidence") or 0.0) * factor)
                    self.db.execute_update(
                        "UPDATE pattern_memory SET confidence = ? WHERE id = ?",
                        (new_val, r["id"]))
                result[f"{'episodic_decayed' if table == 'episodic_memory' else 'patterns_decayed'}"] += 1
        return result

    def consolidate(self, min_occurrences: int = 3) -> Dict[str, Any]:
        """
        Merge near-duplicate episodic summaries (same emotional_context within a
        12h rolling window) into a single higher-importance entry, deleting the
        originals. Portable across Postgres/SQLite. Returns {merged, groups}.
        """
        rows = self.db.execute_query("""
            SELECT id, emotional_context, importance, timestamp
            FROM episodic_memory
            WHERE emotional_context IS NOT NULL AND emotional_context != ''
            ORDER BY timestamp DESC
        """) or []
        # Group by emotional_context + 12h window bucket.
        buckets: Dict[Any, List[dict]] = {}
        for r in rows:
            ts = self._parse_ts(r.get("timestamp"))
            if ts is None:
                continue
            bucket = int(ts) // 43200
            key = (r["emotional_context"], bucket)
            buckets.setdefault(key, []).append(r)

        merged = 0
        groups = 0
        for key, group in buckets.items():
            if len(group) < min_occurrences:
                continue
            groups += 1
            newest = group[0]  # rows sorted DESC
            old_ids = [r["id"] for r in group[1:]]
            for oid in old_ids:
                self.db.execute_update("DELETE FROM episodic_memory WHERE id = ?", (oid,))
            merged += len(old_ids)
            self.db.execute_update("""
                UPDATE episodic_memory
                SET importance = LEAST(1.0, importance + ?)
                WHERE id = ?
            """, (0.05 * len(old_ids), newest["id"]))
        return {"merged": merged, "groups": groups}

    def reinforce(self, user_id: str, n: int = 3) -> Dict[str, Any]:
        """Boost importance of the most-recently relevant episodic memories for
        a user (hippocampal re-access simulation)."""
        rows = self.db.execute_query("""
            SELECT id FROM episodic_memory
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, n))
        for r in rows or []:
            self.db.execute_update("""
                UPDATE episodic_memory
                SET importance = LEAST(1.0, importance + 0.02), timestamp = now()
                WHERE id = ?
            """, (r["id"],))
        return {"reinforced": len(rows or [])}

    def run_maintenance(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """One-shot housekeeping pass: decay → consolidate → reinforce."""
        return {
            "decay": self.decay(),
            "consolidation": self.consolidate(),
            "reinforcement": self.reinforce(user_id) if user_id else {},
        }


# Global instance
_memory_hierarchy: Optional[MemoryHierarchy] = None


def get_memory_hierarchy() -> MemoryHierarchy:
    """Get or create global memory hierarchy instance."""
    global _memory_hierarchy
    if _memory_hierarchy is None:
        _memory_hierarchy = MemoryHierarchy()
    return _memory_hierarchy
