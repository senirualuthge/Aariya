# server/systems/planner.py
"""
Hierarchical Planning Engine — LLM-based goal decomposition.
──────────────────────────────────────────────────────────────
Converts a goal (string or dict) into a hierarchical execution tree:

    {"goal": str, "strategy": "llm" | "fallback", "steps": [...]}

Each step is:
    {"task": str, "parallel": bool, "subgoals": [{"task", "parallel"}, ...]}

Two-stage pipeline (mirrors server/autonomy/planner.py conventions):
    1. LLM decomposition — the model turns the goal into JSON steps with
       optional one-level subgoals and parallel-execution flags.
    2. Deterministic fallback — keyword-based goal templates, so planning
       never stalls when the LLM is unreachable or returns garbage.

All LLM output is validated structurally (JSON + field sanitization); it is
never executed directly — it only shapes the returned plan dict.
"""

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from server.systems.llm import LLMEngine

logger = logging.getLogger("aariya.planner")

_LLM_BASE = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
_LLM_KEY = os.getenv("LLM_API_KEY", "lm-studio")
_LLM_MODEL = os.getenv("LLM_MODEL", "llama3")

# Real bound on the LLM call — a hung model must not stall planning.
LLM_TIMEOUT_SECONDS = 25

# Structural limits — keep generated trees small and executable.
_MAX_STEPS = 8
_MAX_SUBGOALS = 4
_MAX_TASK_LEN = 160

# Lazy LLM singleton (same pattern as autonomy/planner.py + autonomy/loop.py)
_llm: Optional[LLMEngine] = None


def _get_llm() -> LLMEngine:
    global _llm
    if _llm is None:
        _llm = LLMEngine(base_url=_LLM_BASE, api_key=_LLM_KEY, model=_LLM_MODEL)
    return _llm


# ── Public API ────────────────────────────────────────────────────────────────

def plan(goal: str) -> Dict[str, Any]:
    """
    Convert a goal into a hierarchical execution tree.

    Args:
        goal: a goal string, or a dict (uses `description`/`task`/`goal`/`name`
              if present, else its string form).

    Returns:
        {"goal": str, "strategy": "llm"|"fallback", "steps": [{"task", "parallel", "subgoals"?}]}
    """
    goal_text = _goal_to_text(goal)

    llm_steps = _llm_decompose(goal_text)
    if llm_steps:
        return {"goal": goal_text, "strategy": "llm", "steps": llm_steps}

    return _fallback_plan(goal_text)


def score_plan(plan_dict: Dict[str, Any]) -> float:
    """
    Evaluate an execution tree for efficiency and structural risk.

    Deterministic: rewards short plans and parallel branches, penalizes long
    sequential chains. Returns a score in [0.0, 1.0].
    """
    steps = plan_dict.get("steps") or []
    if not isinstance(steps, list) or not steps:
        return 0.0

    steps_count = len(steps)
    # Short chains are more efficient; parallel branches compress wall-time.
    efficiency = 1.0 / steps_count
    parallel_bonus = sum(1 for s in steps if isinstance(s, dict) and s.get("parallel")) * 0.05
    # Structural risk grows with chain length (deterministic — no RNG).
    risk = min(0.3, (steps_count - 1) * 0.05)

    score = efficiency + parallel_bonus - risk
    return max(0.0, min(1.0, round(score, 3)))


# ── LLM decomposition ─────────────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = (
    "You are Aariya's hierarchical planning layer. You decompose ONE goal into "
    "a short executable plan. Return ONLY JSON — no markdown, no explanation."
)

