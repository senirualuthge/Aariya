"""
gap_detector.py
───────────────
Detects missing critical swarm capabilities and spawns new agents to fill them.

- scan_for_gaps(active_agents)  — name-based capability audit of the registry.
- trigger_spawner(missing_cap)  — generates a real agent module for the gap:
    1. Tries the LLM "auto-coder" (writes a bespoke Agent subclass).
    2. Falls back to a built-in per-capability template.
    3. Writes the module into server/systems/swarm/agents/generated/ with an
       atomic write, where the AgentScanner auto-discovers it (folder +
       inheritance strategies) so it shows up in the Neural Swarm UI.

Generated files are validated with AST before being written and are never
imported/executed in this process — only parsed statically by the scanner.
"""

import ast
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("aariya.gap_detector")

REQUIRED_CAPABILITIES = {
    "dialogue",
    "emotion_engine",
    "memory_retrieval",
    "visual_tracking"
}

# ── Spawner configuration ────────────────────────────────────────────────────
# Written inside an `agents/` folder so the AgentScanner's folder strategy
# picks new files up without any manual registration.
GENERATED_AGENTS_DIR = Path(
    os.getenv(
        "AARIYA_GENERATED_AGENTS_DIR",
        str(Path(__file__).resolve().parents[2]
            / "server" / "systems" / "swarm" / "agents" / "generated"),
    )
)
# Cooldown before re-attempting a spawn that produced no file (e.g. a failed
# write), so the 60s evolution tick can't hammer the LLM or the filesystem.
SPAWN_COOLDOWN_SECONDS = float(os.getenv("AARIYA_SPAWN_COOLDOWN_SECONDS", "600"))
LLM_TIMEOUT_SECONDS = 25
MAX_LLM_TOKENS = 800

# LLM env config (mirrors server/autonomy/loop.py — local Ollama/LM Studio by default).
_LLM_BASE = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
_LLM_KEY = os.getenv("LLM_API_KEY", "lm-studio")
_LLM_MODEL = os.getenv("LLM_MODEL", "llama3")

_llm_engine = None


def _get_llm():
    """Lazy LLMEngine singleton — kept as a function so tests can monkeypatch it."""
    global _llm_engine
    if _llm_engine is None:
        from server.systems.llm import LLMEngine
        _llm_engine = LLMEngine(base_url=_LLM_BASE, api_key=_LLM_KEY, model=_LLM_MODEL)
    return _llm_engine


# Tracks when we last attempted a spawn per target file (for the cooldown).
# Guarded by _spawn_lock — trigger_spawner may run on executor threads.
_spawned_at: Dict[str, float] = {}
_spawn_lock = threading.Lock()


def scan_for_gaps(active_agents: list) -> list:
    """
    Checks if the swarm is missing critical components.
    Agents are expected to self-report capabilities, but we can fall back to name matching.
    """
    current_caps = set()
    for agent in active_agents:
        # Simple name-based capability mapping for now
        name = agent.get('name', '').lower()
        if 'dialogue' in name or 'chat' in name:
            current_caps.add('dialogue')
        if 'emotion' in name or 'sentiment' in name:
            current_caps.add('emotion_engine')
        if 'memory' in name or 'rag' in name:
            current_caps.add('memory_retrieval')
        if 'vision' in name or 'visual' in name or 'tracker' in name:
            current_caps.add('visual_tracking')

    missing = REQUIRED_CAPABILITIES - current_caps
    if missing:
        logger.warning(f"[GapDetector] Missing critical swarm capabilities: {missing}")
    return list(missing)


