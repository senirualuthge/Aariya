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


# ── TaskPlanner (AccessFIles §21 — "TASK PLANNER (MOST IMPORTANT)") ───────────

class TaskPlanner:
    """Goal → concrete-action-plan translator (AccessFIles §21).

    Given a goal string, returns an ordered list of whitelisted action dicts
    the ActionExecutor can dispatch (launch_app, navigate, wait, type,
    create_document, observe, research, check_in). Unknown goals degrade to an
    empty plan rather than inventing side effects.
    """

    RECIPES: Dict[str, List[Dict[str, Any]]] = {
        "open chrome": [{"action": "launch_app", "app": "chrome"}],
        "open browser": [{"action": "launch_app", "app": "chrome"}],
        "search youtube": [
            {"action": "launch_app", "app": "chrome"},
            {"action": "navigate", "url": "https://youtube.com"},
        ],
        "create document": [
            {"action": "launch_app", "app": "word"},
            {"action": "wait", "seconds": 2},
            {"action": "type", "text": "New document"},
        ],
        "check email": [
            {"action": "launch_app", "app": "mail"},
            {"action": "observe", "what": "email inbox"},
        ],
        "write notes": [
            {"action": "create_document", "title": "notes"},
            {"action": "type", "text": "Capturing a thought..."},
        ],
        "do research": [{"action": "research", "topic": "current events"}],
        "check in": [{"action": "check_in", "context": "warm, natural check-in"}],
    }

    # Cognitive goal-type recipes (GoalSystem + HierarchicalGoalSystem types).
    # These map internal state goals — which the brain feeds in every turn — onto
    # concrete whitelisted ActionExecutor steps, so the planner→executor chain
    # actually fires instead of degrading to an empty plan (AccessFIles §21-22).
    GOAL_TYPE_RECIPES: Dict[str, List[Dict[str, Any]]] = {
        "stabilize": [
            {"action": "observe", "what": "current cognitive state"},
            {"action": "wait", "seconds": 2},
            {"action": "check_in", "context": "calm, grounded check-in"},
        ],
        "maintain stability": [
            {"action": "observe", "what": "current cognitive state"},
            {"action": "wait", "seconds": 2},
            {"action": "check_in", "context": "calm, grounded check-in"},
        ],
        "build trust": [
            {"action": "observe", "what": "user context"},
            {"action": "check_in", "context": "warm, attentive check-in"},
        ],
        "build relationship": [
            {"action": "observe", "what": "user context"},
            {"action": "check_in", "context": "warm, attentive check-in"},
        ],
        "increase curiosity": [
            {"action": "research", "topic": "an interesting current topic"},
            {"action": "create_document", "title": "curiosity notes"},
        ],
        "expand knowledge": [
            {"action": "research", "topic": "an interesting current topic"},
            {"action": "create_document", "title": "knowledge notes"},
        ],
        "reduce risk": [
            {"action": "observe", "what": "current state"},
            {"action": "wait", "seconds": 1},
            {"action": "check_in", "context": "gentle safety check-in"},
        ],
    }

    def generate_plan(self, goal: str) -> List[Dict[str, Any]]:
        """Translate a goal string into an ordered action plan."""
        if not goal:
            return []
        key = goal.strip().lower()
        if key in self.RECIPES:
            return [dict(step) for step in self.RECIPES[key]]

        # Normalized goal-type lookup — strips punctuation/underscores so both
        # "build_trust" and "build trust" resolve to the same recipe.
        norm = key.replace("_", " ").strip()
        if norm in self.GOAL_TYPE_RECIPES:
            return [dict(step) for step in self.GOAL_TYPE_RECIPES[norm]]

        lowered = key
        if "research" in lowered or "learn about" in lowered:
            topic = lowered.replace("research", "").replace("learn about", "").strip(" :")
            return [{"action": "research", "topic": topic or "current events"}]
        if "search" in lowered:
            query = lowered.replace("search", "").replace("search for", "").strip(" :")
            return [
                {"action": "launch_app", "app": "chrome"},
                {"action": "navigate", "url": f"https://www.google.com/search?q={query.replace(' ', '+')}"},
            ]
        logger.debug("[TaskPlanner] no recipe for goal '%s' → empty plan", goal)
        return []

    def plan_goal(self, goal: str) -> Dict[str, Any]:
        """Return a full plan object (steps + metadata) for downstream use."""
        steps = self.generate_plan(goal)
        return {
            "goal": goal,
            "steps": steps,
            "step_count": len(steps),
            "first_action": steps[0]["action"] if steps else None,
        }


