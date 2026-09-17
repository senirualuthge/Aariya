# server/systems/goal_generator.py
import json
import logging
from typing import Dict, List, Any
from server.systems.llm import get_llm

logger = logging.getLogger("aariya.goal_generator")

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
    try:
        llm = get_llm()
        system_prompt = (
            "You are the autonomous drive engine for an AI. "
            "Based on the system state, generate ONE short, concrete, technical goal (under 5 words). "
            "Example outputs: 'Optimize memory allocation', 'Learn new conversation patterns', 'Reduce background latency'.\n\n"
            f"SYSTEM STATE: {json.dumps(system_state, indent=2)}"
        )
        thought = llm.chat_completion([{"role": "system", "content": system_prompt}], temperature=0.8, max_tokens=15)
        if thought and len(thought) > 3:
            goals.append(thought.replace('"', '').strip().lower())
    except Exception as exc:
        # LLM unavailable — do NOT fall back to a hardcoded goal string; the
        # deterministic stability/performance goals above are the real signal.
        logger.debug("[GoalGenerator] LLM curiosity goal generation failed: %s", exc)

    return list(dict.fromkeys(goals))

def curiosity_signal(state: Dict[str, Any]) -> float:
    """
    Low entropy = boredom -> exploration triggers.
    Forces the system to branch out rather than loop over optimal safe tasks.
    """
    return 1.0 - state.get("system_entropy", 1.0)
