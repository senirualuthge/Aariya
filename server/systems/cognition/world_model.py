"""
World Model — the single evolving representation of user + environment.

Agents should query this instead of scattering ad-hoc state. Provides a
get/update interface plus a JSON snapshot for the dashboard.
"""

import copy
import time
import logging
from typing import Any, Dict

logger = logging.getLogger("aariya.world_model")


class WorldModel:
    def __init__(self):
        self.state: Dict[str, Any] = {
            "user": {},
            "goals": {},
            "projects": {},
            "environment": {},
            "knowledge": {},
            "events": [],
            "predictions": [],
            "active_apps": [],
            "open_documents": [],
            "current_goal": None,
            "system_state": {},
            "tasks": [],
        }

    def update(self, key: str, value: Any) -> None:
        if key not in self.state:
            logger.warning(f"[world_model] unknown slot {key!r} — storing under knowledge")
            self.state["knowledge"][key] = value
        else:
            self.state[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.state.get(key, default)

    def record_event(self, event: Dict[str, Any]) -> None:
        self.state["events"].append({"timestamp": time.time(), **event})
        # Keep the event log bounded.
        self.state["events"] = self.state["events"][-500:]

    def recent_events(self, days: float = 30) -> list:
        cutoff = time.time() - (days * 86400)
        return [e for e in self.state["events"] if e.get("timestamp", 0) > cutoff]

    def snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy(self.state)
