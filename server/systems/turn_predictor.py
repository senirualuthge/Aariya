"""
Turn-Taking Predictor — Phase 4 Implementation.

Analyzes user speech patterns and linguistic cues to predict if a user has 
finished their thought or is merely pausing.
Outputs a completion probability [0.0 - 1.0].
"""

import re
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class TurnPredictorMetrics:
    completion_probability: float
    reason: str

class TurnPredictor:
    """
    Analyzes temporal and linguistic cues to predict turn completion.
    """
    
    # Words that often signal a continuation
    CONTINUATION_WORDS = {
        "and", "but", "or", "so", "actually", "like", "basically", 
        "then", "because", "if", "when", "although"
    }
    
    # Interjections that might be part of a larger thought
    INTERJECTIONS = {"uh", "um", "ah", "er", "hmm"}

    def __init__(self):
        self.last_text = ""
        self.turn_start_time = 0.0

    def predict(
        self, 
        text: str, 
        silence_ms: float, 
        is_final: bool = False
    ) -> TurnPredictorMetrics:
        """
        Calculate probability that the user is done speaking.
        
        Args:
            text: Current partial or final transcript
            silence_ms: Time since last audio activity
            is_final: Whether the ASR marked this as a final segment
        """
        if not text:
            return TurnPredictorMetrics(0.0, "no_text")
            
        prob = 0.5
        reasons = []
        
        # 1. ASR Finality (High weight)
        if is_final:
            prob += 0.3
            reasons.append("asr_final")
            
        # 2. Punctuation Cues
        text_stripped = text.strip()
        if text_stripped.endswith((".", "!", "?")):
            prob += 0.25
            reasons.append("terminal_punctuation")
        
        # 3. Continuation Logic (Negative weight)
        tokens = text_stripped.lower().split()
        if tokens:
            last_token = tokens[-1]
            if last_token in self.CONTINUATION_WORDS:
                prob -= 0.4
                reasons.append("continuation_word")
            elif last_token in self.INTERJECTIONS:
                prob -= 0.2
                reasons.append("interjection")
        
        # 4. Silence Duration (Temporal weight)
        # 0ms -> 0 modifier, 500ms -> +0.2, 1000ms -> +0.4
        silence_mod = min(0.5, (silence_ms / 1000.0) * 0.5)
        prob += silence_mod
        if silence_mod > 0.1:
            reasons.append(f"silence_{int(silence_ms)}ms")
            
        # 5. Sentence Length Heuristic
        # Very short sentences (< 3 words) are often complete (greetings/yes/no)
        if len(tokens) < 3 and silence_ms > 300:
            prob += 0.2
            reasons.append("short_utterance")
            
        # Clamp result
        final_prob = float(max(0.0, min(1.0, prob)))
        
        return TurnPredictorMetrics(
            completion_probability=final_prob,
            reason="|".join(reasons) if reasons else "baseline"
        )

# Singleton instance per session (to be managed in main.py)
def create_turn_predictor() -> TurnPredictor:
    return TurnPredictor()
