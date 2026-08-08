"""
Priority Pipeline - Social QoS
Classifies user input into priority levels (P0-P4) to determine response urgency and resource allocation.

Levels:
P0: Emergency/Safety/Interrupt - Immediate response, bypasses normal gating if needed.
P1: Direct Question/Command - High priority LLM generation.
P2: Conversational/Standard - Normal flow.
P3: Ambient/Observation - Lower priority, may be deferred or acknowledged concisely.
P4: Idle/Automatic - Background tasks only.
"""

import re
from enum import IntEnum
from typing import Dict, List, Optional

class Priority(IntEnum):
    P0_EMERGENCY = 0
    P1_DIRECT = 1
    P2_CONVERSATIONAL = 2
    P3_AMBIENT = 3
    P4_IDLE = 4

class PriorityPipeline:
    def __init__(self):
        # Keywords for P0/P1 detection
        self.emergency_keywords = [
            r"\bhelp\b", r"\bemergency\b", r"\bstop\b", r"\bdanger\b", 
            r"\balert\b", r"\bwait\b", r"\blook out\b"
        ]
        
        self.question_markers = [
            r"\?", r"^who\b", r"^what\b", r"^where\b", r"^when\b", 
            r"^why\b", r"^how\b", r"^can you\b", r"^could you\b"
        ]

    def classify(self, text: str) -> Priority:
        """
        Heuristic-based classification of turn priority.
        """
        clean_text = text.lower().strip()
        
        if not clean_text:
            return Priority.P4_IDLE

        # P0: Emergency/Safety Signals
        for pattern in self.emergency_keywords:
            if re.search(pattern, clean_text):
                return Priority.P0_EMERGENCY

        # P1: Direct Questions or explicit requests
        is_question = any(re.search(pattern, clean_text) for pattern in self.question_markers)
        if is_question or len(clean_text.split()) < 3 and clean_text.endswith('?'):
            return Priority.P1_DIRECT

        # P3: Ambient/Low signal (e.g. "hmm", "okay", "wow")
        ambient_markers = ["hmm", "cool", "wow", "oh", "ok", "okay", "i see"]
        if clean_text in ambient_markers or (len(clean_text) < 10 and clean_text not in self.emergency_keywords):
            # Only P3 if it matches ambient markers or is very short without being a question/emergency
            if clean_text in ambient_markers:
                return Priority.P3_AMBIENT

        # Default: Standard Conversation
        return Priority.P2_CONVERSATIONAL

    def get_qos_params(self, priority: Priority) -> Dict:
        """
        Returns resource allocation parameters based on priority.
        """
        params = {
            Priority.P0_EMERGENCY: {
                "max_tokens": 50,
                "temperature": 0.3,
                "latency_priority": "ultra",
                "bypass_memory": True
            },
            Priority.P1_DIRECT: {
                "max_tokens": 200,
                "temperature": 0.7,
                "latency_priority": "high",
                "bypass_memory": False
            },
            Priority.P2_CONVERSATIONAL: {
                "max_tokens": 500,
                "temperature": 0.9,
                "latency_priority": "normal",
                "bypass_memory": False
            },
            Priority.P3_AMBIENT: {
                "max_tokens": 100,
                "temperature": 1.0,
                "latency_priority": "low",
                "bypass_memory": False
            },
            Priority.P4_IDLE: {
                "max_tokens": 0,
                "temperature": 0.0,
                "latency_priority": "none",
                "bypass_memory": True
            }
        }
        return params.get(priority, params[Priority.P2_CONVERSATIONAL])

_pipeline = PriorityPipeline()

def get_priority_pipeline() -> PriorityPipeline:
    return _pipeline
