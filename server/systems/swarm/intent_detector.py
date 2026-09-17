"""
Multi-Agent Intent Detection Layer (Agents Swarm Visualize §243).

Infers what each agent is "trying to do" by clustering agent features
(position + velocity) and describing each cluster's collective behavior
(converging / escaping / unstable / drifting). Pure numpy — no sklearn.

Feeds directly into the anomaly + prediction layers: each cluster's label,
centroid velocity, and spread become signals for intent-level reasoning.
"""

from typing import Any, Dict, List

import numpy as np


class IntentDetector:
    def __init__(self, k: int = 3, iterations: int = 25):
        self.k = k
        self.iterations = iterations

    def build_features(self, agents: List[Dict[str, Any]]) -> "np.ndarray":
        """[[vx, vy, x, y], ...] per agent."""
        return np.array(
            [[a.get("vx", 0.0), a.get("vy", 0.0), a.get("x", 0.0), a.get("y", 0.0)]
             for a in agents],
            dtype=float,
        )

    def _kmeans(self, X: "np.ndarray", k: int) -> tuple:  # type: ignore[valid-type]
        """Simple k-means (nearest-to-center, batch). Returns (labels, centers)."""
        n, d = X.shape
        if n == 0:
            return np.array([], dtype=int), np.zeros((0, d))
        k = max(1, min(k, n))
        rng = np.random.default_rng(0)
        centers = X[rng.choice(n, size=k, replace=False)].copy()
        labels = np.zeros(n, dtype=int)
        for _ in range(self.iterations):
            dist = ((X[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
            new_labels = np.argmin(dist, axis=1)
            for c in range(k):
                mask = new_labels == c
                if mask.any():
                    centers[c] = X[mask].mean(axis=0)
            if np.array_equal(new_labels, labels):
                break
            labels = new_labels
        return labels, centers

    def _cluster_intent(self, agents: List[Dict[str, Any]]) -> str:
        """Classify cluster behavior from aggregate position/velocity spread."""
        if len(agents) < 2:
            return "solo"
        xs = np.array([a.get("x", 0.0) for a in agents])
        ys = np.array([a.get("y", 0.0) for a in agents])
        vx = np.array([a.get("vx", 0.0) for a in agents])
        vy = np.array([a.get("vy", 0.0) for a in agents])
        spread = np.std(xs) + np.std(ys)
        speed = np.mean(np.sqrt(vx ** 2 + vy ** 2))
        mean_vx, mean_vy = np.mean(vx), np.mean(vy)
        # converging: tight cluster moving toward a common point
        if spread < 5.0 and speed > 1.0:
            return "converging"
        # escaping: large velocity variance → members scattering
        if np.std(vx) + np.std(vy) > 2.0:
            return "escaping"
        # unstable: fast but disordered
        if speed > 3.0:
            return "unstable"
        # drifting: slow consistent movement
        if speed > 0.5 and abs(mean_vx) + abs(mean_vy) > 0.1:
            return "drifting"
        return "stable"

    def detect(self, agents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Cluster agents and annotate each cluster with its collective intent."""
        if not agents:
            return {"clusters": [], "intents": {}}
        X = self.build_features(agents)
        labels, centers = self._kmeans(X, self.k)

        clusters: List[Dict[str, Any]] = []
        intents: Dict[str, List[Dict[str, Any]]] = {}
        for c in sorted(set(labels.tolist())):
            members = [agents[i] for i, l in enumerate(labels) if l == c]
            intent = self._cluster_intent(members)
            clusters.append({
                "cluster": int(c),
                "intent": intent,
                "size": len(members),
                "centroid": [round(float(v), 3) for v in centers[c].tolist()],
                "agents": [m.get("id", i) for i, m in enumerate(members)],
            })
            intents[intent] = intents.get(intent, []) + members
        return {"clusters": clusters, "intents": {k: len(v) for k, v in intents.items()}}
