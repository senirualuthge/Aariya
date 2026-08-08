# server/systems/goal_generator.py
import random
from typing import Dict, List, Any

BASE_GOALS = [
    "increase system stability",
    "improve agent efficiency",
    "reduce latency",
    "expand capability coverage",
    "increase prediction accuracy"
]

def generate_goals(system_state: Dict[str, Any]) -> List[str]:
    """
    Autonomous Drive Layer: Core Engine.
    Generates dynamic goals based on current system conditions and entropy.
    Without this, the system is reactive. With this, it becomes self-directed.
    """
    goals = []

    # Stability-driven goal selection
    if system_state.get("error_rate", 0.0) > 0.1:
        goals.append("reduce system errors")

    # Performance-driven goal selection
    if system_state.get("latency", 0) > 200:
        goals.append("optimize execution speed")

    # Exploration (Curiosity) - ensures the system never stagnates
    goals.append(random.choice(BASE_GOALS))

    return goals

def curiosity_signal(state: Dict[str, Any]) -> float:
    """
    Low entropy = boredom -> exploration triggers.
    Forces the system to branch out rather than loop over optimal safe tasks.
    """
    return 1.0 - state.get("system_entropy", 1.0)
