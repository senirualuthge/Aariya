"""
Long-Term User Modeling (AccessFIles §44, §47 — Habit Tracking).

Learns recurring patterns about the user so the AI can anticipate needs:

  observe(evidence)   → feed turn-level signals (time-of-day, topic, mood, intent)
  habits              → repeated behaviors above a confidence threshold
  rhythm              → time-of-day / weekday activity distribution
  anticipation        → given current context, what is the user likely to do next
  top_predictions     → ranked habit-driven suggestions for predictive assistance

Data lives in Postgres-backed pattern_memory when available and falls back to
an in-memory store so it never blocks the pipeline.
"""

import time
import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

# Confidence to consider a pattern a "habit" (mirrors doc's 3+ occurrence rule).
_HABIT_CONFIDENCE = 0.6
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class UserModel:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self._memory_hierarchy = None
        self._hierarchy_working = True
        self._local_habits: Dict[str, Dict[str, Any]] = {}
        self._local_rhythm: Dict[str, int] = defaultdict(int)

    def _load_hierarchy(self) -> Optional[Any]:
        if self._memory_hierarchy is None:
            try:
                from server.systems.memory_hierarchy import get_memory_hierarchy
                hierarchy: Any = get_memory_hierarchy()
                # Probe the schema once: if pattern_memory is missing (fresh
                # DB), fall back to the in-memory store so observation never
                # blocks. execute_query returns None on a failed query.
                self._hierarchy_working = hierarchy.db.execute_query(
                    "SELECT 1 FROM pattern_memory LIMIT 1"
                ) is not None
                self._memory_hierarchy = hierarchy if self._hierarchy_working else False
            except Exception:
                self._memory_hierarchy = False
        return self._memory_hierarchy or None

    def observe(self, *, topic: Optional[str] = None, intent: Optional[str] = None,
                mood: Optional[str] = None) -> Dict[str, Any]:
        """Feed one turn of evidence. Stores into pattern_memory + local rhythm."""
        ts = time.time()
        local = time.localtime(ts)
        hour = local.tm_hour
        weekday = _WEEKDAYS[local.tm_wday]

        # Rhythm bucket (evening/week/morning, weekend/weekday)
        period = "evening" if hour >= 18 else ("afternoon" if hour >= 12 else "morning")
        kind = "weekend" if local.tm_wday >= 5 else "weekday"
        rhythm_key = f"{kind}:{period}"
        self._local_rhythm[rhythm_key] += 1

        evidence: Dict[str, Any] = {"timestamp": ts, "hour": hour, "weekday": weekday}
        if topic:
            evidence["topic"] = str(topic)[:120]
        if intent:
            evidence["intent"] = str(intent)[:60]
        if mood:
            evidence["mood"] = str(mood)[:40]

        hierarchy = self._load_hierarchy()
        if hierarchy:
            try:
                # Store a behavioral pattern keyed by topic+intent.
                desc = f"{topic or 'general'}:{intent or 'interaction'}"
                hierarchy.store_pattern(
                    self.user_id,
                    pattern_type="behavioral",
                    pattern_description=desc,
                    confidence=0.4,
                )
                hierarchy.detect_pattern(
                    self.user_id,
                    session_id=f"turn_{int(ts)}",
                    behavior_description=topic or intent or "",
                    pattern_type="behavioral",
                )
            except Exception:
                pass
        else:
            self._local_update(evidence)

        return {"recorded": True, "rhythm": rhythm_key}

    def _local_update(self, evidence: Dict[str, Any]) -> None:
        desc = f"{evidence.get('topic', 'general')}:{evidence.get('intent', 'interaction')}"
        h = self._local_habits.setdefault(desc, {
            "description": desc, "occurrences": 0, "confidence": 0.0,
            "last_observed": 0.0, "topics": [], "intents": [],
        })
        h["occurrences"] += 1
        h["confidence"] = min(1.0, h["occurrences"] / 5.0 + 0.1)  # 3 runs ≈ 0.7
        h["last_observed"] = evidence["timestamp"]
        if evidence.get("topic") and evidence["topic"] not in h["topics"]:
            h["topics"].append(evidence["topic"])
        if evidence.get("intent") and evidence["intent"] not in h["intents"]:
            h["intents"].append(evidence["intent"])

    # ── Habits ─────────────────────────────────────────────────────────────────

    def habits(self, min_confidence: float = _HABIT_CONFIDENCE) -> List[Dict[str, Any]]:
        hierarchy = self._load_hierarchy()
        if hierarchy:
            try:
                rows = hierarchy.recall_patterns(self.user_id, "behavioral", min_confidence) or []
                return [
                    {"description": r.get("pattern_description"), "confidence": r.get("confidence"),
                     "occurrences": r.get("occurrences"), "last_observed": r.get("last_observed")}
                    for r in rows
                ]
            except Exception:
                return []
        return [
            {"description": h["description"], "confidence": h["confidence"],
             "occurrences": h["occurrences"], "last_observed": h["last_observed"],
             "topics": h["topics"], "intents": h["intents"]}
            for h in self._local_habits.values()
            if h["confidence"] >= min_confidence
        ]

    # ── Rhythm ─────────────────────────────────────────────────────────────────

    def rhythm(self) -> Dict[str, Any]:
        """Time-of-day activity distribution: which periods is the user active?"""
        total = sum(self._local_rhythm.values())
        if not total:
            return {"distribution": {}, "peak": None}
        dist = {k: round(v / total, 3) for k, v in sorted(self._local_rhythm.items(), key=lambda x: -x[1])}
        return {"distribution": dist, "peak": next(iter(dist), None)}

    # ── Anticipation ───────────────────────────────────────────────────────────

    def anticipate(self, current_topic: Optional[str] = None, current_intent: Optional[str] = None,
                   top_k: int = 3) -> List[Dict[str, Any]]:
        """
        Predictive assistance: given the current context, what is the user most
        likely to do next? Ranks habits by confidence, boosting exact-topic and
        exact-intent matches, and applies mild recency boost.
        """
        now = time.time()
        scored = []
        for h in self.habits(min_confidence=0.3):
            desc = str(h.get("description") or "")
            boost = 0.0
            if current_topic and current_topic.lower() in desc.lower():
                boost += 0.2
            if current_intent and current_intent.lower() in desc.lower():
                boost += 0.15
            # last_observed may be an epoch float (local habits) or a DATETIME
            # string (pattern_memory rows — DATETIME DEFAULT CURRENT_TIMESTAMP).
            ts = h.get("last_observed", now)
            try:
                ts = float(ts) if not isinstance(ts, str) else \
                    datetime.fromisoformat(str(ts)).timestamp()
            except (TypeError, ValueError):
                ts = now
            recency = max(0.0, 1.0 - (now - ts) / (30 * 86400.0))
            scored.append({
                "suggestion": desc,
                "score": round(float(h.get("confidence", 0.0)) + boost + 0.1 * recency, 3),
            })
        scored.sort(key=lambda s: -s["score"])
        return scored[:top_k]

    def summary(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "habits": self.habits(),
            "rhythm": self.rhythm(),
            "anticipations": self.anticipate(),
        }


def get_user_model(user_id: str) -> UserModel:
    return UserModel(user_id)
