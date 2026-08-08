from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)

class MetaTrustSystem:
    """
    Calibrates trust in agents and domains based on historical performance.
    """
    
    def __init__(self):
        self.domain_trust: Dict[str, float] = {}
        self.agent_trust: Dict[str, float] = {}
        
    def update_trust(self, entity_id: str, success: bool):
        """
        Update trust score using simple reinforcement.
        """
        current = self.domain_trust.get(entity_id, 0.5)
        alpha = 0.1
        
        if success:
            new_trust = current + alpha * (1.0 - current)
        else:
            new_trust = current - alpha * current
            
        self.domain_trust[entity_id] = max(min(new_trust, 1.0), 0.0)
        
    def get_trust(self, entity_id: str) -> float:
        return self.domain_trust.get(entity_id, 0.5)

# Global instance
meta_trust = MetaTrustSystem()
