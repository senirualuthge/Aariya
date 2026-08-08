"""
FIXV3 Initiative Guard
Rate-limits AI autonomous initiation to prevent clingy / spammy behavior.
Used by AutonomousLoop before sending proactive messages.
"""

import time
from typing import Dict

from server.autonomy.config import config


class InitiativeGuard:
    """
    Controls when the AI may autonomously initiate contact.

    Rules:
    - Minimum cooldown between initiations per user (default 5 minutes)
    - Blocked entirely if attachment is dangerously high (prevents clingy)
    - Maximum N initiations per hour per user (default 3)

    All tunables are env-configurable via AARIYA_* (server/autonomy/config.py).
    """

    COOLDOWN_SECONDS = config.INITIATIVE_COOLDOWN_SECONDS   # between initiations
    MAX_PER_HOUR = config.INITIATIVES_PER_HOUR              # hard cap per hour
    ATTACHMENT_BLOCK_THRESHOLD = config.ATTACHMENT_BLOCK_THRESHOLD  # clingy guard

    def __init__(self):
        # user_id -> last initiation time
        self._last_initiation: Dict[str, float] = {}
        # user_id -> list of recent initiation timestamps (last hour)
        self._hourly_log: Dict[str, list] = {}

    def allow(self, user_id: str, trust: float, attachment: float) -> bool:
        """
        Decide if AI should be allowed to initiate for this user.

        Returns:
            True if initiation is allowed, False otherwise
        """
        now = time.time()

        # Block if attachment is dangerously high (prevents clingy behavior)
        if attachment > self.ATTACHMENT_BLOCK_THRESHOLD:
            return False

        # Minimum trust required to initiate
        if trust < 0.3:
            return False

        # Cooldown check
        last = self._last_initiation.get(user_id, 0)
        if now - last < self.COOLDOWN_SECONDS:
            return False

        # Hourly rate limit
        hourly = self._hourly_log.get(user_id, [])
        # Remove timestamps older than 1 hour
        hourly = [t for t in hourly if now - t < 3600]
        self._hourly_log[user_id] = hourly

        if len(hourly) >= self.MAX_PER_HOUR:
            return False

        # All checks passed — record this initiation
        self._last_initiation[user_id] = now
        self._hourly_log[user_id].append(now)

        return True

    def reset(self, user_id: str):
        """Reset rate limiting for a user (e.g., after user initiates conversation)."""
        self._last_initiation.pop(user_id, None)
        self._hourly_log.pop(user_id, None)


# Global singleton
_initiative_guard: InitiativeGuard | None = None


def get_initiative_guard() -> InitiativeGuard:
    global _initiative_guard
    if _initiative_guard is None:
        _initiative_guard = InitiativeGuard()
    return _initiative_guard
