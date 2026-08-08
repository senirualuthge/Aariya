import time
from typing import List
from dataclasses import dataclass, field
import uuid

@dataclass
class NarrativeEvent:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = "general"
    user_sentiment: float = 0.0
    trust_delta: float = 0.0
    intensity: float = 0.0
    memory_refs: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

class NarrativeEngine:
    def __init__(self):
        self.history: List[NarrativeEvent] = []
        self.baseline_sentiment: float = 0.0
        # Tracks current emotional volatility
        self.shock_threshold: float = 0.5
        self.current_shock: float = 0.0
        
    def add_event(self, event: NarrativeEvent):
        """Register a new interaction event."""
        self.history.append(event)
        
        # Calculate moving baseline for sudden contrast shifts
        if len(self.history) > 1:
            prev_events = self.history[-5:]
            self.baseline_sentiment = sum(e.user_sentiment for e in prev_events) / len(prev_events)
            
        # Add a time decay step for existing shock
        self.current_shock = max(0.0, self.current_shock - 0.1)

    def compute_shock(self) -> float:
        """
        Calculate if a recent event drastically deviates from the baseline.
        This provides a 'shockwave' coefficient used to destabilize the cognitive swarm.
        """
        if not self.history:
            return 0.0
            
        latest = self.history[-1]
        
        # Shock occurs from sudden sentiment shifts or intensely high-energy events
        shift = abs(latest.user_sentiment - self.baseline_sentiment)
        
        if shift > self.shock_threshold or latest.intensity > self.shock_threshold:
            # We have a cognitive shockwave
            self.current_shock = min(1.0, self.current_shock + shift + latest.intensity)
            
        return self.current_shock
