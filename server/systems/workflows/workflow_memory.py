"""
Workflow Memory — Aariya learns repeated actions (doc *AccessFIles §5).

Persists named multi-step workflows to JSON so she can recall "daily startup",
"open my work apps", "prepare coding environment", etc. Safe, atomic writes;
step lists are copied on read so callers can't mutate the stored workflow.
"""

import json
import os
import threading
import time
from typing import Dict, List, Optional

_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
_WORKFLOWS_PATH = os.path.join(_DATA_DIR, "workflow_memory.json")

_LOCK = threading.Lock()
_EXEC_LOCK = threading.Lock()


def normalize_name(description: str) -> str:
    """Map a goal description to a stable workflow name so the same goal
    phrased slightly differently recalls the same learned workflow."""
    return " ".join(str(description or "").lower().split())[:120]


class WorkflowMemory:
    def __init__(self, path: Optional[str] = None):
        self.path = path or _WORKFLOWS_PATH

    def save_workflow(self, name: str, steps: List[Dict]) -> bool:
        """Persist a named workflow. `steps` is a list of step dicts."""
        if not name or not isinstance(steps, list):
            return False
        with _LOCK:
            data = self._load()
            data[name] = list(steps)
            self._dump(data)
        return True

    def load_workflow(self, name: str) -> Optional[List[Dict]]:
        """Return a copy of the named workflow's steps, or None if unknown."""
        with _LOCK:
            steps = self._load().get(name)
        return list(steps) if steps is not None else None

    def all_workflows(self) -> Dict[str, List[Dict]]:
        """Return {name: steps} for every stored workflow (copied)."""
        with _LOCK:
            data = self._load()
        return {k: list(v) for k, v in data.items()}

    def delete_workflow(self, name: str) -> bool:
        with _LOCK:
            data = self._load()
            existed = name in data
            if existed:
                del data[name]
                self._dump(data)
        return existed

    def _load(self) -> Dict[str, List[Dict]]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _dump(self, data: Dict[str, List[Dict]]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ── Execution history (AccessFIles §59 — learned from real plan runs) ────

    @property
    def _executions_path(self) -> str:
        return self.path.rsplit(".json", 1)[0] + "_executions.json"

    def record_execution(self, goal_description: str,
                         step_types: List[str], *, success: bool) -> bool:
        """Record a REAL completed plan run against its normalized goal name.

        Only the actually-executed step types are stored — never invented
        ones. Repeated successes strengthen the workflow; failures are counted
        so weak templates aren't reused.
        """
        name = normalize_name(goal_description)
        if not name or not isinstance(step_types, list):
            return False
        path = self._executions_path
        with _EXEC_LOCK:
            data = self._load_exec(path)
            entry = data.get(name) or {"steps": [], "runs": 0, "successes": 0}
            entry["steps"] = [str(s) for s in step_types][:10]
            entry["runs"] = int(entry.get("runs", 0)) + 1
            entry["successes"] = int(entry.get("successes", 0)) + (1 if success else 0)
            entry["last_ts"] = time.time()
            data[name] = entry
            self._dump_exec(path, data)
        return True

    def best_template(self, goal_description: str) -> Optional[List[str]]:
        """Step types of a previously-successful workflow for this goal, or
        None when it was never run successfully (callers fall through to the
        normal planner instead of guessing)."""
        name = normalize_name(goal_description)
        with _EXEC_LOCK:
            entry = self._load_exec(self._executions_path).get(name)
        if not entry or not entry.get("successes"):
            return None
        return list(entry.get("steps") or [])

    def known_workflows(self) -> Dict[str, Dict]:
        """All learned execution records {name: {steps, runs, successes}}."""
        with _EXEC_LOCK:
            return self._load_exec(self._executions_path)

    def _load_exec(self, path: str) -> Dict[str, Dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _dump_exec(self, path: str, data: Dict[str, Dict]) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
