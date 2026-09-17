"""
Local LLM routing + MCP-style tool ecosystem (AccessFIles §60, §50 — gaps).

Two missing pieces:

  1. LOCAL_LLM_ROUTER — decides whether a task goes to the fast local model
     (Ollama/LM-Studio, cheap, offline) or the hosted model, based on task
     class, cost, and connectivity. Prevents every micro-call hammering the
     cloud endpoint.
  2. MCP_REGISTRY — a light in-process tool registry mirroring the MCP
     tool-schema shape (name/description/inputSchema). Real MCP servers can be
     adapted onto it; for now it exposes the built-in capability set so the
     governor/meta-reasoner have one place to enumerate tools.
"""

from typing import Any, Callable, Dict, List, Optional
import json
import logging
import os
import threading

logger = logging.getLogger("aariya.llm_router")

# ── Task classes ────────────────────────────────────────────────────────────────
# Heavy reasoning/coding → remote (or a strong local). Cheap chores →
# local. Fast & deterministic → no LLM at all (cache / rule).
_HEAVY = {"code", "refactor", "debug", "research", "plan", "reason"}
_LIGHT = {"sentiment", "classify", "summarize", "title", "route", "extract"}


class LLMRouter:
    def __init__(self, remote, local):
        self._remote = remote   # LLMEngine (hosted or default)
        self._local = local     # LLMEngine pointed at Ollama/LM-Studio
        self._hits: Dict[str, int] = {}

    @classmethod
    def from_engines(cls, remote, local) -> "LLMRouter":
        return cls(remote, local)

    def route(self, task_type: str, *, latency_budget_ms: int = 0) -> str:
        """Pick 'remote' | 'local' | 'none' for a task type."""
        t = str(task_type or "").lower()
        if t in _LIGHT:
            choice = "local"
        elif t in _HEAVY:
            choice = "remote"
        else:
            choice = "local"
        if latency_budget_ms and latency_budget_ms < 100:
            choice = "none"
        self._hits[choice] = self._hits.get(choice, 0) + 1
        return choice

    def engine_for(self, task_type: str, *, latency_budget_ms: int = 0) -> Any:
        choice = self.route(task_type, latency_budget_ms=latency_budget_ms)
        if choice == "remote":
            return self._remote
        if choice == "local":
            return self._local
        return None

    def stats(self) -> Dict[str, int]:
        return dict(self._hits)


# ── MCP-style tool registry ────────────────────────────────────────────────────

class MCPRegistry:
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, description: str, handler: Callable,
                 input_schema: Optional[Dict[str, Any]] = None,
                 *, source: str = "builtin") -> None:
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema or {"type": "object", "properties": {}},
            "source": source,
            "handler": handler,
        }

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {"name": t["name"], "description": t["description"], "inputSchema": t["inputSchema"], "source": t["source"]}
            for t in self._tools.values()
        ]

    async def call(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"unknown tool: {name}", "available": list(self._tools)}
        try:
            result = tool["handler"](arguments or {})
            if hasattr(result, "__await__"):
                result = await result
            return {"tool": name, "result": result}
        except Exception as e:
            return {"tool": name, "error": str(e)[:200]}

    def tool_names(self) -> List[str]:
        return sorted(self._tools)


# ── Default registry wiring the built-in capability set ────────────────────────

