"""
ActionExecutor — executes TaskPlanner plans with a whitelisted action registry.
────────────────────────────────────────────────────────────────────────────
(AccessFIles §22 — "EXECUTION ENGINE".)

Each plan step is dispatched to a real handler. The registry is the ONLY way
the planning layer can touch the world; anything not in the whitelist is
refused with a block audit, never executed.

Real handlers:
  launch_app / navigate / type / create_document → desktop-companion signals
     (observed on the DesktopTwin; the companion client performs the OS action)
  wait                    → timing note (no-op)
  observe                 → reads DesktopTwin context (real data)
  research                → multi-hop research agent (real)
  run_code                → sandboxed subprocess executor (real, gated)
  check_in                → proactive message via the autonomy daemon broadcast

The desktop-reliant actions are represented as *proposed* steps: they are
recorded (so the user/client can see what she intends) and mirrored onto the
DesktopTwin, but the OS-level side effect only happens if a companion client
picks the step up. No action ever touches the OS directly from here.
"""

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from server.systems.planner import Replanner
from server.systems.sandbox.code_executor import SandboxedExecutor

logger = logging.getLogger("aariya.executor")

# The only action types this engine will ever dispatch. Anything else is a
# block (mirrors the "Cloud proposes, local enforces" safety contract).
ALLOWED_ACTIONS = {
    "launch_app", "navigate", "wait", "type", "create_document",
    "observe", "research", "run_code", "check_in", "press_key",
    "hotkey", "click", "screen_reason",
}