class Replanner:
    """Replanning (NEWPredictionPRT2 §8): when something fails, produce an
    alternative strategy instead of dropping the plan.

        Weather API offline → use backup provider → continue plan

    `replan(failed_task)` returns a list of alternative-strategy descriptors.
    Each carries a human-readable strategy, the concrete whitelisted fallback
    steps (reusable by the ActionExecutor), and the reason it was chosen.
    """

    # Action-specific fallback strategies. Each fallback maps the FAILED action
    # to a replacement plan (steps the ActionExecutor can dispatch) plus a
    # short description of the alternative approach.
    ACTION_FALLBACKS: Dict[str, Dict[str, Any]] = {
        "launch_app": {
            "strategy": "Use browser fallback instead of the desktop app",
            "steps": [
                {"action": "navigate", "url": "https://www.google.com"},
                {"action": "observe", "what": "landing page"},
            ],
        },
        "navigate": {
            "strategy": "Retry via search engine instead of the direct URL",
            "steps": [
                {"action": "navigate", "url": "https://www.google.com"},
                {"action": "type", "text": "topic"},
                {"action": "observe", "what": "search results"},
            ],
        },
        "type": {
            "strategy": "Create a document instead of typing in the live app",
            "steps": [
                {"action": "create_document", "title": "captured note"},
                {"action": "type", "text": "Saved offline after typing failure"},
            ],
        },
        "research": {
            "strategy": "Use a backup information provider",
            "steps": [
                {"action": "navigate", "url": "https://www.google.com/search?q=fallback"},
                {"action": "observe", "what": "backup search results"},
            ],
        },
        "run_code": {
            "strategy": "Analyze offline instead of executing code",
            "steps": [
                {"action": "create_document", "title": "analysis note"},
                {"action": "type", "text": "Code execution unavailable; recorded for offline analysis."},
            ],
        },
        "check_in": {
            "strategy": "Continue the plan and check in later",
            "steps": [
                {"action": "wait", "seconds": 3},
                {"action": "observe", "what": "current state"},
            ],
        },
    }

    def replan(self, failed_task: Any) -> List[Dict[str, Any]]:
        """Given a failed task/step, return alternative strategies."""
        if isinstance(failed_task, str):
            failed = {"action": failed_task}
        elif isinstance(failed_task, dict):
            failed = failed_task
        else:
            return []

        action = str(failed.get("action", "")).lower().strip()
        goal = str(failed.get("goal", "") or failed.get("reason", "")).strip()
        alternatives: List[Dict[str, Any]] = []

        fallback = self.ACTION_FALLBACKS.get(action)
        if fallback:
            alternatives.append({
                "failed_action": action,
                "strategy": fallback["strategy"],
                "steps": [dict(step) for step in fallback["steps"]],
                "reason": f"fallback for '{action}'",
            })

        # Goal-level replan: ask the TaskPlanner for a fresh plan, which may
        # sidestep the failed action entirely ("Continue plan").
        if goal:
            replanned = TaskPlanner().generate_plan(goal)
            if replanned:
                alternatives.append({
                    "failed_action": action,
                    "strategy": f"Replan goal '{goal}' with a fresh action sequence",
                    "steps": [dict(step) for step in replanned],
                    "reason": "goal-level replan",
                })

        # Generic last-resort strategy so the plan never dies silently.
        alternatives.append({
            "failed_action": action,
            "strategy": "Fall back to observation and re-check the current state",
            "steps": [
                {"action": "observe", "what": "current state"},
                {"action": "check_in", "context": "gentle status check"},
            ],
            "reason": "last-resort replan",
        })
        return alternatives

    def continue_plan(self, failed_task: Any) -> Dict[str, Any]:
        """Replan() then report whether the plan can continue (the doc's
        'Use backup provider → Continue plan' shape)."""
        alternatives = self.replan(failed_task)
        action = failed_task.get("action") if isinstance(failed_task, dict) else str(failed_task)
        return {
            "failed_action": action,
            "can_continue": bool(alternatives),
            "alternative_count": len(alternatives),
            "alternatives": alternatives,
        }

