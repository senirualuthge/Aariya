import time
from typing import Optional

class MetaCognitionEngine:
    def __init__(self):
        self.consecutive_conflict_turns = 0
        self.consecutive_chaos_turns = 0
        
        self.conflict_threshold = 0.5
        self.chaos_threshold = 0.5  # low coherence
        
        self.current_overlay: Optional[str] = None
        
    def reflect(self, synoptic_state) -> Optional[str]:
        """
        Monitors cognitive coherence and conflict over time.
        If the swarm is consistently in conflict, return a self-regulation strategy.
        Returns an overlay string for the personality/router layer.
        """
        # Monitor Conflict
        conflict = getattr(synoptic_state, "conflict", 0.0)
        if conflict > self.conflict_threshold:
            self.consecutive_conflict_turns += 1
        else:
            self.consecutive_conflict_turns = max(0, self.consecutive_conflict_turns - 1)
            
        # Monitor Coherence
        coherence = getattr(synoptic_state, "coherence", 1.0)
        if coherence < self.chaos_threshold:
            self.consecutive_chaos_turns += 1
        else:
            self.consecutive_chaos_turns = max(0, self.consecutive_chaos_turns - 1)
            
        # Decide on Self-Regulation
        if self.consecutive_conflict_turns >= 3:
            self.current_overlay = "meta_regulation_calm"
        elif self.consecutive_chaos_turns >= 3:
            self.current_overlay = "meta_regulation_focus"
        else:
            self.current_overlay = None
            
        return self.current_overlay
