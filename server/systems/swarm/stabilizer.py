"""
Self-Correcting Swarm Stabilization (Agents Swarm Visualize §245).

Autonomous control loop that damps instability in the swarm:

    adjustment = -λ × gradient(entropy)

Prevents collapse, smooths chaotic bursts, and keeps the swarm "alive but
controlled". Works directly on the agent list by nudging velocities toward
the swarm centroid proportional to how spread out / energetic the swarm is.
"""

from typing import Any, Dict, List

import numpy as np


class SwarmStabilizer:
    def __init__(self, lambda_: float = 0.1, max_delta: float = 0.5):
        self.lambda_ = lambda_
        self.max_delta = max_delta  # per-tick velocity correction cap

    def compute_entropy(self, positions: "np.ndarray") -> float:
        """Sum of per-axis variance = spatial disorder."""
        var = np.var(positions, axis=0)
        return float(np.sum(var))

    def energy(self, agents: List[Dict[str, Any]]) -> float:
        """Mean kinetic energy (speed^2) — high = volatile."""
        speeds = [a.get("vx", 0.0) ** 2 + a.get("vy", 0.0) ** 2 for a in agents]
        return float(np.mean(speeds)) if speeds else 0.0

    def stability_score(self, agents: List[Dict[str, Any]]) -> float:
        """0..1 — 1 = perfectly stable (no spread, no kinetic energy)."""
        if not agents:
            return 1.0
        positions = np.array([[a.get("x", 0.0), a.get("y", 0.0)] for a in agents], dtype=float)
        entropy = self.compute_entropy(positions)
        kinetic = self.energy(agents)
        # normalize: entropy typically 0..(scale^2), kinetic typically 0..tens
        norm = entropy / (1.0 + entropy) + kinetic / (1.0 + kinetic)
        return float(max(0.0, min(1.0, 1.0 - norm / 2.0)))

    def stabilize(self, agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Nudge every agent's velocity toward the swarm centroid to reduce
        disorder. Returns the same list (mutated) plus a report in .report.
        """
        if not agents:
            self.report = {"entropy": 0.0, "correction": 0.0, "stability": 1.0}
            return agents
        positions = np.array([[a.get("x", 0.0), a.get("y", 0.0)] for a in agents], dtype=float)
        centroid = positions.mean(axis=0)
        entropy = self.compute_entropy(positions)
        correction = -self.lambda_ * entropy
        correction = max(-self.max_delta, min(self.max_delta, correction))

        for a in agents:
            dx = centroid[0] - a.get("x", 0.0)
            dy = centroid[1] - a.get("y", 0.0)
            a["vx"] = a.get("vx", 0.0) + correction * 0.01 + dx * correction * 0.001
            a["vy"] = a.get("vy", 0.0) + correction * 0.01 + dy * correction * 0.001

        self.report = {
            "entropy": round(entropy, 4),
            "correction": round(correction, 4),
            "stability": round(self.stability_score(agents), 4),
        }
        return agents
