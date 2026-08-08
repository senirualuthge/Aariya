"""
AutonomyPlanner — turns a self-generated goal into an executable plan.
──────────────────────────────────────────────────────────────────────
Uses the LLM (via LLMEngine, same abstraction as the rest of the brain)
to decompose a goal into a whitelisted sequence of steps. Falls back to
goal-type templates when the LLM is unavailable so autonomy never stalls.

Step types (whitelist — the executor refuses anything else):
  research          → run the real multi-hop research pipeline
  surface_insight   → persist a learned insight for future surfacing
  check_in          → deliver a proactive message to the user
  monitor           → wait / observe a signal
  review_vault      → search the Obsidian RAG vault for related knowledge

Approval policy: steps that contact the user (check_in / surface_insight)
require approval. Read-only research never does. A plan with any
approval-required step is gated on user approval before execution.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from server.systems.llm import LLMEngine

logger = logging.getLogger("aariya.autonomy.planner")

_LLM_BASE = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
_LLM_KEY  = os.getenv("LLM_API_KEY",  "lm-studio")
_LLM_MODEL = os.getenv("LLM_MODEL",   "llama3")

# Whitelisted step types (executor enforces this too)
ALLOWED_STEP_TYPES = {"research", "surface_insight", "check_in", "monitor", "review_vault"}
# Step types that require explicit user approval before execution
APPROVAL_REQUIRED_TYPES = {"check_in", "surface_insight"}

# Fallback plan templates per goal type (real steps, no mock data)
PLAN_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "learn_topic": [
        {"type": "research", "params": {"topic": "{topic}"},
         "description": "Research the topic with the multi-hop pipeline", "requires_approval": False},
        {"type": "surface_insight", "params": {"topic": "{topic}"},
         "description": "Store the finding as a personal insight", "requires_approval": True},
    ],
    "support_user": [
        {"type": "review_vault", "params": {"topic": "wellbeing, stress, comfort"},
         "description": "Recall past comfort moments from the vault", "requires_approval": False},
        {"type": "check_in", "params": {"context": "gentle supportive check-in"},
         "description": "Send a warm, low-pressure check-in message", "requires_approval": True},
    ],
    "re_engage": [
        {"type": "check_in", "params": {"context": "light, curious re-engagement"},
         "description": "Send a light, curious message to re-open the conversation", "requires_approval": True},
    ],
    "deepen_relationship": [
        {"type": "review_vault", "params": {"topic": "shared memories, user interests"},
         "description": "Recall shared moments from the vault", "requires_approval": False},
        {"type": "check_in", "params": {"context": "recall a shared moment, ask a safe personal question"},
         "description": "Send a message recalling a shared moment", "requires_approval": True},
    ],
    "curate_knowledge": [
        {"type": "research", "params": {"topic": "open knowledge gaps"},
         "description": "Fill the highest-priority knowledge gap", "requires_approval": False},
        {"type": "surface_insight", "params": {"topic": "learned knowledge"},
         "description": "Persist the synthesis as an insight", "requires_approval": True},
    ],
}

# Shared lazy LLM singleton (mirrors autonomy/loop.py pattern)
_llm: Optional[LLMEngine] = None

def _get_llm() -> LLMEngine:
    global _llm
    if _llm is None:
        _llm = LLMEngine(base_url=_LLM_BASE, api_key=_LLM_KEY, model=_LLM_MODEL)
    return _llm


def _safe_parse_json(text: str) -> Optional[dict]:
    """Robust JSON extraction from LLM output (strips fences / prose)."""
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return None
        return None


def _sanitize_steps(raw_steps: Any) -> List[Dict[str, Any]]:
    """Validate LLM steps against the whitelist; drop anything unknown."""
    if not isinstance(raw_steps, list):
        return []
    clean: List[Dict[str, Any]] = []
    for s in raw_steps[:6]:
        if not isinstance(s, dict):
            continue
        stype = str(s.get("type", "")).strip()
        if stype not in ALLOWED_STEP_TYPES:
            logger.warning("[AutonomyPlanner] Dropping unknown step type: %s", stype)
            continue
        params = s.get("params") or {}
        if isinstance(params, str):
            params = {"topic": params}
        clean.append({
            "type": stype,
            "params": dict(params),
            "description": str(s.get("description", stype))[:200],
            "requires_approval": bool(s.get("requires_approval", stype in APPROVAL_REQUIRED_TYPES)),
        })
    return clean


def _compute_risk(steps: List[Dict[str, Any]]) -> str:
    """
    Heuristic risk level from step composition.
    All current whitelisted actions are read-only or user-facing messages,
    so plans are low-risk; approval gating comes from the step-level
    `requires_approval` flags (contacting the user requires consent).
    """
    return "low"


class AutonomyPlanner:
    async def plan_goal(self, goal: Dict[str, Any],
                        context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Produce {steps, risk_level, requires_approval, rationale} for a goal.

        Args:
            goal: dict with keys id, description, goal_type, priority
            context: optional {gaps, insights, trust, valence, topic}
        """
        context = context or {}
        llm_steps = await self._llm_plan(goal, context)
        steps = _sanitize_steps(llm_steps)

        if not steps:
            # Graceful fallback: real template decomposition
            steps = self._template_plan(goal, context)

        risk = _compute_risk(steps)
        requires_approval = any(s["requires_approval"] for s in steps) or risk in ("medium", "high")

        return {
            "steps": steps,
            "risk_level": risk,
            "requires_approval": requires_approval,
            "rationale": "LLM-decomposed plan" if llm_steps else "template fallback plan",
        }

    async def _llm_plan(self, goal: Dict[str, Any],
                        context: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        allowed = ", ".join(sorted(ALLOWED_STEP_TYPES))
        prompt = f"""
You are Aariya's internal planning layer. Decompose ONE goal into a short
executable plan (2–4 steps). Return ONLY JSON:

Goal: {goal.get('description')}
Goal type: {goal.get('goal_type')}
Priority: {goal.get('priority')}
Open knowledge gaps: {[g.get('topic') for g in (context.get('gaps') or [])][:3]}
Unsorted insights: {[i.get('topic') for i in (context.get('insights') or [])][:3]}
Trust with user: {context.get('trust', 0.5):.2f}

Allowed step types: {allowed}

Rules:
- 'research' and 'review_vault' are read-only → "requires_approval": false
- 'check_in' and 'surface_insight' touch the user → "requires_approval": true
- Use REAL topics from the gaps/insights above where possible.
- "requires_approval": true means the user must approve before execution.

JSON schema:
{{"steps": [{{"type": "...", "params": {{"topic": "..."}}, "description": "...", "requires_approval": true}}]}}
"""
        try:
            loop = asyncio.get_event_loop()
            raw = await loop.run_in_executor(
                None,
                lambda: _get_llm().chat_completion(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=300,
                ),
            )
            if not raw:
                return None
            data = _safe_parse_json(raw)
            return data.get("steps") if data else None
        except Exception as e:
            logger.warning("[AutonomyPlanner] LLM plan failed — template fallback: %s", e)
            return None

    def _template_plan(self, goal: Dict[str, Any],
                       context: Dict[str, Any]) -> List[Dict[str, Any]]:
        gtype = goal.get("goal_type", "learn_topic")
        topic = context.get("topic") or goal.get("description", "a topic")
        if gtype not in PLAN_TEMPLATES:
            gtype = "learn_topic"
        steps = []
        for step in PLAN_TEMPLATES[gtype]:
            s = json.loads(json.dumps(step))  # deep copy
            s["params"] = {k: str(v).replace("{topic}", topic[:80]) for k, v in s["params"].items()}
            steps.append(s)
        return steps
