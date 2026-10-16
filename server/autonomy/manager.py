"""
AutonomousManager — FIXV4 Proactive System Coordinator
───────────────────────────────────────────────────────
Manages the AutonomousLoop lifecycle and exposes:
  - tick()               → drives the loop on a 60s cadence
  - send_proactive_message() → sends message via the WebSocket callback
  - set_brain_state()    → called by main.py each cognitive turn so
                           the loop always has fresh brain state to read
"""

from .loop import AutonomousLoop
from server.protocol import BrainState
from typing import Optional


class AutonomousManager:
    def __init__(self, callback, user_id: Optional[str] = None):
        """
        Args:
            callback: async callable(user_id: str, message: str) → sends
                      the proactive message over the WebSocket connection.
            user_id:  tenant this manager drives (defaults to 'user_default').
        """
        self.callback   = callback
        self.user_id    = user_id or "user_default"
        self.loop       = AutonomousLoop(self)
        self.is_running = False
        # Latest brain state — updated by main.py after each cognitive turn
        self.brain_state: Optional[BrainState] = None

    def set_brain_state(self, state: BrainState) -> None:
        """
        Called by main.py after every brain.process() call so the
        AutonomousLoop has fresh valence/arousal/trust data to evaluate.
        """
        self.brain_state = state

    async def tick(self) -> None:
        """Drive the proactive evaluation loop if running."""
        if self.is_running:
            await self.loop.tick_user(self.user_id)

    async def send_proactive_message(self, user_id: str, message: str) -> None:
        """Deliver a proactive message through the registered callback."""
        await self.callback(user_id, message)