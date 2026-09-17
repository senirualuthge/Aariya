from typing import List, Dict, Any, Optional
import json
import logging
from server.systems.llm import LLMEngine

logger = logging.getLogger(__name__)

class QueryRewriter:
    """
    Takes an initial base query and geometrically expands it using
    the LLMEngine into multiple distinct search strategies to maximize coverage.
    """
    
    def __init__(self, llm: Optional[LLMEngine] = None):
        self.llm = llm or LLMEngine()
        
    async def generate_strategies(self, base_query: str, num_strategies: int = 3) -> List[Dict[str, str]]:
        """
        Generate diverse search strategies. Returns a list like:
        [
          {"strategy_type": "semantic", "query": "..."},
          ...
        ]
        """
        prompt = f"""
        You are a seasoned research architect. The user is asking: "{base_query}"
        
        We need to thoroughly search our knowledge graph / RAG system to answer this.
        Generate exactly {num_strategies} highly diverse search strategies/queries to maximize information retrieval.
        
        Strategy types:
        1. "broad_semantic" (cover the conceptual landscape)
        2. "keyword_extraction" (dense noun-phrases, technical terms)
        3. "adversarial" or "edge_case" (questions that challenge the premise or explore counter-points)
        
        Return ONLY valid JSON in this exact format, no markdown wrapping, no codeblocks:
        [
          {{"strategy": "broad_semantic", "query": "..."}},
          {{"strategy": "keyword", "query": "..."}}
        ]
        """
        
        try:
            # We use temperature=0.7 for creativity in strategy generation
            response = self.llm.chat_completion([
                {"role": "system", "content": "You are a master of information retrieval."},
                {"role": "user", "content": prompt}
            ], temperature=0.7)
            
            # Clean possible markdown
            clean_json = response.replace("```json", "").replace("```", "").strip()
            strategies = json.loads(clean_json)
            
            # Ensure it's a list
            if isinstance(strategies, dict):
                strategies = [strategies]
            
            # Fallback if generation fails
            if not strategies:
                raise ValueError("Empty strategy list generated.")
            
            return strategies[:num_strategies]
            
        except Exception as e:
            logger.warning(f"QueryRewrite failed: {e}. Falling back to default query.")
            return [{"strategy": "base", "query": base_query}]

# Singleton instance
_rewriter = None
def get_query_rewriter() -> QueryRewriter:
    global _rewriter
    if _rewriter is None:
        _rewriter = QueryRewriter()
    return _rewriter
