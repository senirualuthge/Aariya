"""
Human Collaboration Model (*AccessFIles.txt* §96).

A collaborator, not a command runner: this module decides — from REAL,
measured signals — when Aariya should

    * proceed silently,
    * proceed while communicating her confidence ("proceed_with_caveat"),
    * or stop and ask ONE clarifying question.

Measured inputs (nothing invented):
  * MetaReasoner confidence for the matched agent/domain
  * ambiguity features measured from the raw text: unresolved pronouns,
    how many distinct capability-domains the request could belong to,
    imperative verbs with no object, hedging language
  * feedback history: whether past clarifying questions actually got answers
    (an unanswered-question habit raises the bar for asking again)
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("aariya.clarification_policy")

_DATA_DIR = Path("./data")

# Capability domains with observable keyword signatures. Used to MEASURE how
# many distinct interpretations a request admits — never to fake an answer.
_DOMAIN_KEYWORDS = {
    "filesystem": ("file", "folder", "directory", "path", "disk", "drive", "rename", "move "),
    "web": ("http", "site", "website", "url", "browser", "page", "search online"),
    "code": ("code", "function", "bug", "refactor", "repo", "python", "script"),
    "memory": ("remember", "recall", "memory", "last time", "history"),
    "planning": ("plan", "schedule", "goal", "roadmap", "steps"),
    "social": ("feel", "mood", "stress", "talk", "chat"),
}

_PRONOUNS = ("it", "that", "this", "them", "those", "these")
_HEDGES = ("maybe", "not sure", "or something", "whatever", "i guess", "possibly")

_OBJECT_VERBS = ("open ", "delete ", "launch ", "run ", "move ", "rename ", "close ")

_THRESHOLD_FLOOR, _THRESHOLD_CEIL = 0.30, 0.70


class ClarificationPolicy:
    def __init__(self, stats_path: Optional[str] = None):
        self._lock = threading.Lock()
        self.stats_path = Path(stats_path) if stats_path else (_DATA_DIR / "clarification_policy.json")
        self.ask_threshold = 0.50      # net confidence below this → ask
        self._asked = 0
        self._answered = 0
        self.history: Deque[Dict[str, Any]] = deque(maxlen=100)
        self._load_stats()

    # ── persistence ────────────────────────────────────────────────────────
    def _load_stats(self) -> None:
        try:
            if self.stats_path.exists():
                d = json.loads(self.stats_path.read_text(encoding="utf-8"))
                self.ask_threshold = float(d.get("ask_threshold", 0.50))
                self._asked = int(d.get("asked", 0))
                self._answered = int(d.get("answered", 0))
        except Exception as exc:
            logger.warning("[Clarification] stats load failed: %s", exc)

    def _save_stats(self) -> None:
        try:
            self.stats_path.parent.mkdir(parents=True, exist_ok=True)
            self.stats_path.write_text(json.dumps({
                "ask_threshold": round(self.ask_threshold, 4),
                "asked": self._asked, "answered": self._answered,
            }, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("[Clarification] stats save failed: %s", exc)

    # ── measurement ────────────────────────────────────────────────────────
    @staticmethod
    def _measure(text: str) -> Dict[str, Any]:
        t = f" {str(text or '').lower()} "
        words = [w.strip(".,!?;:'\"()") for w in t.split()]
        n_words = max(1, len(words))

        pronouns = sum(1 for w in words if w in _PRONOUNS)
        domains_hit = sorted(
            d for d, kws in _DOMAIN_KEYWORDS.items()
            if any(f" {k}" in t or t.startswith(f" {k}") for k in kws))
        hedge = next((h for h in _HEDGES if h in t), None)

        first_word = words[0] if words else ""
        verb_no_object = (
            f"{first_word} " in tuple(_OBJECT_VERBS) and n_words <= 2)

        return {
            "words": n_words,
            "pronoun_count": pronouns,
            "pronoun_score": min(1.0, pronouns / 2.0),
            "domains_hit": domains_hit,
            "domain_spread": min(1.0, max(0.0, (len(domains_hit) - 1) / 2.0)),
            "hedge": hedge,
            "verb_without_object": bool(verb_no_object),
        }

    # ── decision ───────────────────────────────────────────────────────────
    def decide(self, text: str, intent: Optional[str] = None,
               confidence: Optional[float] = None) -> Dict[str, Any]:
        if confidence is None:
            from server.systems.cognition.meta_reasoner import MetaReasoner
            confidence = float(MetaReasoner().evaluate(
                {"query": text, "intent": intent}).get("confidence", 0.5))

        m = self._measure(text)
        ambiguity = round(min(1.0, (
            0.40 * m["domain_spread"]
            + 0.25 * m["pronoun_score"]
            + 0.20 * (0.34 if m["verb_without_object"] else 0.0)
            + 0.15 * (0.34 if m["hedge"] else 0.0))), 4)

        with self._lock:
            threshold = self.ask_threshold
        net = round(confidence * (1.0 - 0.5 * ambiguity), 4)

        if net < threshold:
            action = "ask_clarification"
        elif net < threshold + 0.20:
            action = "proceed_with_caveat"
        else:
            action = "proceed"

        question: Optional[str] = None
        if action == "ask_clarification":
            options = m["domains_hit"][:3]
            if m["verb_without_object"]:
                question = f"{text.strip().capitalize()} — what should that apply to?"
            elif options:
                opts = " or ".join(options)
                question = (f"That could mean several things ({opts}) — "
                            f"which one did you mean?")
            elif m["pronoun_count"]:
                question = "Which exact item does \"it\" refer to?"
            else:
                question = "Can you tell me a bit more about what you need?"

        band = ("high" if net >= 0.75 else "medium" if net >= 0.50 else "low")
        decision = {
            "ts": time.time(),
            "action": action,
            "net_confidence": net,
            "raw_confidence": round(float(confidence), 4),
            "ambiguity": ambiguity,
            "confidence_band": band,
            "measured": m,
            "question": question,
            "caveat": (f"(confidence: {band})" if action == "proceed_with_caveat" else None),
        }
        with self._lock:
            self.history.append(decision)
        return decision

    # ── feedback loop ──────────────────────────────────────────────────────
    def record_outcome(self, asked: bool, answered: Optional[bool] = None) -> Dict[str, Any]:
        """Unanswered questions raise the bar for asking again; answered ones
        lower it slightly. Bounded adaptation, persisted."""
        with self._lock:
            if asked:
                self._asked += 1
                if answered is False:
                    self.ask_threshold = min(_THRESHOLD_CEIL, self.ask_threshold + 0.02)
                elif answered is True:
                    self.ask_threshold = max(_THRESHOLD_FLOOR, self.ask_threshold - 0.02)
            self._save_stats()
            return {"ask_threshold": round(self.ask_threshold, 4),
                    "asked": self._asked, "answered": self._answered}

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {"ask_threshold": round(self.ask_threshold, 4),
                    "asked": self._asked, "answered": self._answered,
                    "recent": list(self.history)[-10:]}


_inst: Optional[ClarificationPolicy] = None


def get_clarification_policy() -> ClarificationPolicy:
    global _inst
    if _inst is None:
        _inst = ClarificationPolicy()
    return _inst
