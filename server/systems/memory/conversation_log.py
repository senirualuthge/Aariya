"""
ConversationLog — the persistent conversational self of Aariya.
─────────────────────────────────────────────────────────────────
Provides the durable layer behind BrainV2's sense of continuity:

  - add_turn()     — store every user / Aariya turn (with her inner thought)
  - recent()       — last N turns for prompt context (persists across restarts)
  - memorize()     — store emotionally significant moments as durable memories
  - recall()       — keyword-scored retrieval of relevant memories
  - last_state()   — restore trust/valence/attachment continuity on connect
  - add_thought()  — record inner monologue entries (visible inner life)

Storage is SQLite (data/brain_v4.db) via server.db, so nothing here depends
on ChromaDB / sentence-transformers / Postgres being available.
"""

import time
import uuid
from typing import Any, Dict, List, Optional

from server.db import get_db_connection

DEFAULT_K = 4
SIGNIFICANCE_THRESHOLD = 0.45


def _now() -> float:
    return time.time()


class ConversationLog:
    def __init__(self, user_id: str = "user_default"):
        self.user_id = user_id

    # ── Turn history ───────────────────────────────────────────────────────────

    def add_turn(self, role: str, text: str, thought: Optional[str] = None,
                 valence: float = 0.0, trust: float = 0.5) -> None:
        if not text:
            return
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO conversation_messages
                   (user_id, role, text, thought, valence, trust, ts)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (self.user_id, role, text[:2000], (thought or "")[:500],
                 valence, trust, _now()),
            )
            conn.commit()
        finally:
            conn.close()

    def recent(self, limit: int = 16) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM conversation_messages WHERE user_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (self.user_id, limit),
            ).fetchall()
            return list(reversed([dict(r) for r in rows]))
        finally:
            conn.close()

    def recent_prompt(self, limit: int = 12) -> str:
        """Format recent turns for injection into the LLM prompt."""
        turns = self.recent(limit)
        lines = []
        for t in turns:
            name = "User" if t["role"] == "user" else "Aariya"
            lines.append(f"{name}: {t['text']}")
        return "\n".join(lines) if lines else ""

    def count(self) -> int:
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM conversation_messages WHERE user_id = ?",
                (self.user_id,),
            ).fetchone()
            return int(row["c"]) if row else 0
        finally:
            conn.close()

    # ── Durable memories ───────────────────────────────────────────────────────

    def memorize(self, text: str, valence: float = 0.0, trust: float = 0.5,
                 significance: float = 0.5) -> bool:
        """Store an emotionally significant moment if above the threshold."""
        if not text or significance < SIGNIFICANCE_THRESHOLD:
            return False
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO memories (id, user_id, text, valence, trust, significance, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (str(uuid.uuid4()), self.user_id, text[:1000], valence, trust,
                 significance, _now()),
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def recall(self, query: str, limit: int = DEFAULT_K) -> List[Dict[str, Any]]:
        """
        Keyword-scored recall over durable memories. Scores by word overlap so
        it works with zero ML dependencies; returns highest-confidence hits.
        """
        if not query.strip():
            return []
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM memories WHERE user_id = ?
                   ORDER BY significance DESC, created_at DESC LIMIT 200""",
                (self.user_id,),
            ).fetchall()
            memories = [dict(r) for r in rows]
        finally:
            conn.close()

        query_words = set(_tokens(query))
        scored = []
        for m in memories:
            words = _tokens(m["text"])
            if not words:
                continue
            overlap = len(query_words & words)
            if overlap == 0:
                continue
            score = overlap / max(len(query_words), 1)
            # Blend lexical overlap with stored significance
            score = score * 0.7 + float(m.get("significance", 0.0)) * 0.3
            scored.append((score, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:limit]]

    def recall_prompt(self, query: str, limit: int = DEFAULT_K) -> str:
        memories = self.recall(query, limit)
        if not memories:
            return ""
        return "\n".join(f"- {m['text']}" for m in memories)

    # ── Continuity (restore emotional state on connect) ───────────────────────

    def last_state(self) -> Optional[Dict[str, float]]:
        """Latest self-awareness snapshot (valence/arousal/trust/attachment)
        persisted for this user, so a fresh BrainV2 resumes where she left off."""
        conn = get_db_connection()
        try:
            row = conn.execute(
                """SELECT valence, arousal, trust, attachment FROM autonomy_snapshots
                   WHERE user_id = ? ORDER BY id DESC LIMIT 1""",
                (self.user_id,),
            ).fetchone()
            if not row:
                # Fall back to the most recent conversation turn's state
                row = conn.execute(
                    """SELECT valence, trust FROM conversation_messages
                       WHERE user_id = ? ORDER BY id DESC LIMIT 1""",
                    (self.user_id,),
                ).fetchone()
                if not row:
                    return None
                return {"valence": float(row["valence"]), "trust": float(row["trust"]),
                        "arousal": 0.0, "attachment": 0.0}
            return dict(row)
        finally:
            conn.close()

    # ── Inner monologue ────────────────────────────────────────────────────────

    def add_thought(self, thought: str, kind: str = "private") -> None:
        if not thought:
            return
        conn = get_db_connection()
        try:
            conn.execute(
                """INSERT INTO inner_thoughts (user_id, thought, kind, ts)
                   VALUES (?, ?, ?, ?)""",
                (self.user_id, thought[:500], kind, _now()),
            )
            conn.commit()
        finally:
            conn.close()

    def recent_thoughts(self, limit: int = 10) -> List[Dict[str, Any]]:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """SELECT * FROM inner_thoughts WHERE user_id = ?
                   ORDER BY id DESC LIMIT ?""",
                (self.user_id, limit),
            ).fetchall()
            return list(reversed([dict(r) for r in rows]))
        finally:
            conn.close()


def _tokens(text: str) -> set:
    """Lowercased alphanumeric tokens — light keyword matching."""
    import re
    return set(re.findall(r"[a-z0-9']+", text.lower()))
