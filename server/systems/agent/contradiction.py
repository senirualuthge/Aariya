from typing import List, Dict, Any, Optional
import logging
import json
from server.systems.llm import LLMEngine

logger = logging.getLogger(__name__)

class ContradictionDetector:
    """
    Detects contradictions in evidence and temporal claims.
    """
    
    def __init__(self, llm: Optional[LLMEngine] = None):
        self.llm = llm or LLMEngine()

    def detect_conflicts(self, claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Identify conflicting claims in evidence by comparing facts and values.
        """
        if len(claims) < 2:
            return []
            
        system_prompt = """
        You are a logical consistency auditor. 
        Compare the following list of extracted claims/facts.
        Identify any direct contradictions (e.g., A says X is True, B says X is False).
        Return ONLY a JSON list of conflict objects.
        
        Conflict Object:
        {
            "fact": "topic of conflict",
            "conflict_type": "binary | temporal | numeric",
            "claims": [{"source": "...", "value": "..."}, ...],
            "severity": 0.0-1.0
        }
        """
        
        try:
            response = self.llm.chat_completion([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Claims: {json.dumps(claims)}"}
            ], temperature=0.1)
            
            # Clean and parse JSON
            json_str = response.replace("```json", "").replace("```", "").strip()
            conflicts = json.loads(json_str)
            
            if isinstance(conflicts, list):
                return conflicts
            return []
        except Exception as e:
            logger.error(f"Contradiction detection failed: {e}")
            return []

    def check_temporal_consistency(self, claims: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Check for timeline errors using extraction and logic.
        """
        # Logic delegate to temporal module but can add LLM validation here
        return []

# Global instance
contradiction = ContradictionDetector()