def build_default_registry() -> MCPRegistry:
    reg = MCPRegistry()

    def _governor_status(_: Dict[str, Any]) -> Dict[str, Any]:
        from server.safety.governor import get_safety_governor
        return get_safety_governor().status()

    def _user_summary(args: Dict[str, Any]) -> Dict[str, Any]:
        from server.systems.user_model import get_user_model
        return get_user_model(str(args.get("user_id", "default"))).summary()

    def _memory_maintenance(_: Dict[str, Any]) -> Dict[str, Any]:
        from server.systems.memory_hierarchy import get_memory_hierarchy
        return get_memory_hierarchy().run_maintenance()

    def _kernel_snapshot(_: Dict[str, Any]) -> Dict[str, Any]:
        from server.systems.cognition.cognitive_kernel import get_cognitive_kernel
        return get_cognitive_kernel().snapshot()

    async def _browser_navigate(args: Dict[str, Any]) -> Dict[str, Any]:
        from server.systems.browser.web_agent import navigate_async

        return await navigate_async(str(args.get("url") or ""))

    def _thoughts_open(args: Dict[str, Any]) -> Dict[str, Any]:
        from server.systems.cognition.thought_stream import get_thought_stream

        rows = get_thought_stream().open_thoughts(limit=int(args.get("limit", 20)))
        return {"open_thoughts": rows, "count": len(rows)}

    def _env_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
        from server.systems.cognition.environment_context import get_environment_context

        return get_environment_context().snapshot()

    def _perception_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
        from server.systems.vision.perception_fusion import get_perception_fusion

        return get_perception_fusion().fuse(
            include_screen=bool(args.get("include_screen", False)),
            include_gui_text=bool(args.get("include_gui_text", False)),
            user_id=str(args.get("user_id", "default")))

    def _knowledge_organize(args: Dict[str, Any]) -> Dict[str, Any]:
        from server.systems.memory.knowledge_organizer import get_knowledge_organizer

        return get_knowledge_organizer().organize(
            ingest=bool(args.get("ingest", False)),
            max_per_source=int(args.get("max_per_source", 200)))

    def _economy_decide(args: Dict[str, Any]) -> Dict[str, Any]:
        from server.systems.cognition.cognitive_economy import get_cognitive_economy

        d = get_cognitive_economy().decide(str(args.get("task_text") or ""),
                                           intent=args.get("intent"))
        return {"decision": {k: v for k, v in d.items() if k != "features"}}

    reg.register(
        "safety.governor.status", "Audit log + rollback status for filesystem operations.",
        _governor_status, {"type": "object", "properties": {}})
    reg.register(
        "user_model.summary", "Habits, rhythm, and anticipations for a user.",
        _user_summary, {"type": "object", "properties": {"user_id": {"type": "string"}}})
    reg.register(
        "memory.maintenance", "Run memory decay/consolidation/reinforcement pass.",
        _memory_maintenance, {"type": "object", "properties": {}})
    reg.register(
        "cognition.snapshot", "Current world model, focus, reflections, and goal trees.",
        _kernel_snapshot, {"type": "object", "properties": {}})
    reg.register(
        "browser.navigate", "Real page load via Playwright (§69); honest error when unavailable.",
        _browser_navigate, {"type": "object", "properties": {"url": {"type": "string"}}})
    reg.register(
        "cognition.thoughts", "Open internal thoughts (§52 persisted journal).",
        _thoughts_open, {"type": "object", "properties": {"limit": {"type": "integer"}}})
    reg.register(
        "environment.snapshot", "Unified machine/time/hardware/desktop context (§88).",
        _env_snapshot, {"type": "object", "properties": {}})
    reg.register(
        "perception.snapshot", "Fused multimodal perception stream pushed into the world model (§68).",
        _perception_snapshot, {"type": "object", "properties": {
            "include_screen": {"type": "boolean"},
            "include_gui_text": {"type": "boolean"},
            "user_id": {"type": "string"}}})
    reg.register(
        "knowledge.organize", "Cluster KG/memories/thoughts into emergent topics (§98); optional ingest (§79).",
        _knowledge_organize, {"type": "object", "properties": {
            "ingest": {"type": "boolean"}, "max_per_source": {"type": "integer"}}})
    reg.register(
        "cognition.economy", "Pick reasoning tier for a task from real cost signals (§78).",
        _economy_decide, {"type": "object", "properties": {
            "task_text": {"type": "string"}, "intent": {"type": "string"}}})
    return reg


_registry: Optional[MCPRegistry] = None


def get_mcp_registry() -> MCPRegistry:
    global _registry
    if _registry is None:
        _registry = build_default_registry()
    return _registry