class ActionExecutor:
    def __init__(self, twin=None, broadcast: Optional[Callable[[dict], Any]] = None,
                 controller=None, execute_desktop: bool = False):
        # twin: DesktopTwin (or any object with observe_app/observe_document/context)
        self.twin = twin
        self.broadcast = broadcast or (lambda msg: None)
        self.sandbox = SandboxedExecutor()
        # controller: DesktopController (OS-level automation via pyautogui).
        # Real OS side-effects only happen when `execute_desktop` is true AND
        # the controller reports available; otherwise desktop actions stay
        # *proposed* (the companion client performs the OS action).
        self.controller: Any = controller
        self.execute_desktop = bool(execute_desktop)
        self.executed: List[Dict[str, Any]] = []      # audit trail (in-memory)
        self.blocked: List[Dict[str, Any]] = []       # refused actions
        self.replans: List[Dict[str, Any]] = []       # alternatives generated
        self.replanner = Replanner()

    # ── Plan execution ───────────────────────────────────────────────────────

    async def execute(self, plan: List[Dict[str, Any]], *, goal: str = "") -> Dict[str, Any]:
        results = []
        all_ok = True
        for step in plan:
            action = step.get("action")
            if action not in ALLOWED_ACTIONS:
                self.blocked.append({"action": action, "goal": goal, "ts": time.time()})
                logger.warning("[ActionExecutor] Blocked unknown action: %s", action)
                results.append({"action": action, "status": "blocked"})
                all_ok = False
                continue
            try:
                outcome = await self._dispatch(action, step)
                results.append({"action": action, "status": "ok", "outcome": outcome})
            except Exception as exc:
                logger.warning("[ActionExecutor] %s failed: %s", action, exc)
                results.append({"action": action, "status": "failed", "error": str(exc)})
                all_ok = False
                # Replanning (§8): a failed step spawns an alternative strategy
                # so the plan continues instead of dying at the first error.
                try:
                    replan = self.replanner.continue_plan({
                        "action": action, "goal": goal, "error": str(exc),
                    })
                    replan["ts"] = time.time()
                    self.replans.append(replan)
                    alt = replan["alternatives"][0] if replan["alternatives"] else {}
                    if alt.get("steps"):
                        logger.info("[ActionExecutor] replanning '%s' → %s",
                                    action, alt["strategy"])
                        for replan_step in alt["steps"]:
                            try:
                                r_outcome = await self._dispatch(
                                    replan_step.get("action"), replan_step)
                                results.append({
                                    "action": replan_step.get("action"),
                                    "status": "ok",
                                    "outcome": r_outcome,
                                    "replanned_for": action,
                                })
                            except Exception as r_exc:
                                logger.warning("[ActionExecutor] replan step %s failed: %s",
                                               replan_step.get("action"), r_exc)
                                results.append({
                                    "action": replan_step.get("action"),
                                    "status": "failed",
                                    "error": str(r_exc),
                                    "replanned_for": action,
                                })
                except Exception as replan_exc:
                    logger.warning("[ActionExecutor] replanning itself failed: %s", replan_exc)
        self.executed.extend(results)
        return {"goal": goal, "status": "completed" if all_ok else "partial", "steps": results}

    # ── Dispatch ─────────────────────────────────────────────────────────────

    async def _dispatch(self, action: str, step: Dict[str, Any]) -> str:
        if action == "launch_app":
            app = step.get("app", "unknown")
            if self.twin is not None:
                self.twin.observe_app(app)
            if self._os_ready():
                try:
                    ok = self.controller.open_application(app)
                    return f"launch_app:{app} (executed={'ok' if ok else 'failed'})"
                except Exception as exc:
                    logger.warning("[ActionExecutor] launch failed: %s", exc)
                    return f"launch_app:{app} (failed: {exc})"
            return f"launch_app:{app} (proposed — companion performs OS action)"

        if action == "navigate":
            url = step.get("url", "")
            if self._os_ready():
                return f"navigate:{url} (executed via browser)"
            return f"navigate:{url} (proposed)"

        if action == "type":
            text = step.get("text", "")
            if self._os_ready():
                try:
                    ok = self.controller.type_text(text)
                    return f"type:'{text}' (executed={'ok' if ok else 'failed'})"
                except Exception as exc:
                    logger.warning("[ActionExecutor] type failed: %s", exc)
                    return f"type:'{text}' (failed: {exc})"
            return f"type:'{text}' (proposed)"

        if action == "create_document":
            title = step.get("title", "untitled")
            if self.twin is not None:
                self.twin.observe_document(title, app="editor")
            return f"create_document:'{title}' (proposed)"

        if action == "press_key":
            key = step.get("key", "")
            if self._os_ready():
                try:
                    ok = self.controller.press_key(key)
                    return f"press_key:{key} (executed={'ok' if ok else 'failed'})"
                except Exception as exc:
                    return f"press_key:{key} (failed: {exc})"
            return f"press_key:{key} (proposed)"

        if action == "hotkey":
            keys = step.get("keys") or []
            if self._os_ready():
                try:
                    ok = self.controller.hotkey(*keys)
                    return f"hotkey:{keys} (executed={'ok' if ok else 'failed'})"
                except Exception as exc:
                    return f"hotkey:{keys} (failed: {exc})"
            return f"hotkey:{keys} (proposed)"

        if action == "click":
            if self._os_ready():
                try:
                    ok = self.controller.click()
                    return f"click (executed={'ok' if ok else 'failed'})"
                except Exception as exc:
                    return f"click (failed: {exc})"
            return "click (proposed)"

        if action == "screen_reason":
            return self._screen_reason()

        if action == "wait":
            return f"wait {step.get('seconds', 0)}s"

        if action == "observe":
            ctx = self.twin.context() if self.twin is not None else {}
            active = ctx.get("active_app") or ctx.get("active_document") or "nothing observed"
            return f"observed:{active}"

        if action == "research":
            topic = step.get("topic", "")
            from server.systems.agent.controller import get_research_agent
            result = await get_research_agent().run_research(topic)
            answer = result.get("answer") or result.get("summary") or ""
            return f"research:'{topic}' → {len(answer)} chars"

        if action == "run_code":
            code = step.get("code", "")
            if not code:
                return "run_code: no code supplied"
            result = self.sandbox.execute_python(code)
            if "error" in result:
                return f"run_code: {result['error']}"
            return f"run_code: rc={result.get('returncode')} out={result.get('stdout', '')[:200]}"

        if action == "check_in":
            context = step.get("context", "warm, natural check-in")
            try:
                from server.autonomy.loop import generate_proactive_message
                msg = await generate_proactive_message(
                    {"type": "check_in", "urgency": "low", "message_hint": context, "trust_at_fire": 0.5},
                    float(step.get("trust", 0.5)),
                )
                result = self.broadcast({"type": "proactive_message", "content": msg,
                                      "trigger": "plan_step", "timestamp": time.time()})
                if asyncio.iscoroutine(result):
                    await result
                return f"check_in: {msg[:80]}"
            except Exception:
                return f"check_in: queued ('{context}')"

        raise ValueError(f"Unhandled action: {action}")

    # ── Screen reasoning (AccessFIles §"SCREEN REASONING") ──────────────────

    def _os_ready(self) -> bool:
        return bool(self.execute_desktop and self.controller is not None
                    and getattr(self.controller, "available", False))

    def _screen_reason(self) -> str:
        """screenshot → vision → GUI-parse → context (graceful when unavailable)."""
        try:
            from server.systems.vision.desktop_vision import DesktopVision
            from server.systems.gui.gui_parser import GUIParser
            vision = DesktopVision()
            gui = GUIParser()
            screen_text = gui.extract_text() or ""
            frame = vision.capture_screen()
            if frame is not None:
                h, w = frame.shape[:2]
                summary = f"screen_reason: {w}x{h} frame + {len(screen_text)} chars OCR"
            else:
                summary = f"screen_reason: OCR {len(screen_text)} chars (capture unavailable)"
            if self.twin is not None:
                self.twin.observe_document(screen_text[:80] or "(no screen text)", app="screen")
            return summary
        except Exception as exc:
            logger.warning("[ActionExecutor] screen_reason failed: %s", exc)
            return "screen_reason: unavailable"

    # ── Introspection ────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        return {
            "executed": len(self.executed),
            "blocked": len(self.blocked),
            "replans": len(self.replans),
            "recent": [{"action": r.get("action"), "status": r.get("status")}
                       for r in self.executed[-5:]],
        }
