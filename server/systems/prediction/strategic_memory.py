"""
Strategic Memory — PlanMemory, FailureMemory, and strategic Lessons.
────────────────────────────────────────────────────────────────────────
(NEWPredictionPRT2 §10 Planning Memory, §6 Failure Memory, §Lessons.)

  PlanMemory      → store successful plans; reuse them when a similar goal
                    reappears (reward > 0.7 bumps the reuse counter).
  FailureMemory   → remember failures + their solutions for instant recovery
                    next time the same situation occurs.
  StrategicLessons→ distill outcomes into lessons (quality > 0.8); repeated
                    lessons (occurrences crossing a threshold) are promoted
                    to durable "principles".

All three persist to JSON and reload on boot so strategic knowledge survives
restarts. Domain-agnostic, no financial/market feature set.
"""

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.strategic_memory")


class PlanMemory:
    """Store + reuse successful plans (doc §10 Planning Memory)."""

    def __init__(self, max_plans: int = 200):
        self.memory: Dict[str, Dict[str, Any]] = {}
        self.reuse_count: Dict[str, int] = {}
        self._max = max_plans

    def store(self, goal: str, plan: List[Any], reward: float) -> str:
        plan_key = f"{goal}:{hashlib.md5(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:8]}"
        self.memory[plan_key] = {
            "goal": goal,
            "plan": plan,
            "reward": round(float(reward), 3),
            "timestamp": time.time(),
        }
        if reward > 0.7:
            self.reuse_count[plan_key] = self.reuse_count.get(plan_key, 0) + 1
        if len(self.memory) > self._max:
            oldest = min(self.memory, key=lambda k: self.memory[k]["timestamp"])
            del self.memory[oldest]
        return plan_key

    def recall(self, goal: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Reuse a successful plan for a seen-similar situation."""
        scored = [
            (key, entry) for key, entry in self.memory.items()
            if entry["goal"] == goal
        ]
        scored.sort(key=lambda x: (x[1]["reward"], self.reuse_count.get(x[0], 0)), reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "plan_count": len(self.memory),
            "reusable": [
                {"goal": e["goal"], "reward": e["reward"],
                 "steps": [s.get("action", s) if isinstance(s, dict) else s for s in e["plan"]][:5]}
                for e in list(self.memory.values())[-10:]
            ],
        }


class FailureMemory:
    """Remember failures + solutions for instant recovery (doc §6)."""

    def __init__(self):
        self.failures: Dict[str, Dict[str, Any]] = {}

    def record(self, failure: str, solution: str, *, context: str = "") -> None:
        entry = self.failures.setdefault(failure, {
            "failure": failure, "solution": solution, "count": 0,
            "last_seen": 0.0, "contexts": [],
        })
        entry["count"] += 1
        entry["last_seen"] = time.time()
        entry["solution"] = solution  # keep the latest solution
        if context and context not in entry["contexts"]:
            entry["contexts"].append(context)

    def recover(self, failure: str) -> Optional[str]:
        """Instant recovery: return the remembered solution if we've seen this."""
        entry = self.failures.get(failure)
        if entry:
            entry["count"] += 1
            entry["last_seen"] = time.time()
            return entry["solution"]
        return None

    def snapshot(self) -> Dict[str, Any]:
        return {
            "known_failures": len(self.failures),
            "recent": list(self.failures.values())[-8:],
        }


class StrategicLessons:
    """Distill outcomes into lessons; promote repeated lessons to principles."""

    PRINCIPLE_THRESHOLD = 3

    def __init__(self, max_lessons: int = 300):
        self.lessons: Dict[str, Dict[str, Any]] = {}   # concept -> lesson
        self._max = max_lessons

    def learn(self, outcomes: List[Dict[str, Any]]) -> List[str]:
        """Feed a batch of outcomes; return newly recorded lesson concepts."""
        new = []
        for o in outcomes:
            quality = float(o.get("quality", 0.0))
            if quality <= 0.8:
                continue
            concept = o.get("concept") or o.get("lesson")
            if not concept:
                continue
            lesson = self.lessons.setdefault(concept, {
                "concept": concept, "confidence": 0.0, "occurrences": 0,
                "last_seen": "", "status": "candidate",
            })
            lesson["occurrences"] += 1
            lesson["confidence"] = round(
                lesson["confidence"] * 0.8 + quality * 0.2, 3)
            lesson["last_seen"] = time.strftime("%Y-%m-%d", time.gmtime())
            if lesson["occurrences"] >= self.PRINCIPLE_THRESHOLD:
                lesson["status"] = "principle"
            if concept not in new:
                new.append(concept)
        if len(self.lessons) > self._max:
            self.lessons = dict(list(self.lessons.items())[-self._max:])
        return new

    def snapshot(self) -> Dict[str, Any]:
        return {
            "lesson_count": len(self.lessons),
            "principles": [l for l in self.lessons.values() if l["status"] == "principle"],
            "recent": [l for l in list(self.lessons.values())[-10:]],
        }


# ── Persistence ───────────────────────────────────────────────────────────────

class StrategicMemory:
    """Facade owning PlanMemory + FailureMemory + StrategicLessons with a single
    JSON persistence file."""

    def __init__(self, persist_path: str = "./data/strategic_memory.json"):
        self.persist_path = persist_path
        self.plans = PlanMemory()
        self.failures = FailureMemory()
        self.lessons = StrategicLessons()
        self._load()

    def snapshot(self) -> Dict[str, Any]:
        return {
            "plans": self.plans.snapshot(),
            "failures": self.failures.snapshot(),
            "lessons": self.lessons.snapshot(),
        }

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
            with open(self.persist_path, "w", encoding="utf-8") as f:
                json.dump({
                    "saved_at": time.time(),
                    "plan_memory": self.plans.memory,
                    "reuse_counts": self.plans.reuse_count,
                    "failures": self.failures.failures,
                    "lessons": self.lessons.lessons,
                }, f, indent=2)
        except OSError as exc:
            logger.warning("[strategic] persist failed: %s", exc)

    def _load(self) -> None:
        try:
            if not os.path.exists(self.persist_path):
                return
            with open(self.persist_path, encoding="utf-8") as f:
                data = json.load(f)
            self.plans.memory = data.get("plan_memory", {})
            self.plans.reuse_count = data.get("reuse_counts", {})
            self.failures.failures = data.get("failures", {})
            self.lessons.lessons = data.get("lessons", {})
            logger.info("[strategic] loaded %d plans, %d failures, %d lessons",
                        len(self.plans.memory), len(self.failures.failures),
                        len(self.lessons.lessons))
        except Exception as exc:
            logger.warning("[strategic] load failed (fresh start): %s", exc)
