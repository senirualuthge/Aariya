import logging
from typing import List, Dict, Any, Tuple
import time

logger = logging.getLogger(__name__)

class RAGArena:
    """
    The RAGArena pits different search strategies against each other.
    It evaluates the retrieval results of each strategy based on recall, 
    context density, and credibility, then selects the 'winning' strategy.
    """
    
    def __init__(self):
        pass
        
    def evaluate_strategies(self, strategies_results: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Takes a list of strategy results and ranks them.
        
        Expected structure for each strategy result:
        {
            "strategy": "...",
            "query": "...",
            "findings": [...],
            "evidence": [...],
            "latency": 0.0
        }
        
        Returns:
            Tuple of (Winning Strategy Result, Ranked List of All Results)
        """
        
        if not strategies_results:
            raise ValueError("No strategies provided for evaluation.")
            
        ranked_results = []
        
        for result in strategies_results:
            findings = result.get("findings", [])
            
            # Simple metrics
            num_findings = len(findings)
            
            # Context density/Recall proxy: How much quote text did we get?
            total_quote_chars = sum(len(f.get("quote", "")) for f in findings)
            
            # Credibility: Average credibility of findings
            avg_credibility = 0.0
            if findings:
                credibilities = [f.get("credibility", 0.0) for f in findings if isinstance(f.get("credibility"), (int, float))]
                if credibilities:
                    avg_credibility = sum(credibilities) / len(credibilities)
            
            # Combine into a single score
            # Weighting: 40% credibility, 40% context volume, 20% finding count
            # Normalize volume (arbitrary cap at 5000 chars for scoring)
            volume_score = min(total_quote_chars / 5000.0, 1.0)
            
            # Normalize finding count (arbitrary cap at 10)
            count_score = min(num_findings / 10.0, 1.0)
            
            final_score = (avg_credibility * 0.4) + (volume_score * 0.4) + (count_score * 0.2)
            
            result["arena_metrics"] = {
                "score": final_score,
                "num_findings": num_findings,
                "avg_credibility": avg_credibility,
                "total_quote_chars": total_quote_chars
            }
            
            ranked_results.append(result)
            
        # Sort descending by score
        ranked_results.sort(key=lambda x: x["arena_metrics"]["score"], reverse=True)
        
        winning_strategy = ranked_results[0]
        
        logger.info(f"Arena complete. Winner: {winning_strategy.get('strategy', 'Unknown')} with score {winning_strategy['arena_metrics']['score']:.2f}")
        
        return winning_strategy, ranked_results

# Singleton
_arena = None
def get_rag_arena() -> RAGArena:
    global _arena
    if _arena is None:
        _arena = RAGArena()
    return _arena
