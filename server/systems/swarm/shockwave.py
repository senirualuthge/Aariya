"""
Shockwave Propagation Engine (Agents Swarm Visualize §244) — causal cascades.

When an agent's state changes, the influence propagates through the graph like
a physics wave:

    impact(t+1) = decay × adjacency × impact(t)

Produces a history of impact vectors so the UI can render ripple effects,
cascading failures, and "event gravity". Pure numpy; adjacency can be a dense
or sparse matrix of interaction weights between agents.
"""

from typing import Dict, List, Optional

import numpy as np


class ShockwaveEngine:
    def __init__(self, decay: float = 0.85):
        self.decay = decay

    def propagate(
        self,
        adjacency: "np.ndarray",
        initial_impact: "np.ndarray",
        steps: int = 5,
    ) -> List["np.ndarray"]:
        """
        Propagate an initial impact vector through the graph.

        adjacency    : NxN weight matrix (interaction / influence strength).
        initial_impact: length-N impact vector (0 = none).
        Returns      : list of impact vectors [t0, t1, ..., t_steps].
        """
        adjacency = np.asarray(adjacency, dtype=float)
        impact = np.asarray(initial_impact, dtype=float)
        history = [impact.copy()]
        for _ in range(steps):
            impact = self.decay * (adjacency @ impact)
            history.append(impact)
        return history

    def build_adjacency(
        self,
        agent_ids: List[str],
        edges: List[Dict],
    ) -> "np.ndarray":
        """Build an NxN adjacency from [{source, target, weight}] edges."""
        n = len(agent_ids)
        idx = {a: i for i, a in enumerate(agent_ids)}
        adj = np.zeros((n, n))
        for e in edges:
            s = idx.get(e.get("source"))  # type: ignore[arg-type]
            t = idx.get(e.get("target"))  # type: ignore[arg-type]
            if s is not None and t is not None:
                adj[s, t] += float(e.get("weight", 1.0))
        return adj

    def cascade(
        self,
        agent_ids: List[str],
        edges: List[Dict],
        source: str,
        impact: float = 1.0,
        steps: int = 5,
    ) -> Dict:
        """High-level helper: inject an impact at `source` and report cascades."""
        idx = {a: i for i, a in enumerate(agent_ids)}
        n = len(agent_ids)
        if source not in idx:
            return {"source": source, "history": [], "affected": []}
        initial = np.zeros(n)
        initial[idx[source]] = impact
        history = self.propagate(self.build_adjacency(agent_ids, edges), initial, steps)
        affected = []
        for i, a in enumerate(agent_ids):
            peak = max(float(h[i]) for h in history)
            if peak > 1e-9:
                affected.append({"agent": a, "peak": round(peak, 4), "reached_at": None})
        return {"source": source, "history": [h.tolist() for h in history], "affected": affected}