# ── Live router over REAL engines (AccessFIles §48 / §78 cognitive economy) ───
#
# The remote engine is whatever the rest of the brain uses (env-configured).
# The local engine only exists when the operator actually runs one:
#   AARIYA_LOCAL_LLM_BASE_URL  e.g. http://127.0.0.1:11434/v1  (Ollama)
#   AARIYA_LOCAL_LLM_MODEL     e.g. mistral / llama3.2 / qwen2.5-coder
# Without those vars both slots point at the remote engine, so routing is a
# no-op rather than a fabricated "local" that isn't there.

_router_instance: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    global _router_instance
    if _router_instance is None:
        from server.systems.llm import LLMEngine

        remote = LLMEngine()
        local_base = os.getenv("AARIYA_LOCAL_LLM_BASE_URL", "").strip()
        if local_base:
            local = LLMEngine(
                base_url=local_base,
                api_key=os.getenv("AARIYA_LOCAL_LLM_KEY", "not-needed"),
                model=os.getenv("AARIYA_LOCAL_LLM_MODEL", "mistral"),
            )
        else:
            local = remote
        _router_instance = LLMRouter.from_engines(remote, local)
    return _router_instance


# ── Per-purpose model table (AccessFIles §48 — the doc's multi-model grid) ────
#
# The doc routes PURPOSES to dedicated models: vision / planning / coding /
# memory / fast conversation / heavy reasoning. Which models exist is an
# OPERATOR decision, so it is env-config driven — never hardcoded here and
# never fabricated when unset:
#
#   AARIYA_LLM_PURPOSSES-style JSON (exact var: AARIYA_LLM_PURPOSES):
#   {"vision":   {"base_url": "http://127.0.0.1:1234/v1", "model": "llava"},
#    "planning": {"base_url": "http://127.0.0.1:11434/v1", "model": "deepseek-r1"}}
#
# Unconfigured purposes return None so callers fall back to get_llm_router()'s
# remote/local split instead of pretending a specialist exists.

_PURPOSE_ENGINES: Dict[str, Any] = {}
_purpose_engines_lock = threading.Lock()


class PurposeRouter:
    """Purpose → engine table loaded from AARIYA_LLM_PURPOSES (JSON)."""

    def __init__(self):
        self._table: Dict[str, Dict[str, str]] = self._parse_env()

    @staticmethod
    def _parse_env() -> Dict[str, Dict[str, str]]:
        raw = os.getenv("AARIYA_LLM_PURPOSES", "").strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.warning("[llm_router] AARIYA_LLM_PURPOSES is not valid JSON (%s) "
                           "— no specialist models configured", exc)
            return {}
        if not isinstance(data, dict):
            logger.warning("[llm_router] AARIYA_LLM_PURPOSES must be an object")
            return {}
        table: Dict[str, Dict[str, str]] = {}
        for purpose, cfg in data.items():
            if isinstance(cfg, dict) and cfg.get("base_url"):
                table[str(purpose).strip().lower()] = {
                    "base_url": str(cfg["base_url"]),
                    "model": str(cfg.get("model") or "default"),
                    "api_key": str(cfg.get("api_key") or "not-needed"),
                }
        return table

    def purposes(self) -> List[str]:
        return sorted(self._table)

    def engine_for(self, purpose: str) -> Optional[Any]:
        """Dedicated engine for a configured purpose; None when unconfigured."""
        key = str(purpose or "").strip().lower()
        cfg = self._table.get(key)
        if not cfg:
            return None
        with _purpose_engines_lock:
            engine = _PURPOSE_ENGINES.get(key)
            if engine is None:
                from server.systems.llm import LLMEngine

                engine = LLMEngine(base_url=cfg["base_url"],
                                   api_key=cfg["api_key"],
                                   model=cfg["model"])
                _PURPOSE_ENGINES[key] = engine
            return engine

    def status(self) -> Dict[str, Any]:
        return {
            "configured_purposes": self.purposes(),
            "models": {p: self._table[p]["model"] for p in self.purposes()},
        }


_purpose_router: Optional[PurposeRouter] = None


def get_purpose_router(refresh: bool = False) -> PurposeRouter:
    """Singleton purpose router. refresh=True re-reads the env (tests/config reloads)."""
    global _purpose_router
    if _purpose_router is None or refresh:
        _purpose_router = PurposeRouter()
    return _purpose_router
