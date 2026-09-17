from typing import Dict, Any, Tuple, Optional
import logging
import json
from server.systems.llm import LLMEngine

logger = logging.getLogger(__name__)

class SelfDebate:
    """
    Simulates an internal adversarial debate to validate conclusions.
    Roles: Researcher (proposes answer) vs Skeptic (critiques answer).
    """
    
    def __init__(self, llm: Optional[LLMEngine] = None):
        self.llm = llm or LLMEngine()

    async def conduct_debate(self, query: str, initial_answer: str, evidence: str) -> Tuple[str, float]:
        """
        Run an adversarial debate cycle between Researcher and Skeptic.
        """
        # 1. Skeptic Role: Find gaps, contradictions, or missing evidence
        skeptic_prompt = f"""
        Role: Skeptical Auditor
        Query: {query}
        Proposed Answer: {initial_answer}
        Available Evidence: {evidence}
        
        Task: Identify 3 critical weaknesses, missing citations, or potential contradictions in the Answer.
        Be extremely rigorous. If the answer is perfect, try to find edge cases.
        """
        critique = self.llm.chat_completion([{"role": "user", "content": skeptic_prompt}])
        
        # 2. Researcher Role: Rebuttal and Refinement
        researcher_prompt = f"""
        Role: Senior Research Lead
        Query: {query}
        Original Answer: {initial_answer}
        Skeptic Critique: {critique}
        Available Evidence: {evidence}
        
        Task: Refine the answer to address the skeptic's points. 
        If a point is valid, fix the answer. 
        If a point is invalid, provide a rebuttal based on evidence.
        Return the final absolute 'Ground Truth' synthesis.
        """
        refined_answer = self.llm.chat_completion([{"role": "user", "content": researcher_prompt}])
        
        # 3. Judge Role: Consistency Score
        judge_prompt = f"""
        Rate the final answer's reliability from 0.0 to 1.0 based on how well it addressed the critique.
        Return ONLY the number.
        """
        try:
            score_str = self.llm.chat_completion([
                {"role": "system", "content": judge_prompt},
                {"role": "user", "content": f"Final Answer: {refined_answer}"}
            ])
            confidence = float(score_str.strip())
        except Exception:
            confidence = 0.85
            
        return refined_answer, confidence

# Global instance
debate = SelfDebate()
