from typing import List, Dict, Any, Optional
import json
import logging
from server.systems.agent.config import config
from server.systems.agent.web_intelligence import web_intel
from server.systems.agent.retriever import get_retriever
from server.systems.llm import LLMEngine

logger = logging.getLogger(__name__)

class MultiHopReasoning:
    """
    Handles complex query decomposition and multi-step reasoning.
    """
    
    def __init__(self, llm: Optional[LLMEngine] = None):
        self.llm = llm or LLMEngine()
        self.retriever = get_retriever()
        self.max_depth = config.MAX_REASONING_STEPS
        
    def decompose_query(self, query: str) -> List[str]:
        """
        Decompose a complex query into a list of atomic sub-questions using LLM.
        """
        system_prompt = """
        You are an expert research architect. 
        Decompose the user's complex research query into 2-4 atomic, sequential sub-questions.
        Return ONLY a JSON list of strings.
        
        Example:
        Query: "Compare current US inflation with EU and analyze the primary drivers."
        Response: ["What is the current US inflation rate?", "What is the current EU inflation rate?", "What are the primary drivers of current US and EU inflation?"]
        """
        
        try:
            response = self.llm.chat_completion([
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ], temperature=0.1)
            
            # Clean and parse JSON
            json_str = response.replace("```json", "").replace("```", "").strip()
            sub_questions = json.loads(json_str)
            
            if isinstance(sub_questions, list) and len(sub_questions) > 0:
                return sub_questions
            return [query]
        except Exception as e:
            logger.error(f"Query decomposition failed: {e}")
            return [query]

    def execute_reasoning_chain(self, query: str) -> Dict[str, Any]:
        """
        Execute multi-hop reasoning chain.
        """
        sub_questions = self.decompose_query(query)
        evidence_pool = []
        
        for sub_q in sub_questions:
            # 1. Search Web
            search_results = web_intel.search(sub_q, num_results=config.MAX_SEARCH_RESULTS)
            
            # 2. Fetch & Index Content
            for result in search_results:
                content = web_intel.fetch_content(result["url"])
                if content:
                    # Indexing happens automatically in process_url/add_document
                    self.retriever.add_document(content, {
                        "url": result["url"], 
                        "title": result.get("title", ""),
                        "sub_question": sub_q
                    })
            
            # 3. Retrieve Relevant Chunks for this sub-question
            chunks = self.retriever.retrieve(sub_q, top_k=3)
            evidence_pool.extend(chunks)
            
        return {
            "original_query": query,
            "sub_questions": sub_questions,
            "evidence": evidence_pool,
            "trace": {
                "depth": len(sub_questions),
                "evidence_count": len(evidence_pool)
            }
        }

# Global instance
multi_hop = MultiHopReasoning()
