"""
Memory Consolidation + Decay + Importance (AdvancedPrediction §Memory-Decay).

Adds the three missing memory mechanisms on top of EpisodicMemory:

  decay            → significance decays with age (Ebbinghaus curve), so old
                     un-reinforced memories fade unless re-accessed.
  reinforcement    → re-accessing a memory restores/boosts its significance.
  consolidation    → periodically merges near-duplicate episodes (same
                     social_intent + topic) into a single summary entry.
  importance       → access-weighted importance score drives recall priority.

Works on the chromadb-backed EpisodicMemory collection, so nothing else in the
pipeline changes — this layer just makes memories that already exist smarter.
"""

import time
import hashlib
from typing import Any, Dict, List, Optional

# Half-life in seconds: significance halves after ~30 days without access.
_HALF_LIFE = 30 * 24 * 3600.0


class MemoryConsolidator:
    def __init__(self, episodic_memory):
        self._mem = episodic_memory

    # ── Decay ──────────────────────────────────────────────────────────────────

    @staticmethod
    def _decay_factor(age_seconds: float) -> float:
        """Ebbinghaus-style exponential decay: 1.0 now → 0.5 at half-life."""
        return 0.5 ** (age_seconds / _HALF_LIFE)

    def decay(self) -> Dict[str, Any]:
        """Apply time-based decay to every memory's significance. Returns a
        summary of how much the store shrank."""
        try:
            col = self._mem.collection
            count = col.count()
            if count == 0:
                return {"decayed": 0, "total": 0}
            all_rows = col.get()
            now = time.time()
            updated = []
            for i, cid in enumerate(all_rows["ids"]):
                meta = dict(all_rows["metadatas"][i] or {})
                ts = float(meta.get("timestamp", now))
                age = max(0.0, now - ts)
                old = float(meta.get("significance", 0.0))
                factor = self._decay_factor(age)
                new = round(old * factor, 3)
                meta["significance"] = new
                meta["decay_factor"] = round(factor, 3)
                updated.append((cid, meta))
            for cid, meta in updated:
                col.update(ids=[cid], metadatas=[meta])
            return {
                "decayed": len(updated),
                "total": count,
                "strongest_remaining": max(
                    (float(m.get("significance", 0)) for _, m in updated), default=0.0),
            }
        except Exception as e:
            return {"error": str(e)[:120]}

    # ── Reinforcement ──────────────────────────────────────────────────────────

    def reinforce(self, current_text: str, n: int = 3) -> Dict[str, Any]:
        """Boost significance of memories relevant to the current text
        (simulating hippocampal re-access strengthening a trace)."""
        recalled = self._mem.recall(current_text, n_results=n)
        if not recalled:
            return {"reinforced": 0}
        col = self._mem.collection
        now = time.time()
        count = 0
        for mem in recalled:
            # Re-query by text match — find the doc id via metadata timestamp+text
            matching = col.get(where={"significance": mem["significance"]})
            for i, m in enumerate(matching["metadatas"]):
                if float(m.get("timestamp", 0)) == float(mem["timestamp"]):
                    boost = round(float(m.get("significance", 0.3)) * 0.1 + 0.05, 3)
                    m["significance"] = min(round(float(m.get("significance", 0.0)) + boost, 3), 1.0)
                    m["access_count"] = int(m.get("access_count", 0)) + 1
                    m["last_access"] = now
                    col.update(ids=[matching["ids"][i]], metadatas=[m])
                    count += 1
        return {"reinforced": count}

    # ── Consolidation ──────────────────────────────────────────────────────────

    def consolidate(self) -> Dict[str, Any]:
        """Merge episodes sharing a social_intent bucket + close timestamps into
        one summary entry, marking originals as consolidated."""
        try:
            col = self._mem.collection
            count = col.count()
            if count == 0:
                return {"merged": 0, "groups": 0}
            rows = col.get()
            buckets: Dict[str, List[int]] = {}
            for i, cid in enumerate(rows["ids"]):
                meta = rows["metadatas"][i] or {}
                intent = str(meta.get("social_intent", "unknown"))
                day = int(float(meta.get("timestamp", 0))) // (12 * 3600)  # 12h window
                buckets.setdefault(f"{intent}:{day}", []).append(i)
            groups = [idxs for idxs in buckets.values() if len(idxs) > 1]
            merged = 0
            for idxs in groups:
                merged += self._merge_group(rows, idxs)
            return {"merged": merged, "groups": len(groups), "total": count}
        except Exception as e:
            return {"error": str(e)[:120]}

    def _merge_group(self, rows: Dict[str, List[Any]], idxs: List[int]) -> int:
        """Merge one group of rows into a summary; returns count merged away."""
        col = self._mem.collection
        group = [{
            "id": rows["ids"][i],
            "doc": rows["documents"][i],
            "meta": rows["metadatas"][i] or {},
        } for i in idxs]
        summary_text = "\n".join(g["doc"][:120] for g in group)
        combined = {
            "significance": round(sum(float(g["meta"].get("significance", 0)) for g in group) / len(group), 3),
            "timestamp": min(float(g["meta"].get("timestamp", 0)) for g in group),
            "valence": round(sum(float(g["meta"].get("valence", 0)) for g in group) / len(group), 3),
            "social_intent": group[0]["meta"].get("social_intent", "unknown"),
            "consolidated_from": len(group),
            "access_count": sum(int(g["meta"].get("access_count", 0)) for g in group),
        }
        new_id = hashlib.md5(f"consol:{combined['timestamp']}:{combined['social_intent']}".encode()).hexdigest()
        try:
            col.upsert(ids=[new_id], documents=[summary_text], metadatas=[combined])
            col.delete(ids=[g["id"] for g in group])
        except Exception:
            return 0
        return len(group)

    # ── Importance-weighted recall ─────────────────────────────────────────────

    def importance_ranked_recall(self, current_text: str, n: int = 5) -> List[Dict[str, Any]]:
        """Recall sorted by importance = significance × access-weighted recency."""
        recalled = self._mem.recall(current_text, n_results=n)
        now = time.time()
        def _importance(m: Dict[str, Any]) -> float:
            recency = now - float(m.get("timestamp", 0))
            decay = self._decay_factor(max(recency, 0.0))
            return float(m.get("significance", 0)) * decay
        recalled.sort(key=_importance, reverse=True)
        for m in recalled:
            m["importance"] = round(_importance(m), 3)
        return recalled
