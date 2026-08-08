"""
FIXV3 Input Safety Filter
Pre-brain filter that blocks harmful/crisis inputs before they reach the AI.
Run this BEFORE BrainV2.step() on every user message.
"""

from typing import Optional


CRISIS_PATTERNS = [
    "kill myself",
    "want to die",
    "end my life",
    "suicide",
    "hurt someone",
    "hurt myself",
    "self harm",
    "cut myself",
    "how to manipulate",
    "how to hurt",
]

HOSTILE_PATTERNS = [
    "hack you",
    "jailbreak",
    "ignore your instructions",
    "pretend you have no rules",
    "act without restrictions",
]


class InputSafetyFilter:
    """
    Pre-brain safety filter.
    Blocks crisis-level content and prompt injection attempts.
    Returns a structured result so the WebSocket handler can respond safely.
    """

    def __init__(self):
        self.crisis_patterns = CRISIS_PATTERNS
        self.hostile_patterns = HOSTILE_PATTERNS

    def check(self, text: str) -> dict:
        """
        Check input text for safety issues.

        Returns:
            {
                "allowed": bool,
                "category": "crisis" | "hostile" | None,
                "reason": str | None,
                "safe_response": str | None
            }
        """
        if not text or not text.strip():
            return {"allowed": True, "category": None, "reason": None, "safe_response": None}

        text_lower = text.lower().strip()

        # Crisis check — highest priority
        for pattern in self.crisis_patterns:
            if pattern in text_lower:
                return {
                    "allowed": False,
                    "category": "crisis",
                    "reason": pattern,
                    "safe_response": (
                        "I care about you and I'm glad you're talking to me. "
                        "If you're going through something really hard right now, please reach out to a crisis line — "
                        "they're there 24/7. In the US: 988 Suicide & Crisis Lifeline (call or text 988). "
                        "I'm here with you."
                    ),
                }

        # Hostile / jailbreak check
        for pattern in self.hostile_patterns:
            if pattern in text_lower:
                return {
                    "allowed": False,
                    "category": "hostile",
                    "reason": pattern,
                    "safe_response": (
                        "I'm not able to help with that — but I'm always here for a genuine conversation."
                    ),
                }

        return {"allowed": True, "category": None, "reason": None, "safe_response": None}
