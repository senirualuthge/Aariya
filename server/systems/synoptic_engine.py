"""
synoptic_engine.py — orchestration of the full synoptic pipeline.

Doc (Agents Swarm Visualize §208-215):

    aggregate → smooth → velocity → narrative shock → combine
    → normalize → cognitive influence → metrics (+ trend)

Produces the "synoptic v2" payload:

    {
      "domains": {...},            # influenced, normalized
      "dominant": str,
      "coherence": float,
      "conflict": float,
      "trend": {...}               # per-domain velocity (for predictive orbit)
      "shock": {...}               # narrative shock effects folded in
      "predicted": {...}           # one-step velocity forecast (ghost layer)
    }

`SynopticEngine` is stateful: it owns the EMA smoother + velocity tracker so
frame-to-frame signals stay stable across calls.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from server.systems.synoptic_aggregator import SynopticAggregator, SynopticState
from server.systems.cognitive_field import (
    apply_cognitive_influence,
    predict_domains,
)
from server.systems.synoptic_smoother import SynopticSmoother

EPSILON = 1e-6


@dataclass
class SynopticDynamics:
    """Velocity tracker — v(t) = x(t) - x(t-1) per domain (doc §166B)."""
    prev: Dict[str, float] = field(default_factory=dict)
    velocity: Dict[str, float] = field(default_factory=dict)
    prev_velocity: Dict[str, float] = field(default_factory=dict)

    def update(self, current: Dict[str, float]) -> Dict[str, float]:
        vel = {}
        for k, v in current.items():
            prev_v = self.prev.get(k, v)
            vel[k] = v - prev_v
        self.prev_velocity = self.velocity
        self.velocity = vel
        self.prev = dict(current)
        return vel

    def acceleration(self) -> Dict[str, float]:
        """Second difference — acceleration a(k) = v(k) - v(k-1) (doc §215)."""
        acc = {}
        for k, v in self.velocity.items():
            prev_v = self.prev_velocity.get(k, v)
            acc[k] = v - prev_v
        return acc


class SynopticEngine:
    """Stateful orchestration layer that consumes a swarm turn → synoptic v2."""

    def __init__(self, aggregator: Optional[SynopticAggregator] = None,
                 smoother: Optional[SynopticSmoother] = None,
                 dynamics: Optional[SynopticDynamics] = None,
                 narrative_engine: Optional[Any] = None,
                 arcs: Optional[Any] = None):
        self.aggregator = aggregator or SynopticAggregator()
        self.smoother = smoother or SynopticSmoother(alpha=0.2)
        self.dynamics = dynamics or SynopticDynamics()
        self.narrative_engine = narrative_engine
        self.arcs = arcs

    def compute_synoptic(self, swarm_activations: Dict[str, float],
                         narrative_engine: Optional[Any] = None,
                         arcs: Optional[Any] = None) -> Dict[str, Any]:
        """
        Full pipeline per doc §208-215. Accepts either domain-level keys or
        agent-level keys (aggregator folds via DOMAIN_MAP).
        """
        narrative_engine = narrative_engine or self.narrative_engine
        arcs = arcs or self.arcs

        # 1. base aggregation (fold agent keys → domains)
        base_state = self.aggregator.aggregate_synoptic(swarm_activations)
        base_domains = dict(base_state.domains)

        # 2. temporal smoothing (EMA with inertia)
        smoothed = self.smoother.smooth(base_domains)

        # 3. velocity tracking (for prediction)
        velocity = self.dynamics.update(smoothed)

        # 4. narrative shock — fold decaying event effects into domains
        shock: Dict[str, float] = {}
        if narrative_engine is not None:
            try:
                shock = narrative_engine.compute_shock() or {}
            except TypeError:
                shock = {}
        # Cap total shock (doc §174: shock_total = min(1.5, sum(domain_effects)))
        shock_total = sum(shock.values())
        if shock_total > 1.5:
            scale = 1.5 / shock_total
            shock = {k: v * scale for k, v in shock.items()}
        combined = {
            k: smoothed.get(k, 0.0) + shock.get(k, 0.0)
            for k in smoothed
        }

        # 5. normalize
        total = sum(combined.values()) + EPSILON
        normalized = {k: max(0.0, v) / total for k, v in combined.items()}

        # 6. cognitive influence layer
        influenced = apply_cognitive_influence(normalized)

        # 7. metrics + trend
        dominant = max(influenced, key=influenced.get)  # type: ignore[arg-type]
        coherence = max(influenced.values())
        vals = sorted(influenced.values(), reverse=True)
        conflict = vals[1] / (vals[0] + EPSILON) if len(vals) > 1 else 0.0

        acceleration = self.dynamics.acceleration()
        # Trend aggregates (doc §215: direction + velocity + acceleration).
        # direction = sign of net velocity; velocity = mean |v|; acceleration = mean |a|.
        vel_vals = list(velocity.values())
        acc_vals = list(acceleration.values())
        trend_meta = {
            "direction": "rising" if sum(vel_vals) > 0 else ("falling" if sum(vel_vals) < 0 else "stable"),
            "velocity": round(float(sum(vel_vals)) / max(1, len(vel_vals)), 4),
            "acceleration": round(float(sum(acc_vals)) / max(1, len(acc_vals)), 4),
        }

        return {
            "domains": {k: round(v, 4) for k, v in influenced.items()},
            "dominant": dominant,
            "coherence": round(coherence, 4),
            "conflict": round(conflict, 4),
            "trend": {k: round(v, 4) for k, v in velocity.items()},
            "trend_meta": trend_meta,
            "acceleration": {k: round(v, 4) for k, v in acceleration.items()},
            "shock": {k: round(v, 4) for k, v in shock.items()},
            "predicted": {k: round(v, 4) for k, v in predict_domains(influenced, velocity).items()},
            "timestamp": time.time(),
        }

    def to_planets(self, synoptic: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Map synoptic v2 → orbital planet payloads (size/glow/speed/velocity)."""
        planets = []
        domains = synoptic.get("domains", {})
        trend = synoptic.get("trend", {})
        dominant = synoptic.get("dominant")
        for name, value in domains.items():
            is_dominant = (name == dominant)
            planets.append({
                "id": name,
                "name": name.capitalize(),
                "radius": 0.25 + value * 0.4,
                "mass": round(value ** 2, 4),
                "orbit_speed": round(0.2 + value, 4),
                "glow": 1.5 if is_dominant else value * 0.8,
                "velocity": trend.get(name, 0.0),
                "color": self.aggregator.domain_colors.get(name, "#ffffff"),
                "activation": round(value, 4),
            })
        return planets
