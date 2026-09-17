"""
Synoptic smoother — EMA smoothing + velocity tracking for stable visualization.

The doc's SynopticSmoother + SynopticDynamics. `smooth` applies an exponential
moving average to keep domain signals frame-to-frame stable; `velocity`
tracks the rate of change so the frontend can predictively ease orbits.
"""

from typing import Dict, Any


class SynopticSmoother:
    def __init__(self, alpha: float = 0.2):
        self.alpha = alpha
        self.prev: Dict[str, float] = {}
        self.velocity: Dict[str, float] = {}

    def smooth(self, domains: Dict[str, float]) -> Dict[str, float]:
        smoothed = {}
        for k, v in domains.items():
            prev_v = self.prev.get(k, v)
            new_v = (1 - self.alpha) * prev_v + self.alpha * v
            self.velocity[k] = new_v - prev_v
            smoothed[k] = round(new_v, 4)
        self.prev = smoothed
        return smoothed

    def snapshot(self) -> Dict[str, Any]:
        return {
            "smoothed": dict(self.prev),
            "velocity": {k: round(v, 4) for k, v in self.velocity.items()},
        }
