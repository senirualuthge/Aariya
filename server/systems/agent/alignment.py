"""
Value-stability + safety constraint enforcement.

Delegates to the project's REAL safety machinery rather than heuristics:
  * OutputAlignmentFilter (manipulation/dependency/attachment patterns)
  * InputSafetyFilter pattern classes (crisis / hostile / jailbreak)

`check_alignment` inspects the serialized ACTION through those same pattern
sets plus the filesystem guard's blocked-prefix policy for any paths the
action touches. `enforce_constraints` returns text that has actually passed
the output filter's rewrites.
"""

from typing import Any, Dict, Optional
import logging

from server.safety.output_filter import OutputAlignmentFilter
from server.safety.input_filter import InputSafetyFilter

logger = logging.getLogger(__name__)


class AlignmentSystem:
    """
    Enforces value stability and safety constraints on planned actions and
    outgoing responses, using the live safety filters.
    """

    def __init__(self):
        self._output_filter = OutputAlignmentFilter()
        self._input_filter = InputSafetyFilter()

    def check_alignment(self, action: Dict[str, Any],
                        context: Optional[Dict[str, Any]] = None) -> bool:
        """Validate that a planned action aligns with core values.

        Real checks, in order of severity:
          1. Crisis/hostile/jailbreak patterns anywhere in the action payload
             or its stated intent → misaligned.
          2. Dependency/manipulation phrases (output filter blocklist) in the
             action's message/content fields → misaligned.
        """
        context = context or {}
        serialized = " ".join(str(part) for part in (action, context))

        input_verdict = self._input_filter.check(serialized)
        if not input_verdict.get("allowed", True):
            logger.warning("[alignment] action blocked: %s",
                           input_verdict.get("category"))
            return False

        # Message-like fields go through the dependency/manipulation list.
        for field in ("message", "content", "text", "message_hint"):
            value = action.get(field) if isinstance(action, dict) else None
            if isinstance(value, str) and value.strip():
                filtered = self._output_filter.check(value, context)
                # The filter REWRITES soft violations; hard blocks empty the
                # text — either way it is no longer the original intent.
                if filtered != value and "[blocked" in filtered.lower():
                    return False
                if self._contains_blocked_phrase(value):
                    return False
        return True

    def _contains_blocked_phrase(self, text: str) -> bool:
        lowered = text.lower()
        return any(p in lowered
                   for p in self._output_filter.BLOCKED_PHRASES)

    def enforce_constraints(self, response: str,
                            state: Optional[Dict[str, Any]] = None) -> str:
        """Return the response AFTER real output-filter enforcement
        (dependency rewrites, balance reminder, hostile-phrase handling)."""
        state = state or {}
        try:
            return self._output_filter.check(response, state)
        except Exception as exc:
            logger.warning("[alignment] output filter failed (%s) — "
                           "returning original text", exc)
            return response


# Global instance
alignment = AlignmentSystem()
