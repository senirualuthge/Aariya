from typing import Dict, Any
from .base import Agent
import asyncio

class EmotionAgent(Agent):
    """
    Handles internal emotional regulation and tone selection for responses.
    """
    def __init__(self):
        super().__init__("emotion")

    async def act(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluates the context and sets the ideal emotional tone payload.
        """
        valence = state.get("perception_data", {}).get("valence", 0.0)
        
        tone = "neutral"
        if valence > 0.4:
            tone = "warm_and_playful"
        elif valence < -0.3:
            tone = "soft_and_supportive"

        # Simulate async reasoning latency
        await asyncio.sleep(0.01)

        return {
            "agent": self.name,
            "tone": tone,
            "valence_target": valence * 0.8  # Mirroring user valence slightly
        }
