from typing import Dict, Any
from .base import Agent
import asyncio

class PlannerAgent(Agent):
    """
    Decides the strategic direction and structure of the conversation
    before generating the exact text.
    """
    def __init__(self):
        super().__init__("planner")

    async def act(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        Takes the current brain state and outputs a high-level conversational plan.
        """
        user_intent = state.get("user_model", {}).get("intent", "chatting")
        trust_level = state.get("trust", 0.5)
        
        # Simplified planning logic for Swarm integration
        plan_type = "maintain_flow"
        if user_intent == "seeking_support":
            plan_type = "empathetic_validation"
        elif user_intent == "challenging_ai":
            plan_type = "firm_deescalation"
        elif trust_level < 0.3:
            plan_type = "build_rapport_safely"

        # Simulate async LLM/planning latency
        await asyncio.sleep(0.01)

        return {
            "agent": self.name,
            "plan_type": plan_type,
            "directive": f"Proceed with {plan_type} strategies."
        }
