"""
FIXV3 Memory V2 — ChromaDB + Emotional Tagging
Upgrade over Fixv2 memory: only stores emotionally significant memories,
tags them with valence/arousal, and triggers emotional replay on retrieval.

Dependencies: chromadb, sentence-transformers
Graceful fallback: keyword search if sentence-transformers unavailable.
"""

import time
import uuid
from typing import List, Optional

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
    _VECTOR_AVAILABLE = True
except ImportError:
    _VECTOR_AVAILABLE = False


# Minimum significance threshold to store a memory
SIGNIFICANCE_THRESHOLD = 0.45
# Replay influence on current emotion
REPLAY_VALENCE_INFLUENCE = 0.18
# Maximum memories to retrieve per query
DEFAULT_K = 3


class MemorySystemV2:
    """
    Emotionally-tagged vector memory with significance gating.

    Upgrade over Fixv2:
    - Only stores memories above significance threshold
    - Stores emotional context (valence, arousal) with each memory
    - Retrieval triggers emotional replay in BrainV2
    - Falls back to keyword search if sentence-transformers not available
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._fallback_memories: List[dict] = []

        if _VECTOR_AVAILABLE:
            try:
                self.client = chromadb.Client()
                self.collection = self.client.get_or_create_collection(
                    name=f"memory_v2_{user_id.replace('-', '_')}"
                )
                self.embedder = SentenceTransformer("all-MiniLM-L6-v2")
                self._vector_ready = True
            except Exception:
                self._vector_ready = False
        else:
            self._vector_ready = False

    # ── Storage ───────────────────────────────────────────────────────────────
    def store(
        self,
        text: str,
        emotion: dict,
        trust_delta: float = 0.0,
        attachment_delta: float = 0.0,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """
        Store a memory if it's emotionally significant.

        Significance = |valence| × 0.4 + |trust_delta| × 0.3 + |attachment_delta| × 0.3

        Returns:
            True if stored, False if filtered out
        """
        valence = float(emotion.get("valence", 0.0))
        arousal = float(emotion.get("arousal", 0.5))

        significance = (
            abs(valence)       * 0.4
            + abs(trust_delta)      * 0.3
            + abs(attachment_delta) * 0.3
        )

        if significance < SIGNIFICANCE_THRESHOLD:
            return False   # Not worth storing

        memory = {
            "id": str(uuid.uuid4()),
            "text": text,
            "valence": valence,
            "arousal": arousal,
            "trust_delta": trust_delta,
            "attachment_delta": attachment_delta,
            "significance": significance,
            "tags": tags or [],
            "timestamp": time.time(),
        }

        if self._vector_ready:
            try:
                embedding = self.embedder.encode(text).tolist()
                self.collection.add(
                    documents=[text],
                    embeddings=[embedding],
                    ids=[memory["id"]],
                    metadatas=[{
                        "valence": valence,
                        "arousal": arousal,
                        "significance": significance,
                        "timestamp": memory["timestamp"],
                    }],
                )
                return True
            except Exception:
                pass

        # Fallback: in-memory list (keeps last 100)
        self._fallback_memories.append(memory)
        self._fallback_memories = self._fallback_memories[-100:]
        return True

    # ── Retrieval ─────────────────────────────────────────────────────────────
    def retrieve(self, query: str, k: int = DEFAULT_K) -> List[dict]:
        """
        Retrieve k most relevant emotionally-significant memories.

        Returns list of memory dicts with emotional replay effect included.
        """
        if not query.strip():
            return []

        memories = []

        if self._vector_ready:
            try:
                embedding = self.embedder.encode(query).tolist()
                results = self.collection.query(
                    query_embeddings=[embedding],
                    n_results=min(k, self.collection.count() or 1),
                )
                docs      = results.get("documents", [[]])[0]
                metas     = results.get("metadatas", [[]])[0]
                for text, meta in zip(docs, metas):
                    memories.append({
                        "text": text,
                        "valence": meta.get("valence", 0.0),
                        "arousal": meta.get("arousal", 0.5),
                        "significance": meta.get("significance", 0.5),
                        "replay_effect": meta.get("valence", 0.0) * REPLAY_VALENCE_INFLUENCE,
                    })
            except Exception:
                pass

        if not memories and self._fallback_memories:
            # Naive keyword fallback: score by word overlap
            query_words = set(query.lower().split())
            scored = []
            for m in self._fallback_memories:
                words = set(m["text"].lower().split())
                score = len(query_words & words) / max(len(query_words), 1)
                scored.append((score, m))
            scored.sort(key=lambda x: x[0], reverse=True)
            for score, m in scored[:k]:
                if score > 0:
                    memories.append({
                        **m,
                        "replay_effect": m["valence"] * REPLAY_VALENCE_INFLUENCE,
                    })

        return memories

    # ── Replay ────────────────────────────────────────────────────────────────
    def compute_replay_effect(self, memories: List[dict]) -> float:
        """
        Compute total emotional replay effect from retrieved memories.
        Applied to current valence in BrainV2._update_emotion().
        """
        effect = 0.0
        for m in memories:
            weight = abs(m.get("valence", 0.0))
            if weight > 0.3:
                effect += m.get("valence", 0.0) * REPLAY_VALENCE_INFLUENCE * weight
        return round(effect, 4)

    def count(self) -> int:
        if self._vector_ready:
            try:
                return self.collection.count()
            except Exception:
                pass
        return len(self._fallback_memories)
