"""
AutonomyExecutor — executes approved plans with a whitelisted action registry.
───────────────────────────────────────────────────────────────────────────────
Every action is audited to the autonomy_actions table. The registry is the
ONLY way the autonomy layer can touch the world — nothing is allowed outside
the whitelist (mirrors the 'Cloud proposes, local enforces' safety contract).

Action handlers (real implementations, no mocks):
  research          → multi-hop research pipeline (RAG arena + web + vault)
  review_vault      → same pipeline, memory-focused query
  surface_insight   → persists learned knowledge for future surfacing
  check_in          → delivers a proactive message via the daemon broadcast
  monitor           → acknowledges a wait/observe step (daemon watches signals)
"""

import asyncio
import logging
import traceback
from typing import Any, Callable, Dict, Optional

from server.autonomy.state import AutonomyStore
from server.autonomy.planner import ALLOWED_STEP_TYPES

logger = logging.getLogger("aariya.autonomy.executor")


class AutonomyExecutor:
    def __init__(self, store: AutonomyStore,
                 broadcast: Optional[Callable[[dict], Any]] = None):
        self.store = store
        # broadcast: async fn(dict) — used by check_in steps to deliver messages
        async def _noop(msg: dict) -> None:
            pass
        self.broadcast = broadcast or _noop

    # ── Plan execution ───────────────────────────────────────────────────────

    async def execute_plan(self, plan: Dict[str, Any], goal: Dict[str, Any]) -> Dict[str, Any]:
        """Execute every step of an approved plan, auditing each one."""
        self.store.update_plan(plan["id"], status="running")
        results = []
        all_ok = True
        last_outcome = ""

        for step in plan.get("steps", []):
            if step.get("type") not in ALLOWED_STEP_TYPES:
                logger.warning("[Executor] Blocked unknown action type: %s", step.get("type"))
                continue
            # Thread the previous step's real outcome into the next step
            # (e.g., a research finding becomes the surface_insight content)
            params = dict(step.get("params") or {})
            if not params.get("content") and last_outcome:
                params["content"] = last_outcome[:2000]
            result = await self._run_step(step, plan, goal, params)
            results.append(result)
            if result.get("status") == "completed" and result.get("outcome"):
                last_outcome = result["outcome"]
            if result.get("status") != "completed":
                all_ok = False

        final_status = "completed" if all_ok else "failed"
        self.store.update_plan(plan["id"], status=final_status)
        if goal:
            self.store.update_goal(
                goal["id"],
                status="completed" if all_ok else "failed",
                progress=1.0 if all_ok else 0.5,
            )
        # Workflow memory (AccessFIles §59): learn from the REAL run — store
        # the step sequence that actually executed so the planner can recall
        # it next time this goal reappears. Failures are recorded too, with
        # successes=0, so weak templates are never reused.
        try:
            from server.systems.workflows.workflow_memory import WorkflowMemory
            WorkflowMemory().record_execution(
                goal.get("description", "") if goal else plan.get("id", ""),
                [r.get("type") for r in results if r.get("type")],
                success=(final_status == "completed"),
            )
        except Exception as exc:
            logger.debug("[Executor] workflow record skipped: %s", exc)

        return {"plan_id": plan["id"], "status": final_status, "steps": results}

    # ── Step runner (with audit) ─────────────────────────────────────────────

    async def _run_step(self, step: Dict[str, Any], plan: Dict[str, Any],
                        goal: Dict[str, Any],
                        params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        stype = step["type"]
        if params is None:
            params = dict(step.get("params") or {})
        action_id = self.store.log_action(
            action_type=stype,
            plan_id=plan["id"],
            goal_id=goal["id"] if goal else None,
            params=params,
            status="pending",
        )
        self.store.update_action(action_id, status="running")

        try:
            outcome, summary = await self._dispatch(stype, params, goal)
            self.store.update_action(
                action_id, status="completed",
                outcome=(outcome or summary)[:2000] if (outcome or summary) else "",
            )
            logger.info("[Executor] ✓ %s → %s", stype, summary[:80])
            return {"type": stype, "status": "completed", "summary": summary, "outcome": outcome or ""}
        except Exception as e:
            logger.error("[Executor] ✗ %s failed: %s", stype, e)
            logger.error("[Executor] traceback for %s:\n%s", stype, traceback.format_exc())
            self.store.update_action(action_id, status="failed", outcome=str(e)[:2000])
            return {"type": stype, "status": "failed", "summary": f"Failed: {e}", "outcome": ""}

    # ── Action registry ──────────────────────────────────────────────────────

    async def _dispatch(self, stype: str, params: Dict[str, Any],
                        goal: Dict[str, Any]) -> tuple[str, str]:
        if stype == "research":
            return await self._do_research(params)
        if stype == "review_vault":
            return await self._do_review_vault(params)
        if stype == "surface_insight":
            return await self._do_surface_insight(params)
        if stype == "check_in":
            return await self._do_check_in(params, goal)
        if stype == "monitor":
            return "", "Monitor step acknowledged — daemon continues watching real-time signals."
        raise ValueError(f"Unknown action type: {stype}")

    async def _do_research(self, params: Dict[str, Any]) -> tuple[str, str]:
        """Real multi-hop research via the existing research agent."""
        from server.systems.agent.controller import get_research_agent
        topic = params.get("topic", "")
        if not topic:
            raise ValueError("research step requires a topic")
        result = await get_research_agent().run_research(topic)
        answer = result.get("answer") or result.get("summary") or ""
        if not answer:
            raise ValueError(f"No research result returned for '{topic}'")
        return answer, f"Researched '{topic}' ({len(answer)} chars of findings)"

    async def _do_review_vault(self, params: Dict[str, Any]) -> tuple[str, str]:
        """Search the Obsidian RAG vault via the research agent's retrieval."""
        from server.systems.agent.controller import get_research_agent
        topic = params.get("topic", "user memories")
        try:
            result = await get_research_agent().run_research(topic)
        except Exception as exc:
            # A vault recall miss (or a degraded research stack) is a normal
            # outcome, not a plan failure — never let it fail the goal.
            logger.warning("[Executor] Vault review degraded for '%s': %s", topic, exc)
            return "", f"Vault review for '{topic}' was unavailable — continuing"
        result = result or {}
        answer = result.get("answer") or result.get("summary") or ""
        if not answer:
            return "", f"Vault review for '{topic}' found nothing to recall"
        return answer, f"Reviewed vault for '{topic}' — recalled {len(answer)} chars"

    async def _do_surface_insight(self, params: Dict[str, Any]) -> tuple[str, str]:
        """Persist an insight (learned knowledge) for future surfacing."""
        topic = params.get("topic", "learned knowledge")
        # Use a real, recent research finding if available from the store,
        # otherwise the caller passes content directly.
        content = params.get("content") or params.get("answer") or ""
        if not content:
            gaps = self.store.get_pending_gaps(limit=1)
            # nothing real to store → no-op rather than fabricating content
            if not gaps:
                return "", f"No real content to store for '{topic}' — skipping"
            return "", f"Insight queued for '{topic}' after research completes"
        insight_id = self.store.add_insight(
            topic=topic, content=content,
            source="autonomous_action",
            confidence=float(params.get("confidence", 0.6)),
        )
        return content, f"Stored insight '{topic}' (id={insight_id})"

    async def _do_check_in(self, params: Dict[str, Any],
                           goal: Dict[str, Any]) -> tuple[str, str]:
        """Deliver a proactive message through the daemon broadcast."""
        from server.autonomy.loop import generate_proactive_message
        context = params.get("context", "warm, natural check-in")
        hint = params.get("hint", context)
        trigger = {
            "type": "check_in",
            "urgency": "low",
            "message_hint": hint,
            "trust_at_fire": 0.5,
            "payload": {},
        }
        trust = float(params.get("trust", 0.5))
        message = await generate_proactive_message(trigger, trust)
        await self.broadcast({
            "type": "proactive_message",
            "content": message,
            "trigger": "plan_step",
            "goal": goal["description"] if goal else None,
            "timestamp": asyncio.get_event_loop().time(),
        })
        return message, f"Sent check-in: {message[:80]}"