def _llm_decompose(goal_text: str) -> Optional[List[Dict[str, Any]]]:
    """Ask the LLM for a hierarchical step tree. Returns sanitized steps or None."""
    prompt = f"""
Decompose this goal into a hierarchical execution tree:

Goal: {goal_text[:500]}

Return JSON matching exactly this schema (max {_MAX_STEPS} steps):
{{
  "steps": [
    {{
      "task": "short actionable task",
      "parallel": false,
      "subgoals": [
        {{"task": "subtask", "parallel": true}}
      ]
    }}
  ]
}}

Rules:
- 2–{_MAX_STEPS} top-level steps; each step has at most {_MAX_SUBGOALS} subgoals.
- "parallel": true means the task (or subgoal) can run concurrently with its siblings.
- Tasks must be short, concrete, and directly executable.
- Only include "subgoals" when a step genuinely decomposes into subtasks.
"""
    try:
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(
                _get_llm().chat_completion,
                [
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                0.3,
                500,
            )
            raw = future.result(timeout=LLM_TIMEOUT_SECONDS)
        finally:
            # wait=False: a hung model must not block past the timeout above.
            pool.shutdown(wait=False, cancel_futures=True)
    except Exception as exc:
        logger.debug("[Planner] LLM decomposition failed: %s", exc)
        return None

    if not raw:
        return None

    data = _safe_parse_json(raw)
    if not isinstance(data, dict):
        return None
    steps = _sanitize_steps(data.get("steps"))
    return steps or None


def _safe_parse_json(text: str) -> Optional[dict]:
    """Robust JSON extraction from LLM output (strips fences / prose)."""
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
        return None


def _sanitize_steps(raw_steps: Any) -> List[Dict[str, Any]]:
    """Validate/normalize LLM steps; drop anything malformed."""
    if not isinstance(raw_steps, list):
        return []
    clean: List[Dict[str, Any]] = []
    for s in raw_steps[:_MAX_STEPS]:
        if not isinstance(s, dict):
            continue
        task = str(s.get("task") or "").strip()
        if not task or len(task) > _MAX_TASK_LEN:
            continue
        step: Dict[str, Any] = {
            "task": task,
            "parallel": bool(s.get("parallel", False)),
        }
        subgoals = _sanitize_subgoals(s.get("subgoals"))
        if subgoals:
            step["subgoals"] = subgoals
        clean.append(step)
    return clean


def _sanitize_subgoals(raw_subgoals: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw_subgoals, list):
        return []
    clean: List[Dict[str, Any]] = []
    for g in raw_subgoals[:_MAX_SUBGOALS]:
        if not isinstance(g, dict):
            continue
        task = str(g.get("task") or "").strip()
        if not task or len(task) > _MAX_TASK_LEN:
            continue
        clean.append({"task": task, "parallel": bool(g.get("parallel", False))})
    return clean


# ── Deterministic fallback (LLM unavailable / invalid output) ─────────────────

def _fallback_plan(goal_text: str) -> Dict[str, Any]:
    """Keyword-based goal templates — real hierarchical steps, no RNG."""
    g = goal_text.lower()

    if any(k in g for k in ("research", "learn", "investigate", "study", "understand")):
        steps = [
            {"task": "define_research_question", "parallel": False},
            {
                "task": "gather_sources",
                "parallel": True,
                "subgoals": [
                    {"task": "web_search", "parallel": True},
                    {"task": "vault_review", "parallel": True},
                ],
            },
            {"task": "synthesize_findings", "parallel": False},
        ]
    elif any(k in g for k in ("build", "create", "implement", "develop", "write")):
        steps = [
            {"task": "analyze_requirements", "parallel": False},
            {"task": "design_architecture", "parallel": False},
            {
                "task": "implement_components",
                "parallel": True,
                "subgoals": [
                    {"task": "core_implementation", "parallel": True},
                    {"task": "write_tests", "parallel": True},
                ],
            },
            {"task": "verify_and_review", "parallel": False},
        ]
    elif any(k in g for k in ("optimize", "improve", "scale", "fix", "debug", "speed")):
        steps = [
            {"task": "analyze_current_state", "parallel": False},
            {"task": "identify_bottlenecks", "parallel": True},
            {"task": "apply_changes", "parallel": True},
            {"task": "validate_impact", "parallel": False},
        ]
    else:
        # Generic tree — preserves the original stub's shape as a last resort.
        steps = [
            {"task": "analyze_state", "parallel": False},
            {"task": "select_agents", "parallel": False},
            {"task": "simulate_paths", "parallel": True},
            {"task": "execute_best_plan", "parallel": False},
        ]

    return {"goal": goal_text, "strategy": "fallback", "steps": steps}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _goal_to_text(goal: Any) -> str:
    """Normalize a string or dict goal into a single text form."""
    if isinstance(goal, dict):
        for key in ("description", "task", "goal", "name"):
            value = goal.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return str(goal)
    text = str(goal or "").strip()
    return text or "general goal"
