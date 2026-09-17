import math
from typing import Dict, List, Any
from dataclasses import dataclass, field
import time

from server.systems.synoptic_smoother import SynopticSmoother

# Agent-level key → synoptic domain (raw agent activations get folded in).
DOMAIN_MAP = {
    "emotion": ["emotion_agent", "emotion"],
    "reasoning": ["planner", "planner_agent", "critic", "reasoning_agent"],
    "memory": ["memory_agent", "memory"],
    "risk": ["risk_agent", "risk_engine", "guard_agent"],
    "perception": ["vision", "vision_agent", "perception"],
}

@dataclass
class SynopticState:
    domains: Dict[str, float] = field(default_factory=lambda: {
        "emotion": 0.0,
        "reasoning": 0.0,
        "memory": 0.0,
        "risk": 0.0,
        "perception": 0.0
    })
    dominant_domain: str = "reasoning"
    coherence: float = 1.0  # 1.0 = stable, 0.0 = chaos
    conflict: float = 0.0
    velocity: Dict[str, float] = field(default_factory=dict)

class SynopticAggregator:
    def __init__(self):
        self.state = SynopticState()
        self.smoother = SynopticSmoother(alpha=0.15)
        # For EMA smoothing
        self.smoothed_domains = {
            "emotion": 0.1,
            "reasoning": 0.1,
            "memory": 0.1,
            "risk": 0.1,
            "perception": 0.1
        }
        self.alpha = 0.15  # Smoothing factor: lower is smoother, higher is more responsive
        
        # Base colors from frontend mapping
        self.domain_colors = {
            "emotion": "#ff6b9d",
            "reasoning": "#00d2ff",
            "memory": "#9d6bff",
            "risk": "#ffcc00",
            "perception": "#2ecc71"
        }

    def _fold_agent_activations(self, activations: Dict[str, float]) -> Dict[str, float]:
        """Fold raw agent-level keys into domain-level values via DOMAIN_MAP.
        Domain keys passed directly win over folded agent scores."""
        folded: Dict[str, float] = {}
        domain_scores: Dict[str, float] = {}
        for domain, members in DOMAIN_MAP.items():
            scores = [activations.get(m, 0.0) for m in members if m in activations]
            domain_scores[domain] = max(scores) if scores else 0.0
        for k, v in activations.items():
            if k in DOMAIN_MAP:
                folded[k] = float(v)
        for domain, score in domain_scores.items():
            folded.setdefault(domain, score)
        return folded

    def aggregate_synoptic(self, agent_activations: Dict[str, float]) -> SynopticState:
        """
        Maps raw agent activations -> High level domains
        Accepts either domain-level keys (emotion/reasoning/memory/risk/
        perception) or agent-level keys (planner, critic, vision, ...) which
        are folded through DOMAIN_MAP.
        """
        normalized = self._fold_agent_activations(agent_activations or {})

        # Apply EMA smoothing to incoming activations
        for key in self.smoothed_domains:
            incoming_val = normalized.get(key, 0.0)
            self.smoothed_domains[key] = (self.alpha * incoming_val) + ((1 - self.alpha) * self.smoothed_domains[key])
        
        self.state.domains = dict(self.smoothed_domains)
        # Velocity tracking for the frontend's predictive easing.
        self.smoother.smooth(self.state.domains)
        self.state.velocity = self.smoother.snapshot()["velocity"]

        # Calculate dominant domain
        max_domain = max(self.state.domains.items(), key=lambda x: x[1])
        self.state.dominant_domain = max_domain[0]

        # Calculate coherence (inverse variance of active domains - simplified heuristic)
        active_vals = [v for v in self.state.domains.values() if v > 0.1]
        if active_vals:
            avg = sum(active_vals) / len(active_vals)
            variance = sum((v - avg)**2 for v in active_vals) / len(active_vals)
            # High variance = lower coherence
            self.state.coherence = max(0.0, min(1.0, 1.0 - math.sqrt(variance) * 1.5))
            
            # Conflict is high if multiple domains have high activation + low coherence
            top_two = sorted(active_vals, reverse=True)[:2]
            if len(top_two) == 2 and top_two[0] > 0.5 and top_two[1] > 0.5:
                # E.g. Reason and Emotion both high
                self.state.conflict = min(1.0, (top_two[0] + top_two[1]) / 2.0 * (1.0 - self.state.coherence))
            else:
                self.state.conflict = max(0.0, self.state.conflict - 0.1) # decay
        else:
            self.state.coherence = 1.0
            self.state.conflict = 0.0

        return self.state

    def synoptic_to_planets(self, state: SynopticState) -> List[dict]:
        """
        Converts the synoptic state to orbital visualization data.
        Returns a list of dicts that match the PlanetData shape for React.
        """
        planets = []
        for domain, activation in state.domains.items():
            base_radius = 0.25
            is_dominant = (domain == state.dominant_domain)
            
            # Calculate planet parameters driven by state
            radius = base_radius + (activation * 0.4) 
            glow = 1.5 if is_dominant else (activation * 0.8)
            
            # Agitation affects orbit speed
            base_speed = 0.3
            speed_multiplier = 1.0 + (activation * 1.5) + (state.conflict * 2.0)
            
            p = {
                "id": domain,
                "name": domain.capitalize(),
                "radius": radius,
                "orbit_speed": base_speed * speed_multiplier,
                "glow": glow,
                "color": self.domain_colors.get(domain, "#ffffff"),
                "activation": activation
            }
            planets.append(p)
            
        return planets
