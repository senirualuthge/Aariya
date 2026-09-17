import chromadb
from chromadb.config import Settings
import hashlib
import time
from typing import Optional

class EpisodicMemory:
    """
    Stores semantically significant moments from conversations.
    Retrieves them mid-conversation when context is relevant.

    Memory tiers:
      Short-term  → last 20 turns (existing, in Redis)
      Episodic    → THIS — memorable moments, vector search
      Long-term   → personality EMA (existing, in SQLite)
    """

    # Only store turns above this emotional significance threshold
    SIGNIFICANCE_THRESHOLD = 0.45

    def __init__(self, user_id: str, persist_path: str = "./data/episodic"):
        self.user_id = user_id
        self.client = chromadb.PersistentClient(
            path=persist_path,
            settings=Settings(anonymized_telemetry=False)
        )
        self.collection = self.client.get_or_create_collection(
            name=f"user_{user_id}_episodes",
            metadata={"hnsw:space": "cosine"}
        )

    def _significance_score(
        self,
        valence: float,
        arousal: float,
        trust_delta: float,
        contradiction_ema: float
    ) -> float:
        """
        How memorable is this moment?
        High arousal, trust change, or contradiction = memorable.
        """
        emotional_intensity = abs(valence) * 0.4 + arousal * 0.4
        trust_importance    = abs(trust_delta) * 10.0          # small deltas, amplified
        contradiction_flag  = contradiction_ema * 0.3

        return min(emotional_intensity + trust_importance + contradiction_flag, 1.0)

    def maybe_store(
        self,
        user_text: str,
        ai_response: str,
        valence: float,
        arousal: float,
        trust_delta: float,
        contradiction_ema: float,
        social_intent: str,
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Conditionally stores a turn as an episodic memory.
        Returns True if stored, False if below significance threshold.
        """
        score = self._significance_score(valence, arousal, trust_delta, contradiction_ema)
        if score < self.SIGNIFICANCE_THRESHOLD:
            return False

        timestamp = time.time()
        doc_id = hashlib.md5(f"{self.user_id}{timestamp}{user_text[:30]}".encode()).hexdigest()

        # Store the episode (use upsert to avoid duplicate-ID warnings when
        # the same text arrives within the same millisecond).
        self.collection.upsert(
            ids=[doc_id],
            documents=[f"User: {user_text}\nAI: {ai_response}"],
            metadatas=[{
                "timestamp": int(timestamp),
                "valence": round(valence, 3),
                "arousal": round(arousal, 3),
                "trust_delta": round(trust_delta, 4),
                "significance": round(score, 3),
                "social_intent": social_intent,
                **(metadata or {})
            }]
        )
        return True

    def recall(
        self,
        current_text: str,
        n_results: int = 3,
        min_significance: float = 0.0
    ) -> list[dict]:
        """
        Retrieve relevant episodic memories for the current context.
        Call this before each LLM prompt to inject relevant history.
        """
        if self.collection.count() == 0:
            return []

        results = self.collection.query(
            query_texts=[current_text],
            n_results=min(n_results, self.collection.count()),
            where={"significance": {"$gte": min_significance}} if min_significance > 0 else None
        )

        memories = []
        for i, doc in enumerate(results["documents"][0]):  # type: ignore[index]
            meta = results["metadatas"][0][i]  # type: ignore[index]
            memories.append({
                "text": doc,
                "significance": meta.get("significance", 0),
                "timestamp": meta.get("timestamp", 0),
                "valence": meta.get("valence", 0),
                "social_intent": meta.get("social_intent", ""),
            })

        # Sort by relevance * recency
        memories.sort(key=lambda m: m["significance"], reverse=True)
        return memories

    def recall_candidates(
        self,
        current_text: str,
        n_results: int = 5,
        min_significance: float = 0.0
    ) -> list[dict]:
        """
        Recall raw results from ChromaDB for custom scoring.
        """
        if self.collection.count() == 0:
            return []

        results = self.collection.query(
            query_texts=[current_text],
            n_results=min(n_results, self.collection.count()),
            where={"significance": {"$gte": min_significance}} if min_significance > 0 else None
        )

        candidates = []
        for i, doc in enumerate(results["documents"][0]):  # type: ignore[index]
            meta = results["metadatas"][0][i]  # type: ignore[index]
            # dist is often returned by chroma depending on settings, if not we assume distance 0
            dist = results.get("distances", [[0]*n_results])[0][i]  # type: ignore[index]
            # convert distance to similarity (cosine distance is [0, 2], sim = 1 - dist/2 or similar)
            # but usually hnsw:space cosine returns 1-similarity or similar.
            sim = 1.0 - dist 

            candidates.append({
                "id": results["ids"][0][i],  # type: ignore[index]
                "content": doc,
                "metadata": meta,
                "semantic_similarity": sim
            })
        return candidates

    def format_for_prompt(self, memories: list[dict]) -> str:
        """
        Formats retrieved memories as a prompt injection block.
        Insert this into your system prompt before each LLM call.
        """
        if not memories:
            return ""

        lines = ["[Relevant memories from past conversations:]"]
        for m in memories:
            time_ago = int((time.time() - m["timestamp"]) / 3600)
            time_str = f"{time_ago}h ago" if time_ago < 48 else f"{time_ago // 24}d ago"
            lines.append(f"- ({time_str}, mood: {m['valence']:+.1f}) {m['text'][:200]}")

        return "\n".join(lines)
