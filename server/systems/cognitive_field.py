"""
cognitive_field.py — inter-domain cognitive influence (Agents Swarm Visualize doc).

Implements the "Cognitive Field" layer:
  * INFLUENCE_MATRIX      — how much each domain pushes/pulls its neighbors
                            (strong emotion suppresses reasoning clarity, etc.)
  * apply_cognitive_influence(domains)
                          — applies the matrix, then re-normalizes to [0..1]
  * predict_domains(domains, velocity)
                          — short-horizon domain forecast from current state
                            + velocity (x(t+1) = x(t) + v(t)), clamped.
"""

from typing import Dict

INFLUENCE_MATRIX: Dict[str, Dict[str, float]] = {
    "emotion": {
        "reasoning": -0.3,   # strong emotion reduces reasoning clarity
        "memory": 0.2,
        "risk": 0.4,
        "personality": 0.3,
    },
    "reasoning": {
        "emotion": -0.2,
        "risk": 0.3,
        "memory": 0.4,
    },
    "memory": {
        "emotion": 0.3,
        "reasoning": 0.2,
    },
    "risk": {
        "emotion": 0.5,
        "reasoning": -0.3,
    },
    "personality": {
        "emotion": 0.4,
        "reasoning": 0.2,
    },
}

EPSILON = 1e-6


def apply_cognitive_influence(domains: Dict[str, float]) -> Dict[str, float]:
    """
    Propagate influence between domains, then clamp negatives and normalize
    so the result stays a valid probability-ish distribution over domains.
    """
    updated = dict(domains)

    for source, targets in INFLUENCE_MATRIX.items():
        source_val = domains.get(source, 0.0)
        for target, weight in targets.items():
            updated[target] = updated.get(target, 0.0) + source_val * weight

    # Clamp negatives (negative activation is meaningless) then normalize.
    total = sum(max(0.0, v) for v in updated.values()) + EPSILON
    normalized = {k: max(0.0, v) / total for k, v in updated.items()}
    return normalized


def predict_domains(domains: Dict[str, float], velocity: Dict[str, float],
                    horizon: float = 0.3) -> Dict[str, float]:
    """
    x(t+horizon) = x(t) + v(t) * horizon, clamped to [0, 1]. Used for the
    predictive ghost layer / orbit forecasting (doc §168: predicted =
    current + velocity * horizon). `velocity` is the SynopticDynamics output.
    """
    predicted = {}
    for k, v in domains.items():
        vv = velocity.get(k, 0.0)
        predicted[k] = max(0.0, min(1.0, v + vv * horizon))
    return predicted
