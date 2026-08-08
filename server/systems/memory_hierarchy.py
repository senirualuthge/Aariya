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

from typing import List, Dict, Optional
from datetime import datetime, timedelta
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
        count = sum(1 for mem in recent_memories if behavior_description.lower() in mem['summary'].lower())
        
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


# Global instance
_memory_hierarchy: Optional[MemoryHierarchy] = None


def get_memory_hierarchy() -> MemoryHierarchy:
    """Get or create global memory hierarchy instance."""
    global _memory_hierarchy
    if _memory_hierarchy is None:
        _memory_hierarchy = MemoryHierarchy()
    return _memory_hierarchy
