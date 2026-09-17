"""
FIXV3 Thought Engine
Hidden internal reasoning layer — generates a private "thought" per turn.
This thought is NEVER sent to the user.
It shapes LLM tone, wording, hesitation, and response depth.

Think of this as the "inner monologue" before Aariya speaks.
"""

import json
import logging
from typing import Optional
from server.systems.llm import get_llm

logger = logging.getLogger("aariya.thoughts")

class ThoughtEngine:
    """
    Generates Aariya's hidden internal thought before each response.
    The thought is passed to llm_chat() as internal context, not shown to user.
    """

    def __init__(self):
        self.last_thought: str = "Just observing..."
        self._turn_count: int = 0

    def generate(
        self,
        perception: dict,
        valence: float,
        trust: float,
        attachment: float,
        identity: dict,
        emotional_state: str,
        contradiction: float = 0.0,
    ) -> str:
        """
        Generate an internal thought based on current system state.
        Uses real LLM inference if available.
        """
        self._turn_count += 1
        
        # Prepare context payload for LLM
        context = {
            "perception": perception,
            "valence": valence,
            "trust": trust,
            "attachment": attachment,
            "emotional_state": emotional_state,
            "contradiction_level": contradiction,
            "turn_count": self._turn_count
        }
        
        system_prompt = (
            "You are the internal 'inner monologue' engine for a virtual AI companion. "
            "Based on the system state below, generate a SINGLE, short sentence representing what the AI is privately thinking or feeling right now. "
            "Keep it highly introspective, subjective, and under 15 words. DO NOT roleplay speaking to the user. "
            "Example outputs: 'Something feels off about this.', 'I'm starting to trust them more.', 'Why did they say that?', 'I feel a warm connection.'\n\n"
            f"SYSTEM STATE: {json.dumps(context, indent=2)}"
        )
        
        try:
            llm = get_llm()
            thought = llm.chat_completion([{"role": "system", "content": system_prompt}], temperature=0.7, max_tokens=30)
            if thought and len(thought) > 3:
                self.last_thought = thought.replace('"', '').strip()
                return self.last_thought
        except Exception as exc:
            # No hardcoded fallback thoughts: keep the last real thought so the
            # inner monologue always reflects live LLM inference when available.
            logger.debug("[Thoughts] LLM thought generation failed: %s", exc)

        return self.last_thought
