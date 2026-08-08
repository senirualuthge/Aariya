from typing import Dict, Any
import time
import logging

logger = logging.getLogger(__name__)

class BoundedRationalityController:
    """
    Manages computational resources and stops reasoning when cost exceeds benefit.
    """
    
    def __init__(self):
        self.start_time = 0
        self.budget_ms = 2000 # 2 seconds default
        
    def start_task(self, budget_ms: int = 2000):
        self.start_time = time.time()
        self.budget_ms = budget_ms
        
    def should_continue(self) -> bool:
        """Check if time budget allows continuing."""
        elapsed = (time.time() - self.start_time) * 1000
        return elapsed < self.budget_ms
        
    def check_marginal_utility(self, current_confidence: float, step_cost: float) -> bool:
        """
        Decide to stop if expected gain in confidence is low.
        """
        # Simple heuristic: if confidence is already high (>0.9), stop
        if current_confidence > 0.9:
            return False
        return True

# Global instance
resource_controller = BoundedRationalityController()
