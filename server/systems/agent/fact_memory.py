import json
import os
import logging
from typing import Dict, Any
from server.systems.agent.config import config

logger = logging.getLogger(__name__)

class FactMemory:
    """
    Manages long-term storage and reinforcement of facts.
    Implements simple reinforcement learning for belief updates.
    """
    
    def __init__(self):
        self.path = config.FACT_MEMORY_PATH
        self.facts: Dict[str, Dict[str, Any]] = {}
        self._load()
        
    def update_fact(self, fact_id: str, new_confidence: float):
        """
        Update belief using exponential moving average (reinforcement).
        """
        if fact_id not in self.facts:
            self.facts[fact_id] = {
                "confidence": new_confidence,
                "count": 1,
                "last_updated": "now" # TODO: Implement timestamp
            }
        else:
            # Reinforcement learning update
            alpha = 0.2
            old_conf = self.facts[fact_id]["confidence"]
            self.facts[fact_id]["confidence"] = old_conf + alpha * (new_confidence - old_conf)
            self.facts[fact_id]["count"] += 1
            
        self._save()
        
    def get_confidence(self, fact_id: str) -> float:
        return self.facts.get(fact_id, {}).get("confidence", 0.5)

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, 'w') as f:
                json.dump(self.facts, f)
        except Exception as e:
            logger.error(f"Failed to save fact memory: {e}")

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r') as f:
                    self.facts = json.load(f)
            except Exception as e:
                logger.error(f"Failed to load fact memory: {e}")

# Global instance
fact_memory = FactMemory()
