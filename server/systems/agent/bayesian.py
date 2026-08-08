from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class BayesianReasoning:
    """
    Handles probabilistic belief updating.
    """
    
    def initial_prior(self) -> float:
        """Return neutral prior belief."""
        return 0.5

    def update_belief(self, prior: float, likelihood: float) -> float:
        """
        Standard Bayesian update: P(H|E) = P(E|H) * P(H) / (P(E|H)P(H) + P(E|~H)P(~H))
        Assume P(E|~H) = 1 - P(E|H) for simplicity.
        """
        # Numerical stability check
        prior = max(0.01, min(0.99, prior))
        likelihood = max(0.01, min(0.99, likelihood))
        
        numerator = likelihood * prior
        denominator = (likelihood * prior) + ((1 - likelihood) * (1 - prior))
        
        if denominator == 0:
            return prior
            
        return numerator / denominator

    def sequential_update(self, initial_prior: float, evidence_list: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process multiple pieces of evidence sequentially.
        Each evidence dict should have: 'strength' (0-1), 'direction' (-1, 0, 1).
        """
        belief = initial_prior
        trace = []
        
        for i, e in enumerate(evidence_list):
            strength = e.get("strength", 0.5)
            direction = e.get("direction", 1) # 1=supports, -1=contradicts, 0=neutral
            
            # Map strength to likelihood
            # If direction=1, likelihood=strength (if strength > 0.5)
            # If direction=-1, likelihood=1-strength
            if direction == 1:
                likelihood = 0.5 + (strength * 0.5)
            elif direction == -1:
                likelihood = 0.5 - (strength * 0.5)
            else:
                likelihood = 0.5
                
            old_belief = belief
            belief = self.update_belief(belief, likelihood)
            
            trace.append({
                "step": i,
                "evidence_id": e.get("id"),
                "prior": old_belief,
                "likelihood": likelihood,
                "posterior": belief,
                "delta": belief - old_belief
            })
            
        return {
            "final_belief": belief,
            "confidence": abs(belief - 0.5) * 2, # Scale to 0-1
            "trace": trace
        }

# Global instance
bayesian = BayesianReasoning()
