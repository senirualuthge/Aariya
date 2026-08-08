from typing import Dict, List, Set, Any
import logging

logger = logging.getLogger(__name__)

class TruthMaintenanceSystem:
    """
    Manages belief dependencies and consistency.
    Allows for retraction of facts when supporting evidence is invalidated.
    """
    
    def __init__(self):
        self.beliefs: Dict[str, float] = {}
        self.dependencies: Dict[str, Set[str]] = {}
        self.justifications: Dict[str, List[str]] = {}
        
    def add_belief(self, fact_id: str, confidence: float, dependencies: List[str] = []):
        """Register a new belief with dependencies."""
        self.beliefs[fact_id] = confidence
        self.dependencies[fact_id] = set(dependencies)
        
        # Reverse mapping: which facts depend on this dependency?
        for dep in dependencies:
            if dep not in self.justifications:
                self.justifications[dep] = []
            self.justifications[dep].append(fact_id)
            
    def retract_fact(self, fact_id: str):
        """
        Retract a fact and recursively retract all dependent beliefs.
        """
        if fact_id in self.beliefs:
            del self.beliefs[fact_id]
            logger.info(f"Retracted fact: {fact_id}")
            
            # Retract dependents
            if fact_id in self.justifications:
                for dependent in self.justifications[fact_id]:
                    self.retract_fact(dependent)
                    
    def get_belief(self, fact_id: str) -> float:
        return self.beliefs.get(fact_id, 0.0)

# Global instance
tms = TruthMaintenanceSystem()
