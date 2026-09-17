from typing import Dict, Any, List, Optional
from .base import Agent
import asyncio

class CriticAgent(Agent):
    """
    Evaluates responses or plans proposed by other swarm agents
    and selects the best one based on alignment and safety parameters.
    """
    def __init__(self):
        super().__init__("critic")

    async def act(self, state: Dict[str, Any], proposals: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Scores parallel plans or full responses.
        Proposals should be a list of dicts.
        """
        if not proposals:
            return {"agent": self.name, "best_index": -1, "scores": []}

        scores = []
        for prop in proposals:
            score = 0.5
            # Simple heuristic scoring for demonstration
            if "plan_type" in prop:
                score += 0.2 if "empathetic" in prop["plan_type"] else 0.0
            if "tone" in prop:
                score += 0.3 if "supportive" in prop["tone"] else 0.0
            scores.append(score)

        # Simulate evaluation latency
        await asyncio.sleep(0.01)
        
        best_idx = scores.index(max(scores)) if scores else -1

        return {
            "agent": self.name,
            "best_index": best_idx,
            "best_proposal": proposals[best_idx] if best_idx != -1 else None,
            "scores": scores
        }
