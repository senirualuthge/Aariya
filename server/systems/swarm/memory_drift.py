"""
Live Memory + Narrative Drift Tracking (Agents Swarm Visualize §246).

Tracks how "the swarm story is changing" over time. Each frame appends a
state snapshot; drift_score quantifies how far the swarm moved between frames.
A per-domain variance tracker exposes which domain drifted the most, feeding
the narrative + anomaly layers.

(Transformer-based embedding drift is the documented upgrade path — this
module stays dependency-light and deterministic.)
"""

from collections import deque
from typing import Any, Dict, List

import numpy as np


class NarrativeMemory:
    def __init__(self, size: int = 100):
        self.history: deque = deque(maxlen=size)

    def add_state(self, state: List[Dict[str, Any]]) -> None:
        """Append a swarm snapshot (list of agent dicts)."""
        self.history.append(list(state))

    def _centroid(self, state: List[Dict[str, Any]], key: str = "x") -> float:
        if not state:
            return 0.0
        return float(np.mean([a.get(key, 0.0) for a in state]))

    def drift_score(self) -> float:
        """Scalar distance between the last two snapshots (0 when <2 frames)."""
        if len(self.history) < 2:
            return 0.0
        prev = self.history[-2]
        curr = self.history[-1]
        dx = abs(self._centroid(curr, "x") - self._centroid(prev, "x"))
        dy = abs(self._centroid(curr, "y") - self._centroid(prev, "y"))
        return round(dx + dy, 4)

    def domain_drift(self) -> Dict[str, float]:
        """Per-axis drift magnitude (x, y, and optionally vx/vy)."""
        if len(self.history) < 2:
            return {}
        prev = self.history[-2]
        curr = self.history[-1]
        drift = {}
        for axis in ("x", "y"):
            drift[axis] = round(abs(self._centroid(curr, axis) - self._centroid(prev, axis)), 4)
        return drift

    def trend(self, window: int = 5) -> Dict[str, Any]:
        """Rolling average of drift over the last `window` frames."""
        recent = list(self.history)[-window:]
        if len(recent) < 2:
            return {"drift": 0.0, "direction": "stable", "frames": len(recent)}
        vals = []
        for i in range(1, len(recent)):
            p, c = recent[i - 1], recent[i]
            vals.append(abs(self._centroid(c, "x") - self._centroid(p, "x")) +
                        abs(self._centroid(c, "y") - self._centroid(p, "y")))
        avg = float(np.mean(vals))
        direction = "diverging" if avg > 2.0 else "evolving" if avg > 0.5 else "stable"
        return {"drift": round(avg, 4), "direction": direction, "frames": len(recent)}