def trigger_spawner(missing_cap: str) -> dict:
    """
    Generate a new agent module that fills the given swarm capability gap.

    Returns a dict describing what happened, e.g.:
        {"ok": True, "capability": "memory_retrieval", "method": "llm"|"template",
         "agent_name": "MemoryRetrievalAgent", "file": "...", "source": "..."}
        {"ok": True, "skipped": True, ...}   # agent already on disk
        {"ok": False, "error": "...", ...}   # cooldown / write failure
    """
    cap = _slug(missing_cap)
    if not cap:
        logger.warning("[GapDetector] Ignoring spawn for invalid capability %r", missing_cap)
        return {"ok": False, "error": f"invalid capability: {missing_cap!r}"}

    out_dir = Path(GENERATED_AGENTS_DIR).resolve()
    file_path = out_dir / f"{cap}_agent.py"

    # Serialize the check-then-act window (exists / cooldown / write) so two
    # executor threads can't spawn the same agent twice.
    with _spawn_lock:
        # Already on disk (from a previous spawn or hand-written) — evolution ticks
        # every 60s, so this guard prevents re-generating on every single tick.
        if file_path.exists():
            logger.debug("[GapDetector] %s already exists — skipping.", file_path.name)
            return {"ok": True, "skipped": True, "capability": cap, "file": str(file_path)}

        # Cooldown: give the watcher/scanner time to discover a recent spawn before
        # attempting another (only reached when the file write failed or was removed).
        now = time.time()
        if now - _spawned_at.get(str(file_path), 0.0) < SPAWN_COOLDOWN_SECONDS:
            return {"ok": False, "error": "cooldown", "capability": cap}

        class_name, source, method = _generate_agent(cap)

        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = out_dir / f".{cap}_agent.py.tmp"
            tmp_path.write_text(source, encoding="utf-8")
            tmp_path.replace(file_path)  # atomic — the watcher never sees a half-written file
        except OSError as exc:
            logger.error("[GapDetector] Failed to write %s: %s", file_path, exc)
            return {"ok": False, "error": str(exc), "capability": cap}

        _spawned_at[str(file_path)] = now
    logger.info("[GapDetector] Spawned %s (%s) -> %s", class_name, method, file_path)
    return {
        "ok": True,
        "capability": cap,
        "method": method,
        "agent_name": class_name,
        "file": str(file_path),
        "source": source,
    }


# ── Generation ────────────────────────────────────────────────────────────────

def _generate_agent(cap: str) -> Tuple[str, str, str]:
    """Return (class_name, source, method). LLM auto-coder first, template fallback."""
    llm_class, llm_code = _generate_via_llm(cap)
    if llm_class:
        return llm_class, llm_code, "llm"
    class_name, source = _generate_template(cap)
    return class_name, source, "template"


_LLM_SYSTEM_PROMPT = (
    "You are AgentForge, the auto-coder inside Aariya's neural swarm. "
    "You write ONE Python swarm agent class that fills a missing capability.\n"
    "Rules:\n"
    "1. The file lives in server/systems/swarm/agents/, so the base import MUST be: `from .base import Agent`\n"
    "2. Define exactly ONE class that subclasses Agent.\n"
    "3. Implement `async def act(self, state) -> dict` returning a dict that includes an \"agent\" key set to the capability name.\n"
    "4. Keep it under 80 lines. Return ONLY the Python code — no markdown fences, no explanations."
)


