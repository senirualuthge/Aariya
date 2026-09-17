"""
anomaly_detector.py — swarm/synoptic anomaly detection (Agents Swarm Visualize doc §219-223).

Implements the core detection methods that make the system "smart, not just
predictive":

    §220 Statistical Deviation     z = (x - μ) / σ, flag if |z| > threshold
    §223 Temporal Surprise Index   surprise = -log P(state_t | state_{t-1})
    §222 Graph Anomaly Score       A(G) = Δ centrality + Δ clustering + Δ entropy

Also a light structural/velocity anomaly pass over per-domain activations
(velocity spike / sentiment inversion / loss of diversity) so it can run on
the synoptic pipeline's own data without a full graph engine.
"""

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

EPSILON = 1e-9


@dataclass
class Anomaly:
    type: str          # e.g. "velocity_spike", "temporal_surprise", "entropy_collapse"
    severity: float    # 0–1
    location: str      # domain / region / node label
    cause: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type, "severity": round(self.severity, 4), "location": self.location, "cause": self.cause}


class AnomalyDetector:
    """Stateful anomaly detection over the synoptic domain stream."""

    def __init__(self, z_threshold: float = 2.0, surprise_floor: float = 1.0,
                 history_size: int = 50):
        self.z_threshold = z_threshold
        self.surprise_floor = surprise_floor
        self.history: deque = deque(maxlen=history_size)
        self.last_state: Optional[Dict[str, float]] = None

    # ── §220 Statistical deviation (per-domain z-score) ──────────────────────
    def statistical_deviation(self, state: Dict[str, float]) -> List[Anomaly]:
        if not self.history:
            return []
        anomalies: List[Anomaly] = []
        for k, v in state.items():
            vals = [s.get(k, 0.0) for s in self.history]
            mu = sum(vals) / len(vals)
            var = sum((x - mu) ** 2 for x in vals) / len(vals)
            sigma = math.sqrt(var + EPSILON)
            z = (v - mu) / sigma
            if abs(z) > self.z_threshold:
                anomalies.append(Anomaly(
                    type="statistical_deviation",
                    severity=min(1.0, abs(z) / (self.z_threshold * 2)),
                    location=k,
                    cause=f"z={z:.2f} beyond threshold {self.z_threshold}",
                ))
        return anomalies

    # ── §223 Temporal surprise index ─────────────────────────────────────────
    def temporal_surprise(self, state: Dict[str, float]) -> List[Anomaly]:
        """surprise = -log P(state_t | state_{t-1}) — modeled as normalized
        Euclidean jump under a Gaussian prior over domain deltas."""
        prev = self.last_state
        if not prev:
            return []
        anomalies: List[Anomaly] = []
        for k, v in state.items():
            prev_v = prev.get(k, 0.0)
            delta = v - prev_v
            if abs(delta) > EPSILON:
                # p(delta) ~ exp(-delta^2/2) → surprise = delta^2 / 2
                surprise = (delta * delta) / 2.0
                if surprise > self.surprise_floor:
                    anomalies.append(Anomaly(
                        type="temporal_surprise",
                        severity=min(1.0, surprise / (self.surprise_floor * 2)),
                        location=k,
                        cause=f"delta={delta:+.3f}, surprise={surprise:.2f}",
                    ))
        return anomalies

    # ── §222 Graph anomaly score (simplified, no graph engine needed) ────────
    @staticmethod
    def graph_anomaly_score(state: Dict[str, float]) -> List[Anomaly]:
        """Entropy-collapse / diversity-loss detection over the domain
        distribution (proxy for network-entropy collapse in §B structural
        anomaly)."""
        vals = list(state.values())
        total = sum(vals) + EPSILON
        probs = [v / total for v in vals]
        entropy = -sum(p * math.log(p + EPSILON) for p in probs)
        max_entropy = math.log(len(vals) + 1) + EPSILON
        normalized = entropy / max_entropy
        anomalies: List[Anomaly] = []
        if normalized < 0.3:
            anomalies.append(Anomaly(
                type="entropy_collapse",
                severity=round(1.0 - normalized, 4),
                location="swarm",
                cause=f"entropy={normalized:.2f} → loss of expected diversity",
            ))
        return anomalies

    # ── Behavioral velocity spike (§A) ───────────────────────────────────────
    @staticmethod
    def velocity_spike(velocity: Dict[str, float], spike_threshold: float = 0.4) -> List[Anomaly]:
        anomalies: List[Anomaly] = []
        for k, v in (velocity or {}).items():
            if abs(v) > spike_threshold:
                anomalies.append(Anomaly(
                    type="velocity_spike",
                    severity=min(1.0, abs(v)),
                    location=k,
                    cause=f"|v|={abs(v):.3f} > {spike_threshold}",
                ))
        return anomalies

    # ── Combined pass ────────────────────────────────────────────────────────
    def detect(self, state: Dict[str, float],
               velocity: Optional[Dict[str, float]] = None) -> List[Anomaly]:
        """Run all methods over a synoptic domain snapshot. Records state for
        the next frame's surprise computation."""
        anomalies: List[Anomaly] = []
        anomalies += self.statistical_deviation(state)
        anomalies += self.temporal_surprise(state)
        anomalies += self.graph_anomaly_score(state)
        if velocity is not None:
            anomalies += self.velocity_spike(velocity)

        self.history.append(dict(state))
        self.last_state = dict(state)
        return anomalies

    def snapshot(self) -> Dict[str, Any]:
        return {
            "anomalies": [a.to_dict() for a in self.detect(self.last_state or {})],
            "z_threshold": self.z_threshold,
            "surprise_floor": self.surprise_floor,
        }
