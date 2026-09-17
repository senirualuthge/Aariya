"""
Voice-controlled file operations — turns spoken commands into guarded FS
operations via the FileSystemAgent. All paths still pass through the safety
guard; destructive intents require confirmation (returned as a request, not
executed).
"""

import logging
import re

from server.systems.desktop.desktop_controller import DesktopController
from server.systems.filesystem.filesystem_agent import FileSystemAgent
from server.systems.workflows.workflow_memory import normalize_name

logger = logging.getLogger("aariya.voice_file_controller")


class VoiceFileController:
    def __init__(self, fs_agent: FileSystemAgent | None = None):
        self.fs = fs_agent or FileSystemAgent()
        self.desktop = DesktopController()

    async def process_command(self, text: str) -> dict:
        if not text:
            return {"status": "empty"}
        t = text.strip().lower()

        # ── open ───────────────────────────────────────────────────────────────
        for target in ("downloads", "desktop", "documents"):
            if f"open {target}" in t:
                path = f"~/{target.capitalize()}"
                ok = self.fs.open_path(path)
                return {"status": "ok" if ok else "denied", "action": "open", "path": path}

        # ── search ─────────────────────────────────────────────────────────────
        m = re.search(r"search for (.+)", t)
        if m:
            query = m.group(1).strip()
            results = self.fs.search_files("~/Downloads", query) or \
                      self.fs.search_files("~/Documents", query)
            return {"status": "ok", "action": "search", "query": query, "results": results[:10]}

        # ── create note ────────────────────────────────────────────────────────
        m = re.search(r"(?:create|make) (?:a )?note(?: (?:saying|about))?(?: that)? (.*)", t)
        if m:
            content = m.group(1).strip()
            ok = self.fs.append_file("~/notes/voice_note.txt", content + "\n")
            return {"status": "ok" if ok else "denied", "action": "note", "path": "~/notes/voice_note.txt"}

        # ── read ───────────────────────────────────────────────────────────────
        m = re.search(r"read (?:the )?(?:file )?(.+)", t)
        if m and ("read" in t):
            path = m.group(1).strip()
            content = self.fs.read_file(path)
            if content and content not in ("File not found.", "File not accessible.", "Cannot read directory."):
                return {"status": "ok", "action": "read", "path": path, "content": content[:2000]}

        # ── learned-workflow recall (AccessFIles §31: voice + OS fusion) ───────
        # "run workflow <name>" exactly, or a fuzzy match of the rest of the
        # utterance against workflows actually executed before. Steps are
        # real recorded step types replayed through the guarded agent.
        m = re.search(r"(?:run|start|execute)(?: the)?(?: workflow)? (.+)", t)
        if m and any(w in t for w in ("workflow", "routine", "setup")):
            return await self._run_learned_workflow(m.group(1).strip())

        return {"status": "not_understood"}

    async def _run_learned_workflow(self, spoken_name: str) -> dict:
        """Find the best-matching REAL workflow and run it for real.

        Sources, in priority order:
          1. Desktop-routine workflows saved by observation (launch_app steps
             for apps the user demonstrably opens together — §59).
          2. Manually saved workflows (save_workflow).
        Steps are executed through DesktopController.launch_app (OS launcher,
        input-validated) or acknowledged honestly when they need the brain.
        """
        try:
            from server.systems.workflows.workflow_memory import WorkflowMemory
            wm = WorkflowMemory()
            saved = wm.all_workflows()
            learned = wm.known_workflows()
        except Exception:
            wm, saved, learned = None, {}, {}

        # Observation-mined desktop routines (real app sequences).
        if wm is not None and not any("routine:" in k.lower() for k in saved):
            try:
                from server.systems.desktop_twin import get_desktop_twin
                twin = get_desktop_twin("user_default")
                for r in twin.frequent_app_routines(min_support=3)[:5]:
                    name = f"routine: {' + '.join(r['apps'][:2])}"
                    steps_payload = [{"action": "launch_app", "app": a} for a in r["apps"]]
                    wm.save_workflow(name, steps_payload)
                    saved[name] = steps_payload
            except Exception:
                pass

        candidates = set(saved.keys()) | set(learned.keys())
        if not candidates:
            return {"status": "no_workflows", "spoken": spoken_name}

        spoken = spoken_name.lower()
        best, best_score = None, 0.0
        import difflib
        for name in candidates:
            name_l = normalize_name(name).replace("routine:", "").lower()
            if not name_l:
                continue
            sw, nw = set(spoken.split()), set(name_l.split())
            overlap = len(sw & nw)
            score = overlap / max(1, min(len(sw), len(nw))) if overlap else 0.0
            # Layered fallbacks so natural phrasing still matches.
            if name_l in spoken or spoken in name_l:
                score = max(score, 0.9)
            else:
                ratio = difflib.SequenceMatcher(None, spoken, name_l).ratio()
                score = max(score, ratio if ratio >= 0.5 else 0.0)
            if score > best_score:
                best, best_score = name, score
        if best is None or best_score < 0.34:
            return {"status": "not_understood", "spoken": spoken_name,
                    "known": sorted(candidates)[:10]}

        raw_steps = (saved.get(best)
                     or [{"type": t} for t in (learned.get(best, {}).get("steps") or [])])
        executed = []
        for step in raw_steps[:8]:
            executed.append(self._replay_step(step))
        return {"status": "ok", "action": "workflow",
                "workflow": best, "confidence": round(best_score, 2),
                "executed": executed}

    def _replay_step(self, step: dict) -> dict:
        """Execute one workflow step for real where it maps to an OS action;
        brain-only steps are skipped with an honest reason (never faked)."""
        step_type = step.get("action") or step.get("type") or ""
        if step_type == "launch_app" and step.get("app"):
            ok = self.desktop.launch_app(str(step["app"]))
            return {"step": "launch_app", "app": step["app"],
                    "ok": ok}
        if step_type == "research":
            return {"step": step_type, "skipped": True, "reason": "needs live research topic"}
        if step_type in ("review_vault", "check_in", "surface_insight"):
            return {"step": step_type, "skipped": True, "reason": "runs inside the brain with consent"}
        if step_type == "monitor":
            return {"step": step_type, "ok": True, "reason": "monitoring already active"}
        return {"step": step_type, "skipped": True,
                "reason": f"no direct OS mapping for '{step_type}'"}
