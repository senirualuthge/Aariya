"""
Cognitive Economy (*AccessFIles.txt* §78 — "when to think deeply, when to
respond fast, when to delegate").

Every task does not deserve full reasoning. This module measures REAL signals
per request and picks a reasoning tier:

    FAST      — short/simple/urgent turns, tiny token budget
    STANDARD  — normal conversation depth
    DEEP      — complex, uncertain, multi-step work

Signals used (nothing invented):
  * measured text features of the task itself (length, code/URL/path markers,
    multi-step conjunctions)
  * PriorityPipeline classification (social QoS, P0-P4)
  * MetaReasoner confidence for the matched agent
  * live EnergyManager mode (conservation/sleep bias toward cheaper tiers)
  * persisted outcome history: tiers that keep failing get escalated next time

No LLM call happens here; the decision is pure measurement so it stays cheap
enough to run on every turn.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.cognitive_economy")

_DATA_DIR = Path("./data")

_TIER_CAPS = {"fast": 200, "standard": 600, "deep": 1600}
_DEEP_AT = 0.62          # score >= this → DEEP
_STANDARD_AT = 0.34      # score >= this (and < deep) → STANDARD
_CONSERVATION_DISCOUNT = 0.15   # energy pressure pushes toward cheaper tiers
_ESCALATE_BELOW = 0.60   # FAST EMA success under this (>=5 samples) escalates
_MIN_PRIORITY_WEIGHT = {
    # Priority int → how much depth the social QoS implies
    0: 0.30,  # P0 emergency: latency beats depth (handled via fast path)
    1: 0.65,
    2: 0.50,
    3: 0.25,
    4: 0.10,
}

_CODE_MARKERS = ("def ", "class ", "import ", "```", "&&", "=>", "npm ", "pip ")
_STEP_MARKERS = (" then ", " after that", "step 1", "step 2", "first ", "finally ")
_QUICK_MARKERS = ("quick", "just", "simply", "briefly")


def _measured_features(text: str) -> Dict[str, Any]:
    """Measure the raw input text. These are observations, not guesses."""
    t = f" {str(text or '').lower()} "
    words = len(t.split())
    return {
        "words": words,
        "has_code": any(m in t for m in _CODE_MARKERS),
        "has_url": "http://" in t or "https://" in t or "www." in t,
        "has_path": ("/" in t.strip() or "\\" in t.strip()),
        "multi_step": any(m in t for m in _STEP_MARKERS),
        "wants_quick": any(f" {m} " in t for m in _QUICK_MARKERS),
    }


def _complexity(feat: Dict[str, Any]) -> float:
    if feat["words"] == 0:
        return 0.0
    if feat["words"] < 8:
        base = 0.20
    elif feat["words"] < 30:
        base = 0.50
    else:
        base = 0.80
    bonus = 0.0
    for flag in ("has_code", "has_url", "has_path", "multi_step"):
        if feat[flag]:
            bonus += 0.10
    if feat["wants_quick"]:
        bonus -= 0.15
    return round(min(1.0, max(0.0, base + bonus)), 3)


class CognitiveEconomy:
    """Decides per-task reasoning tier from real signals; learns from outcomes."""

    def __init__(self, stats_path: Optional[str] = None):
        self._lock = threading.Lock()
        self.stats_path = Path(stats_path) if stats_path else (_DATA_DIR / "cognitive_economy.json")
        # tier -> {"ema_success": float, "samples": int}
        self._tier_stats: Dict[str, Dict[str, float]] = {}
        self._decisions: deque = deque(maxlen=100)
        self._load_stats()

    # ── persistence ────────────────────────────────────────────────────────
    def _load_stats(self) -> None:
        try:
            if self.stats_path.exists():
                data = json.loads(self.stats_path.read_text(encoding="utf-8"))
                self._tier_stats = {k: dict(v) for k, v in data.get("tier_stats", {}).items()}
        except Exception as exc:
            logger.warning("[CognitiveEconomy] stats load failed: %s", exc)

    def _save_stats(self) -> None:
        try:
            self.stats_path.parent.mkdir(parents=True, exist_ok=True)
            self.stats_path.write_text(
                json.dumps({"tier_stats": self._tier_stats}, indent=2),
                encoding="utf-8")
        except Exception as exc:
            logger.warning("[CognitiveEconomy] stats save failed: %s", exc)

    # ── decision ───────────────────────────────────────────────────────────
    def decide(self, task_text: str, intent: Optional[str] = None,
               energy_mode: Optional[str] = None) -> Dict[str, Any]:
        from server.systems.priority_pipeline import get_priority_pipeline
        from server.systems.cognition.meta_reasoner import MetaReasoner

        text = str(task_text or "")
        feat = _measured_features(text)
        complexity = _complexity(feat)

        pipeline = get_priority_pipeline()
        priority = pipeline.classify(text)
        qos = pipeline.get_qos_params(priority)
        meta = MetaReasoner().evaluate({"query": text, "intent": intent})
        confidence = float(meta.get("confidence", 0.5))

        p_weight = _MIN_PRIORITY_WEIGHT.get(int(priority), 0.5)
        score = round(0.45 * complexity + 0.35 * (1.0 - confidence) + 0.20 * p_weight, 4)

        reasons: List[str] = [
            f"complexity={complexity} from {feat['words']} words"
            + (" +code/url/path/multi-step markers" if feat["has_code"] or feat["has_url"]
               or feat["has_path"] or feat["multi_step"] else ""),
            f"meta_confidence={confidence} ({meta.get('best_agent')})",
            f"priority=P{int(priority)}",
        ]

        defer = False
        try:
            if energy_mode is None:      # live probe when caller doesn't pin it
                from server.systems.resources.energy_manager import get_energy_manager
                energy_mode = get_energy_manager().evaluate().get("mode")
            if energy_mode == "conservation":
                score = round(score - _CONSERVATION_DISCOUNT, 4)
                reasons.append("energy=conservation → -0.15 depth bias")
            elif energy_mode == "sleep" and priority >= 3:
                defer = True
                reasons.append("energy=sleep & non-urgent → deferred")
        except Exception as exc:
            logger.debug("[CognitiveEconomy] energy unavailable: %s", exc)

        if defer:
            tier = "deferred"
        elif int(priority) == 0:
            tier = "fast"           # emergencies: ultra latency, tiny budget
            reasons.append("P0 emergency → latency over depth")
        elif feat["words"] <= 3 and int(priority) >= 2:
            tier = "fast"           # measured: tiny non-urgent turn = filler
            reasons.append(f"tiny turn ({feat['words']} words) → conversational filler")
        elif score >= _DEEP_AT:
            tier = "deep"
        elif score >= _STANDARD_AT:
            tier = "standard"
        else:
            tier = "fast"

        # Outcome-driven escalation: a FAST tier that keeps failing gets bumped.
        with self._lock:
            st = self._tier_stats.get("fast") or {}
            if tier == "fast" and int(st.get("samples", 0)) >= 5 \
                    and float(st.get("ema_success", 1.0)) < _ESCALATE_BELOW:
                tier = "standard"
                reasons.append("history: fast-tier success below 60% → escalated")

        budget = int(qos.get("max_tokens", 500)) or _TIER_CAPS[tier]
        budget = min(budget, _TIER_CAPS.get(tier, 600))

        decision_id = hashlib.sha1(
            f"{text[:120]}|{time.time():.6f}".encode("utf-8")).hexdigest()[:12]
        record = {
            "id": decision_id, "ts": time.time(),
            "tier": tier, "score": score, "complexity": complexity,
            "confidence": confidence, "priority": int(priority),
            "delegate_to": meta.get("best_agent"),
            "requires_verification": bool(meta.get("requires_verification")),
        }
        with self._lock:
            self._decisions.append(record)

        return {
            "decision_id": decision_id,
            "tier": tier,
            "score": score,
            "max_tokens": budget if tier != "deferred" else 0,
            "temperature": qos.get("temperature", 0.9),
            "latency_priority": qos.get("latency_priority", "normal"),
            "delegate_to": meta.get("best_agent"),
            "requires_verification": bool(meta.get("requires_verification")),
            "deferred": defer,
            "reasons": reasons,
            "features": feat,
        }

    def record_outcome(self, tier: str, ok: bool, duration_s: Optional[float] = None) -> Dict[str, Any]:
        tier = str(tier or "").lower()
        if tier not in _TIER_CAPS:
            return {"recorded": False, "reason": f"unknown tier: {tier}"}
        with self._lock:
            st = self._tier_stats.setdefault(tier, {"ema_success": 1.0, "samples": 0})
            n = int(st["samples"])
            alpha = 1.0 / (n + 1) if n < 20 else 0.05
            st["ema_success"] = round(st["ema_success"] * (1 - alpha) + (1.0 if ok else 0.0) * alpha, 4)
            st["samples"] = n + 1
            if duration_s is not None:
                prev = float(st.get("ema_duration_s", float(duration_s)))
                st["ema_duration_s"] = round(prev * 0.8 + float(duration_s) * 0.2, 3)
            self._save_stats()
        return {"recorded": True, "tier": tier, **self._tier_stats[tier]}

    def status(self) -> Dict[str, Any]:
        with self._lock:
            recent = list(self._decisions)[-10:]
            counts: Dict[str, int] = {}
            for d in self._decisions:
                counts[d["tier"]] = counts.get(d["tier"], 0) + 1
            return {
                "tier_stats": json.loads(json.dumps(self._tier_stats)),
                "decision_counts": counts,
                "recent": recent,
                "thresholds": {"deep_at": _DEEP_AT, "standard_at": _STANDARD_AT},
            }


_inst: Optional[CognitiveEconomy] = None


def get_cognitive_economy() -> CognitiveEconomy:
    global _inst
    if _inst is None:
        _inst = CognitiveEconomy()
    return _inst