def _generate_via_llm(cap: str) -> Tuple[Optional[str], Optional[str]]:
    """Ask the LLM auto-coder to write a bespoke agent. Returns (class_name, code) or (None, None)."""
    try:
        llm = _get_llm()
        prompt = (
            f"Swarm capability to fill: {cap}\n\n"
            "Write a single Python class implementing this capability as a swarm agent. "
            "The class MUST subclass Agent (from .base) and implement "
            "`async def act(self, state) -> dict`, returning a dict that includes "
            "an \"agent\" key set to the capability name."
        )
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(
                llm.chat_completion,
                [
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                0.3,
                MAX_LLM_TOKENS,
            )
            raw = future.result(timeout=LLM_TIMEOUT_SECONDS)
        finally:
            # wait=False: don't block on a hung LLM call — the timeout above is
            # the real bound. (A `with` block would shutdown(wait=True) and wait
            # for the timed-out task to finish, defeating the timeout.)
            pool.shutdown(wait=False, cancel_futures=True)
    except Exception as exc:
        logger.debug("[GapDetector] LLM spawn failed: %s", exc)
        return None, None

    code = _extract_code(raw or "")
    class_name = _validate_generated(code)
    if class_name is None:
        logger.warning("[GapDetector] LLM output rejected — falling back to template.")
        return None, None
    return class_name, code


def _extract_code(text: str) -> str:
    """Pull the Python code out of an LLM reply (fenced block or trailing code)."""
    text = (text or "").strip()
    fence = re.search(r"```(?:python)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    # No fence: drop any prose prefix, keep from the first code-looking line.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(("from ", "import ", "class ", "@")):
            return "\n".join(lines[i:]).strip()
    return text


def _validate_generated(code: str) -> Optional[str]:
    """
    Statically validate LLM-generated agent code.

    Returns the class name if the module is safe/usable, else None.
    Only checks structure — the module is NEVER imported or executed here.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if len(classes) != 1:
        return None
    cls = classes[0]

    # Must subclass Agent (bare `class X(Agent)`).
    if not any(isinstance(b, ast.Name) and b.id == "Agent" for b in cls.bases):
        return None

    # Must define `async def act(self, state)` — the base contract used with
    # asyncio.gather (a plain sync `act` would break the orchestrator).
    has_act = any(
        isinstance(n, ast.AsyncFunctionDef) and n.name == "act" for n in cls.body
    )
    if not has_act:
        return None

    return cls.name


# ── Templates (deterministic fallback when no LLM is reachable) ───────────────

_TEMPLATES: Dict[str, str] = {
    "dialogue": '''"""DialogueAgent — auto-generated by Aariya's gap-spawner.

Fills the "dialogue" swarm capability gap.
"""

from typing import Any, Dict

from .base import Agent


class DialogueAgent(Agent):
    """Shapes a conversational response hint from the incoming state."""

    def __init__(self):
        super().__init__("dialogue")

    async def act(self, state: Dict[str, Any]) -> dict:
        text = str(state.get("text") or "")
        return {
            "agent": "dialogue",
            "context": f"[DIALOGUE] Reply intent from: {text[:200] or '(empty input)'}",
            "confidence": 0.5,
        }
''',
    "emotion_engine": '''"""EmotionEngineAgent — auto-generated by Aariya's gap-spawner.

Fills the "emotion_engine" swarm capability gap.
"""

from typing import Any, Dict

from .base import Agent


class EmotionEngineAgent(Agent):
    """Infers user affect from the incoming state."""

    def __init__(self):
        super().__init__("emotion_engine")

    async def act(self, state: Dict[str, Any]) -> dict:
        emotion = state.get("emotion") or state.get("user_emotion") or "neutral"
        return {
            "agent": "emotion_engine",
            "emotion": emotion,
            "context": f"[EMOTION] user appears {emotion}",
            "confidence": 0.6,
        }
''',
    "memory_retrieval": '''"""MemoryRetrievalAgent — auto-generated by Aariya's gap-spawner.

Fills the "memory_retrieval" swarm capability gap.
"""

from typing import Any, Dict

from .base import Agent


class MemoryRetrievalAgent(Agent):
    """Surfaces relevant memory context from the incoming state."""

    def __init__(self):
        super().__init__("memory_retrieval")

    async def act(self, state: Dict[str, Any]) -> dict:
        memories = state.get("memories") or state.get("memory_context") or []
        count = len(memories) if isinstance(memories, list) else 0
        return {
            "agent": "memory_retrieval",
            "memories": memories,
            "context": f"[MEMORY] {count} memory item(s) surfaced",
            "confidence": 0.6,
        }
''',
    "visual_tracking": '''"""VisualTrackerAgent — auto-generated by Aariya's gap-spawner.

Fills the "visual_tracking" swarm capability gap.
"""

from typing import Any, Dict

from .base import Agent


class VisualTrackerAgent(Agent):
    """Tracks face/visual state from the incoming vision payload."""

    def __init__(self):
        super().__init__("visual_tracking")

    async def act(self, state: Dict[str, Any]) -> dict:
        vision = state.get("vision_data") or {}
        face_detected = bool(vision.get("face_detected", False))
        return {
            "agent": "visual_tracking",
            "face_detected": face_detected,
            "context": "[VISUAL] face detected" if face_detected else "[VISUAL] no face",
            "confidence": float(vision.get("face_confidence", 0.0)),
        }
''',
}

_GENERIC_TEMPLATE = '''"""__CLASS_NAME__ — auto-generated by Aariya's gap-spawner.

Fills the "__CAPABILITY__" swarm capability gap.
"""

from typing import Any, Dict

from .base import Agent


class __CLASS_NAME__(Agent):
    """Generic capability agent: observes state and reports findings."""

    def __init__(self):
        super().__init__("__CAPABILITY__")

    async def act(self, state: Dict[str, Any]) -> dict:
        text_len = len(str(state.get("text") or ""))
        return {
            "agent": "__CAPABILITY__",
            "context": f"[__TAG__] observed input of {text_len} chars",
            "confidence": 0.4,
        }
'''


def _generate_template(cap: str) -> Tuple[str, str]:
    """Return (class_name, source) for a built-in or generic template agent."""
    class_name = _pascal(cap) + "Agent"
    if cap in _TEMPLATES:
        return class_name, _TEMPLATES[cap]
    source = (
        _GENERIC_TEMPLATE
        .replace("__CLASS_NAME__", class_name)
        .replace("__CAPABILITY__", cap)
        .replace("__TAG__", cap.upper())
    )
    return class_name, source


# ── Naming helpers ────────────────────────────────────────────────────────────

def _slug(raw: str) -> str:
    """'Memory Retrieval!' -> 'memory_retrieval' (safe file/module identifier)."""
    return re.sub(r"[^a-zA-Z0-9_]+", "_", (raw or "").strip()).lower().strip("_")


def _pascal(slug: str) -> str:
    """'visual_tracking' -> 'VisualTracking'."""
    return "".join(part.capitalize() for part in slug.split("_"))
