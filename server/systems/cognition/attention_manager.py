"""
Attention Manager — single focus tracker for the cognitive loop.

Controls what the system is actively reasoning about. Focus is a string
identifier (e.g. "research:prediction_engine") so the planner and agents
share one notion of "what matters now".
"""

from typing import Any, Optional


class AttentionManager:
    def __init__(self):
        self.focus: Optional[str] = None

    def set_focus(self, item: str) -> None:
        self.focus = item

    def get_focus(self) -> Optional[str]:
        return self.focus

    def clear(self) -> None:
        self.focus = None
