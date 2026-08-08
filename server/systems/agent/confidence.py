from typing import List, Dict, Any
import math
import logging

logger = logging.getLogger(__name__)

class ConfidenceCalculator:
    """
    Calculates epistemic uncertainty and overall confidence.
    """
    
    def compute_confidence(self, evidence_list: List[Dict[str, Any]], contradictions: List[Any] = []) -> float:
        """
        Compute aggregate confidence score (0.0 - 1.0).
        Considers source credibility, evidence volume, and contradictions.
        """
        if not evidence_list:
            return 0.0
            
        # 1. Average Credibility
        avg_credibility = sum(e.get("credibility_score", 0.5) for e in evidence_list) / len(evidence_list)
        
        # 2. Contradiction Penalty
        penalty = 0.3 if contradictions else 0.0
        
        # 3. Source Diversity Boost (up to +0.2)
        unique_domains = len(set(e.get("domain", "") for e in evidence_list))
        diversity_boost = min(unique_domains * 0.05, 0.2)
        
        raw_score = avg_credibility + diversity_boost - penalty
        return max(min(raw_score, 1.0), 0.0)

    def epistemic_uncertainty(self, p: float) -> float:
        """
        Calculate entropy-based uncertainty.
        High when p ~ 0.5, Low when p -> 0 or 1.
        """
        if p <= 0 or p >= 1:
            return 0.0
        return -p * math.log(p) - (1-p) * math.log(1-p)

# Global instance
confidence = ConfidenceCalculator()
