"""
Memory Retrieval Policy (MRP) — Fixv2 Implementation.

Controls WHEN and WHAT memories are injected into responses.
Design goals:
- Recall only when it adds value
- Avoid repeating the same memory
- Gate memory depth by trust tier
- Prefer: recent → relevant → emotionally aligned
- Stay within latency budget
- Non-creepy injection formatting
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from server.infrastructure.observability import logger
from server.infrastructure.postgres_manager import get_postgres
from server.systems.trust_system import get_trust_system, TrustTier
from server.systems.memory.episodic_memory import EpisodicMemory


# ─────────────────────────────────────────────
#  Trust tier memory access map
# ─────────────────────────────────────────────

class MemoryTrustLevel(str, Enum):
    """Which memory types are accessible at each trust tier."""
    NONE     = "none"          # DEFENSIVE  < 0.2
    SEMANTIC = "semantic"      # GUARDED    0.2–0.4
    EPISODIC_RECENT = "episodic_recent"  # NEUTRAL 0.4–0.6  (+7-day episodic)
    EPISODIC_FULL   = "episodic_full"   # WARM    0.6–0.8  (+older episodic)
    PATTERN         = "pattern"         # INTIMATE > 0.8   (+patterns)


TRUST_TO_MEMORY_LEVEL: Dict[TrustTier, MemoryTrustLevel] = {
    TrustTier.DEFENSIVE: MemoryTrustLevel.NONE,
    TrustTier.GUARDED:   MemoryTrustLevel.SEMANTIC,
    TrustTier.NEUTRAL:   MemoryTrustLevel.EPISODIC_RECENT,
    TrustTier.WARM:      MemoryTrustLevel.EPISODIC_FULL,
    TrustTier.INTIMATE:  MemoryTrustLevel.PATTERN,
}

# Memory type allowed at each level (inclusive / cumulative)
LEVEL_ORDER = [
    MemoryTrustLevel.NONE,
    MemoryTrustLevel.SEMANTIC,
    MemoryTrustLevel.EPISODIC_RECENT,
    MemoryTrustLevel.EPISODIC_FULL,
    MemoryTrustLevel.PATTERN,
]

PERSONAL_QUESTION_INTENTS = {"PERSONAL", "COMFORTING", "PLANNING"}
LATENCY_SKIP_THRESHOLD_MS = 180.0


@dataclass
class MemoryCandidate:
    memory_id: str
    content: str
    memory_type: str       # 'semantic', 'episodic', 'pattern'
    timestamp: datetime
    emotional_context: Optional[str]
    emotion_valence: float
    emotion_intensity: float
    topic_tags: List[str]
    days_old: float
    reuse_count: int       # times used in recent sessions
    last_used_turn_ago: int  # 0 = used this turn
    score: float = 0.0


@dataclass
class RecallResult:
    """Returned by retrieve_memory(). None means no recall."""
    memory_id: str
    abstracted_summary: str
    topic_tag: str
    tone: str              # 'light_reference' | 'confident' | 'indirect'
    injected_prompt: str   # ready for prompt injection


# ─────────────────────────────────────────────
#  Session-scoped recall quota tracker
# ─────────────────────────────────────────────

class RecallQuota:
    """Per-session rolling quota: max 1/turn, max 2/minute."""

    MAX_PER_TURN    = 1
    MAX_PER_MINUTE  = 2

    def __init__(self):
        self._this_turn_count = 0
        self._minute_timestamps: List[float] = []

    def can_recall(self) -> bool:
        if self._this_turn_count >= self.MAX_PER_TURN:
            return False
        # Prune timestamps older than 60 s
        now = time.monotonic()
        self._minute_timestamps = [t for t in self._minute_timestamps if now - t < 60.0]
        return len(self._minute_timestamps) < self.MAX_PER_MINUTE

    def record_recall(self):
        self._this_turn_count += 1
        self._minute_timestamps.append(time.monotonic())

    def reset_turn(self):
        """Call at the beginning of each new turn."""
        self._this_turn_count = 0


# ─────────────────────────────────────────────
#  Scoring helpers
# ─────────────────────────────────────────────

def _recency_decay(days_old: float) -> float:
    """exp(-days / 14) — from Fixv2 spec."""
    return math.exp(-days_old / 14.0)


def _novelty_score(reuse_count: int) -> float:
    """1 - reuse_frequency (penalise recently used memories)."""
    return max(0.0, 1.0 - min(1.0, reuse_count / 5.0))


def _emotional_alignment(
    current_valence: float,
    memory_valence: float,
    memory_intensity: float
) -> float:
    """
    |ΔVA| < 0.25 AND memory_emotion_intensity > 0.6 → high alignment.
    Returns [0, 1].
    """
    delta = abs(current_valence - memory_valence)
    if delta < 0.25 and memory_intensity > 0.6:
        return 1.0 - delta / 0.25  # gradient inside window
    return max(0.0, 1.0 - delta)


def score_candidate(
    c: MemoryCandidate,
    semantic_similarity: float,
    current_valence: float,
    trust_level: float,
) -> float:
    """
    Memory scoring function from Fixv2 spec:
    score = 0.35*sim + 0.25*recency + 0.20*emotion_align + 0.10*trust + 0.10*novelty
    """
    recency   = _recency_decay(c.days_old)
    emotion   = _emotional_alignment(current_valence, c.emotion_valence, c.emotion_intensity)
    novelty   = _novelty_score(c.reuse_count)
    trust_w   = trust_level  # higher trust → memories weighted more

    return round(
        0.35 * semantic_similarity
        + 0.25 * recency
        + 0.20 * emotion
        + 0.10 * trust_w
        + 0.10 * novelty,
        4
    )


# ─────────────────────────────────────────────
#  Injection formatter
# ─────────────────────────────────────────────

def _format_injection(content: str, topic_tag: str, trust_level: float) -> Tuple[str, str, str]:
    """
    Build non-creepy memory context block.
    Low/mid trust  → indirect reference
    High trust     → confident reference

    Returns: (abstracted_summary, tone, injected_prompt)
    """
    # Sanitise: strip timestamps/dates from content
    abstracted = content.strip()
    # Remove anything that looks like "on DATE at TIME"
    import re
    abstracted = re.sub(
        r'\bon\s+\w+\s+\d{1,2}(st|nd|rd|th)?(\s+at\s+[\d:]+\s*(AM|PM)?)?',
        '',
        abstracted,
        flags=re.IGNORECASE
    ).strip()

    if trust_level >= 0.7:
        tone = "confident"
        prefix = "You told me"
    elif trust_level >= 0.4:
        tone = "indirect"
        prefix = "I think you mentioned"
    else:
        tone = "light_reference"
        prefix = "Last time you mentioned"

    # Trim if too long
    if len(abstracted) > 200:
        abstracted = abstracted[:197] + "…"

    summary = f"{prefix} {abstracted.lower()}"

    injected_prompt = (
        "<personal_context>\n"
        f"User previously mentioned: {abstracted}\n"
        f"Relevance: {topic_tag}\n"
        f"Tone: {tone}\n"
        "</personal_context>"
    )

    return summary, tone, injected_prompt


# ─────────────────────────────────────────────
#  Main MRP class
# ─────────────────────────────────────────────

class MemoryRetrievalPolicy:
    """
    Decides whether to recall memory, selects the best candidate,
    and formats the injection context.

    Stateless except for the per-session quota tracker (injected).
    """

    def __init__(self):
        self.db = get_postgres()
        self.trust_system = get_trust_system()

    def retrieve_memory(
        self,
        user_id: str,
        session_id: str,
        turn_id: str,
        user_text: str,
        intent: str,
        current_valence: float,
        current_arousal: float,
        trust_level: float,
        latency_budget_ms: float,
        quota: RecallQuota,
        episodic_mgr: EpisodicMemory,
        days_since_last_session: float = 0.0,
        recent_turn_memory_ids: Optional[List[str]] = None,
        recent_session_memory_ids: Optional[List[str]] = None,
    ) -> Optional[RecallResult]:
        """
        Main entry point. Returns a RecallResult or None.

        Args:
            user_id:                     User identifier
            session_id:                  Active session
            turn_id:                     Current turn identifier
            user_text:                   Raw user utterance
            intent:                      Classified social intent
            current_valence:             VA valence [-1, 1]
            current_arousal:             VA arousal [0, 1]
            trust_level:                 [0, 1]
            latency_budget_ms:           Available response budget
            quota:                       Session-scoped RecallQuota
            days_since_last_session:     Float days gap
            recent_turn_memory_ids:      Memory IDs used in last 3 turns
            recent_session_memory_ids:   Memory IDs used in last 2 sessions
        """
        recent_turn_memory_ids    = recent_turn_memory_ids    or []
        recent_session_memory_ids = recent_session_memory_ids or []

        # ── 1. Gate checks ─────────────────────────────────────────────────
        tier = self.trust_system.get_trust_tier(trust_level)
        allowed_level = TRUST_TO_MEMORY_LEVEL.get(tier, MemoryTrustLevel.NONE)

        if allowed_level == MemoryTrustLevel.NONE:
            return None

        if latency_budget_ms < LATENCY_SKIP_THRESHOLD_MS:
            return None

        if not quota.can_recall():
            return None

        # ── 2. Trigger check ───────────────────────────────────────────────
        if not self._has_recall_trigger(
            user_text, intent, current_valence, current_arousal,
            trust_level, days_since_last_session
        ):
            return None

        # ── 3. Fetch candidates (Vector Search) ───────────────────────────
        raw_candidates = episodic_mgr.recall_candidates(user_text, n_results=5)
        if not raw_candidates:
            return None

        # ── 4. Filter & Map ────────────────────────────────────────────────
        candidates = []
        for raw in raw_candidates:
            meta = raw["metadata"]
            ts = datetime.fromtimestamp(meta.get("timestamp", time.time()))
            
            c = MemoryCandidate(
                memory_id=raw["id"],
                content=raw["content"],
                memory_type="episodic",
                timestamp=ts,
                emotional_context=meta.get("social_intent"),
                emotion_valence=meta.get("valence", 0.0),
                emotion_intensity=meta.get("significance", 0.5),
                topic_tags=[],
                days_old=(time.time() - meta.get("timestamp", time.time())) / 86400.0,
                reuse_count=0,
                last_used_turn_ago=999,
                score=0.0
            )

            if self._passes_suppression(
                c, trust_level, current_valence, current_arousal,
                recent_turn_memory_ids, recent_session_memory_ids
            ):
                # Apply vector similarity in scoring
                c.score = score_candidate(c, raw["semantic_similarity"], current_valence, trust_level)
                candidates.append(c)

        if not candidates:
            return None

        candidates.sort(key=lambda c: c.score, reverse=True)
        best = candidates[0]

        if best.score < 0.45: # Adjusted threshold for vector similarity
            return None

        # ── 6. Format injection ────────────────────────────────────────────
        topic_tag = best.topic_tags[0] if best.topic_tags else "general"
        summary, tone, injected_prompt = _format_injection(
            best.content, topic_tag, trust_level
        )

        # ── 7. Log recall ──────────────────────────────────────────────────
        quota.record_recall()
        self._log_recall(turn_id, best.memory_id)

        logger.info(
            "Memory recalled",
            user_id=user_id,
            memory_id=best.memory_id,
            score=best.score,
            tone=tone,
            trust=round(trust_level, 3),
        )

        return RecallResult(
            memory_id=best.memory_id,
            abstracted_summary=summary,
            topic_tag=topic_tag,
            tone=tone,
            injected_prompt=injected_prompt,
        )

    # ─────────────────────────────────────────
    #  Trigger detection
    # ─────────────────────────────────────────

    def _has_recall_trigger(
        self,
        user_text: str,
        intent: str,
        current_valence: float,
        current_arousal: float,
        trust_level: float,
        days_since_last_session: float,
    ) -> bool:
        """Check if at least one recall trigger fires."""

        # Trigger 1: Personal question intent
        if intent in PERSONAL_QUESTION_INTENTS:
            return True

        # Trigger 2: Long gap reconnection
        if days_since_last_session > 3.0 and trust_level > 0.5:
            return True

        # Trigger 3: Direct reference (keyword-based; full embedding search done in _fetch)
        # We flag here cheaply; full cosine check happens during scoring
        if user_text and len(user_text.split()) >= 3:
            return True

        return False

    # ─────────────────────────────────────────
    #  Suppression rules
    # ─────────────────────────────────────────

    def _passes_suppression(
        self,
        candidate: MemoryCandidate,
        trust_level: float,
        current_valence: float,
        current_arousal: float,
        recent_turn_ids: List[str],
        recent_session_ids: List[str],
    ) -> bool:
        """Return True if memory passes all suppression checks."""

        # Never use if in last 3 turns
        if candidate.memory_id in recent_turn_ids:
            return False

        # Never use if in last 2 sessions
        if candidate.memory_id in recent_session_ids:
            return False

        # Pattern memory requires trust > 0.8
        if candidate.memory_type == "pattern" and trust_level <= 0.8:
            return False

        # Emotional whiplash: negative memory during positive mood
        if current_valence > 0.3 and candidate.emotion_valence < -0.3:
            return False

        return True

    # ─────────────────────────────────────────
    #  DB helpers
    # ─────────────────────────────────────────

    def _fetch_candidates(
        self,
        user_id: str,
        allowed_level: MemoryTrustLevel,
        limit: int = 5,
    ) -> List[MemoryCandidate]:
        """
        Fetch candidate memories from DB based on trust level.
        Falls back gracefully if DB unavailable.
        """
        level_idx = LEVEL_ORDER.index(allowed_level)
        allowed_types = []
        if level_idx >= 1:
            allowed_types.append("semantic")
        if level_idx >= 2:
            allowed_types.append("episodic")
        if level_idx >= 4:
            allowed_types.append("pattern")

        if not allowed_types:
            return []

        try:
            placeholders = ",".join("?" * len(allowed_types))
            # Episodic_recent means only last 7 days for episodic
            date_filter = ""
            params: list = [user_id] + allowed_types

            if allowed_level == MemoryTrustLevel.EPISODIC_RECENT:
                date_filter = " AND (memory_type != 'episodic' OR created_at >= datetime('now', '-7 days'))"

            rows = self.db.execute_query(
                f"""
                SELECT id, content, memory_type, created_at,
                       emotional_context, importance
                FROM episodic_memory
                WHERE user_id = ?
                  AND memory_type IN ({placeholders})
                  {date_filter}
                ORDER BY importance DESC, created_at DESC
                LIMIT ?
                """,
                params + [limit]
            ) or []

            now = datetime.utcnow()
            result = []
            for row in rows:
                try:
                    ts  = datetime.fromisoformat(str(row.get("created_at", now)))
                    days_old = max(0.0, (now - ts).total_seconds() / 86400.0)
                except Exception:
                    days_old = 1.0

                result.append(MemoryCandidate(
                    memory_id=str(row.get("id", "")),
                    content=str(row.get("content") or row.get("summary", "")),
                    memory_type=str(row.get("memory_type", "episodic")),
                    timestamp=ts,
                    emotional_context=row.get("emotional_context"),
                    emotion_valence=0.0,
                    emotion_intensity=float(row.get("importance", 0.5)),
                    topic_tags=[],
                    days_old=days_old,
                    reuse_count=0,
                    last_used_turn_ago=999,
                ))
            return result

        except Exception as e:
            logger.error("Memory fetch failed", error=str(e))
            return []

    def _compute_similarity(self, user_text: str, memory_content: str) -> float:
        """
        Cheap keyword-based similarity proxy.
        Production: replace with vector cosine similarity (e.g. sentence-transformers).
        """
        if not user_text or not memory_content:
            return 0.0

        user_words    = set(user_text.lower().split())
        memory_words  = set(memory_content.lower().split())
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "i", "you",
            "me", "my", "your", "it", "in", "on", "at", "to", "for"
        }
        user_keywords   = user_words - stopwords
        memory_keywords = memory_words - stopwords

        if not user_keywords:
            return 0.0

        overlap = len(user_keywords & memory_keywords)
        return min(1.0, overlap / len(user_keywords))

    def _log_recall(self, turn_id: str, memory_id: str):
        """Log recall event to memory_recall_log table."""
        try:
            self.db.execute_update(
                """
                INSERT INTO memory_recall_log (turn_id, memory_id, user_reaction)
                VALUES (?, ?, ?)
                """,
                (turn_id, memory_id, "pending")
            )
        except Exception as e:
            logger.error("Memory recall log failed", error=str(e))


# ─────────────────────────────────────────────
#  Global singleton
# ─────────────────────────────────────────────

_mrp: Optional[MemoryRetrievalPolicy] = None


def get_memory_retrieval_policy() -> MemoryRetrievalPolicy:
    global _mrp
    if _mrp is None:
        _mrp = MemoryRetrievalPolicy()
    return _mrp
