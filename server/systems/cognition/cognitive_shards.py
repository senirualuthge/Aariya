"""
Cognitive Sharding (AccessFIles §86 — gap fill).

One monolithic reasoner becomes inefficient, so cognition is split into
DOMAIN SHARDS — each backed by a REAL subsystem (episodic recall, knowledge
graph, user model, cognitive kernel, code index, system health) — and a
dispatcher routes tasks to shards by domain keywords and runs them with a
timeout. fan_out() executes several shards concurrently.

Nothing is seeded: dispatching against an empty store returns that store's
real empty result; dispatching an unroutable task honestly reports
handled=False instead of guessing.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("aariya.cognitive_shards")

DEFAULT_TIMEOUT_S = 10.0

# Domain keyword routing table (routing config, not data).
_DOMAIN_KEYWORDS: Dict[str, tuple] = {
    "memory": ("memory", "remember", "recall", "episode", "forget", "past"),
    "knowledge": ("graph", "entity", "relation", "triple", "knows", "linked"),
    "social": ("user", "habit", "preference", "mood", "trust", "attachment", "relationship"),
    "planning": ("plan", "goal", "focus", "priority", "world", "state", "next step"),
    "code": ("code", "symbol", "function", "class", "repo", "import", "refactor"),
    "system": ("cpu", "battery", "thermal", "health", "load", "resources", "disk"),
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(name or "").lower()).strip("_")


# ── Real subsystem handlers (lazy imports; read-only queries) ─────────────────

def _shard_memory(params: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    from server.systems.memory.episodic_memory import EpisodicMemory
    query = str(params.get("query") or params.get("text") or "").strip()
    if not query:
        return {"note": "no query given"}
    memories = EpisodicMemory(user_id).recall(query, n_results=int(params.get("limit", 3)))
    return {"memories": memories, "count": len(memories)}


def _shard_knowledge(params: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    from server.systems.agent.knowledge_graph import kg
    entity = str(params.get("entity") or params.get("query") or params.get("text") or "").strip()
    if not entity:
        return {"note": "no entity given"}
    rows = kg.query(entity)
    return {"entity": entity, "relations": rows, "count": len(rows)}


def _shard_social(params: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    from server.systems.user_model import get_user_model
    return get_user_model(user_id).summary()


def _shard_planning(params: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    from server.systems.cognition.cognitive_kernel import get_cognitive_kernel
    return get_cognitive_kernel().snapshot()


def _shard_code(params: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    from server.systems.agent.code_indexer import symbol_usages
    symbol = str(params.get("symbol") or params.get("query") or params.get("text") or "").strip()
    if not symbol:
        return {"note": "no symbol given"}
    usage = symbol_usages(symbol)
    return {"symbol": symbol, **usage}


def _shard_system(params: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    import psutil
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
        "loadavg": [round(x, 2) for x in (psutil.getloadavg() if hasattr(psutil, "getloadavg") else ())],
    }


_DEFAULT_SHARDS: Dict[str, Dict[str, Any]] = {
    "memory": {"handler": _shard_memory,
               "description": "Episodic memory recall over real stored episodes."},
    "knowledge": {"handler": _shard_knowledge,
                  "description": "Knowledge-graph entity/relation queries."},
    "social": {"handler": _shard_social,
               "description": "User-model habits, rhythm and anticipations."},
    "planning": {"handler": _shard_planning,
                 "description": "Cognitive-kernel world model / goal-tree snapshot."},
    "code": {"handler": _shard_code,
             "description": "AST code-index symbol usage lookups."},
    "system": {"handler": _shard_system,
               "description": "Live psutil resource snapshot."},
}


class CognitiveShards:
    """Registry + keyword router + timeout dispatcher for cognition shards."""

    def __init__(self, user_id: str = "user_default"):
        self.user_id = user_id
        self._shards: Dict[str, Dict[str, Any]] = {}
        self._last_latency: Dict[str, float] = {}
        self._last_error: Dict[str, str] = {}
        for name, spec in _DEFAULT_SHARDS.items():
            self.register(name, spec["handler"], description=spec["description"])

    # ── registry ──────────────────────────────────────────────────────────

    def register(self, name: str, handler: Callable[..., Dict[str, Any]],
                 *, description: str = "", domains: Optional[tuple] = None) -> None:
        key = _slug(name)
        if not key or not callable(handler):
            raise ValueError("shard needs a name and callable handler")
        self._shards[key] = {
            "handler": handler,
            "description": description,
            "domains": tuple(domains) if domains else (key,),
        }

    def shard_names(self) -> List[str]:
        return sorted(self._shards)

    # ── routing ───────────────────────────────────────────────────────────

    def route(self, task_text: str) -> Optional[str]:
        """Best-matching shard for free text, or None when nothing matches."""
        text = f" {str(task_text or '').lower()} "
        best: Optional[str] = None
        best_score = 0
        # Later registrations win ties — newly added specialist shards can
        # shadow the built-in defaults without touching this module.
        for shard, spec in self._shards.items():
            score = 0
            for kw in set(sum((list(_DOMAIN_KEYWORDS.get(d, ())) for d in spec["domains"]), [])):
                if f" {kw} " in text or f" {kw}s " in text:
                    score += 1
            if score >= best_score and score > 0:
                best, best_score = shard, score
        return best

    # ── execution ─────────────────────────────────────────────────────────

    async def dispatch(self, task_text: str, *, params: Optional[Dict[str, Any]] = None,
                       timeout_s: float = DEFAULT_TIMEOUT_S) -> Dict[str, Any]:
        """Run the routed shard handler (in an executor thread) with a timeout."""
        shard = self.route(task_text)
        if shard is None:
            return {"handled": False, "task": str(task_text)[:200],
                    "reason": "no shard matched"}
        spec = self._shards[shard]
        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: spec["handler"](dict(params or {}), self.user_id)),
                timeout=timeout_s,
            )
            latency = round((time.perf_counter() - started) * 1000.0, 2)
            self._last_latency[shard] = latency
            self._last_error.pop(shard, None)
            return {"handled": True, "shard": shard, "ok": True,
                    "result": result, "latency_ms": latency}
        except asyncio.TimeoutError:
            self._last_error[shard] = f"timeout after {timeout_s}s"
            return {"handled": True, "shard": shard, "ok": False, "error": "timeout"}
        except Exception as exc:
            self._last_error[shard] = str(exc)[:200]
            return {"handled": True, "shard": shard, "ok": False,
                    "error": str(exc)[:200]}

    async def fan_out(self, tasks: List[str], *,
                      timeout_s: float = DEFAULT_TIMEOUT_S) -> List[Dict[str, Any]]:
        """Dispatch several tasks across shards concurrently."""
        routable = [t for t in tasks if self.route(t) is not None]
        if not routable:
            return [{"handled": False, "task": str(t)[:200],
                     "reason": "no shard matched"} for t in tasks]
        results = await asyncio.gather(*(self.dispatch(t, timeout_s=timeout_s)
                                         for t in tasks))
        return list(results)

    # ── observability ─────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        shards = {}
        for name, spec in self._shards.items():
            shards[name] = {
                "description": spec["description"],
                "domains": list(spec["domains"]),
                "last_latency_ms": self._last_latency.get(name),
                "last_error": self._last_error.get(name),
            }
        return {"shards": shards, "count": len(shards), "user_id": self.user_id}


_instances: Dict[str, CognitiveShards] = {}


def get_cognitive_shards(user_id: str = "user_default") -> CognitiveShards:
    key = _slug(user_id)
    inst = _instances.get(key)
    if inst is None:
        inst = CognitiveShards(user_id)
        _instances[key] = inst
    return inst
