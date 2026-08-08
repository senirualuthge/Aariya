"""
L1 Working Memory — Per-Turn Scratchpad

The first layer of the 4-layer memory hierarchy:
  L1  Working Memory   — current turn only (this file)
  L2  Episodic Memory  — past sessions (episodic_memory.py)
  L3  Semantic Memory  — long-term ChromaDB store (memory_v2.py)
  L4  Emotional Memory — emotionally-tagged recall (memory_v2.py)

WorkingMemoryL1 holds a scratch-dict for the single active cognitive tick.
It is populated at the top of brain_v2.step() and flushed at the end.
Nothing persists beyond one turn — that is the whole point.

Usage:
    wm = WorkingMemoryL1()
    wm.begin_turn()                # clears previous scratch
    wm.write("valence", 0.4)
    wm.write("thoughts", "I am curious")
    snapshot = wm.snapshot()       # returns copy for logging
    # ... at bottom of step() ...
    wm.commit()                    # logs final state, marks turn done
"""

import time
import copy
from typing import Any, Optional


class WorkingMemoryL1:
    """
    Per-turn scratchpad (L1 Working Memory).

    Lifecycle per cognitive tick:
        begin_turn()  → clear previous scratch, stamp timestamp
        write(k, v)   → accumulate facts about this turn
        snapshot()    → peek at current state (non-destructive)
        commit()      → finalise and log (can be flushed to L2 externally)
    """

    def __init__(self):
        self.scratch: dict[str, Any] = {}
        self._turn_id: Optional[str] = None
        self._started_at: float = 0.0
        self._committed: bool = False
        self._history: list[dict] = []   # last 3 turns for velocity checks

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def begin_turn(self, turn_id: Optional[str] = None) -> None:
        """Clear scratch and start a new cognitive tick."""
        # Archive previous turn (keep last 3)
        if self.scratch:
            self._history.append(copy.deepcopy(self.scratch))
            self._history = self._history[-3:]

        self.scratch = {}
        self._turn_id = turn_id or f"turn_{int(time.time() * 1000)}"
        self._started_at = time.time()
        self._committed = False

    def write(self, key: str, value: Any) -> None:
        """Write a fact into the current turn's scratchpad."""
        self.scratch[key] = value

    def write_many(self, updates: dict[str, Any]) -> None:
        """Bulk-write multiple facts."""
        self.scratch.update(updates)

    def read(self, key: str, default: Any = None) -> Any:
        """Read a value from the current turn's scratch."""
        return self.scratch.get(key, default)

    def snapshot(self) -> dict:
        """Return a shallow copy of current scratch state."""
        return {
            "turn_id":    self._turn_id,
            "elapsed_ms": round((time.time() - self._started_at) * 1000, 1),
            "committed":  self._committed,
            "scratch":    dict(self.scratch),
        }

    def commit(self) -> dict:
        """
        Mark the turn as done.
        Returns the full snapshot for the brain to attach to enriched_context.
        """
        self._committed = True
        return self.snapshot()

    # ── Convenience accessors ─────────────────────────────────────────────────

    @property
    def valence(self) -> float:
        return float(self.scratch.get("valence", 0.0))

    @property
    def arousal(self) -> float:
        return float(self.scratch.get("arousal", 0.5))

    @property
    def trust(self) -> float:
        return float(self.scratch.get("trust", 0.5))

    @property
    def emotion_state(self) -> str:
        return str(self.scratch.get("emotion_state", "neutral"))

    def previous_turn(self) -> Optional[dict]:
        """Return the last committed scratch (or None if first turn)."""
        return self._history[-1] if self._history else None

    def velocity(self, key: str) -> float:
        """
        Compute rate-of-change for a numeric key across the last 2 turns.
        Returns 0.0 if insufficient history.
        """
        if len(self._history) < 2:
            return 0.0
        prev = self._history[-1].get("scratch", {}).get(key)
        curr = self.scratch.get(key)
        if prev is None or curr is None:
            return 0.0
        try:
            return float(curr) - float(prev)
        except (TypeError, ValueError):
            return 0.0
