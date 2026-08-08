import numpy as np
from collections import defaultdict

class AgentMetrics:
    def __init__(self):
        self.calls = defaultdict(int)
        self.errors = defaultdict(int)
        self.latency = defaultdict(list)

    def record_call(self, name: str, latency: float, success: bool = True):
        self.calls[name] += 1
        self.latency[name].append(latency)
        if not success:
            self.errors[name] += 1

metrics = AgentMetrics()

def compute_score(name: str) -> float:
    """
    Computes a fitness score (0-1) for an agent based on usage, errors, and latency.
    Employs a stable exponential decay model to prevent wild swings.
    """
    calls = metrics.calls[name]
    errors = metrics.errors[name]
    latencies = metrics.latency[name]

    if calls < 5:
        return 0.5  # Neutral baseline for new agents with low data

    error_rate = errors / calls
    avg_latency = np.mean(latencies) if latencies else 1000

    # Stability: drops off exponentially as error rate increases
    stability = np.exp(-error_rate * 5)
    
    # Speed: sweet spot is < 500ms
    speed = np.exp(-avg_latency / 800)

    # Usefulness: diminishing returns on spam calls
    usefulness = np.log1p(calls) / 10

    # Consistency penalty
    volatility_penalty = np.std(latencies) / 1000 if len(latencies) > 1 else 0

    score = (
        0.4 * stability +
        0.3 * speed +
        0.2 * usefulness -
        0.1 * volatility_penalty
    )

    return float(np.clip(score, 0.0, 1.0))

def classify_state(score: float) -> str:
    """Classifies an agent's lifecycle state based on its current core."""
    if score >= 0.75:
        return "ACTIVE"
    elif score >= 0.5:
        return "WEAK"
    elif score >= 0.3:
        return "DEGRADED"
    else:
        return "REWRITE"
