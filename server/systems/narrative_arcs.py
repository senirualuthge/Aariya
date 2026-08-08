import time
from typing import Dict, Optional, List
from dataclasses import dataclass, field

@dataclass
class NarrativeArc:
    id: str
    theme: str  # e.g., "Building Trust", "Conflict Resolution"
    status: str = "open"  # "open", "resolved", "fading"
    intensity: float = 0.5
    event_ids: List[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)

class NarrativeArcSystem:
    def __init__(self):
        self.active_arcs: Dict[str, NarrativeArc] = {}
        
    def evaluate_arcs(self, shock: float, latest_event_topic: str) -> None:
        """
        Groups events into long-term behavioral narrative patterns.
        High shock can spawn a new arc or intensify an existing one.
        """
        # Slow decay of all open arcs
        for arc in self.active_arcs.values():
            if arc.status == "open":
                arc.intensity = max(0.0, arc.intensity - 0.05)
                if arc.intensity < 0.1:
                    arc.status = "fading"

        if shock > 0.6:
            arc_id = f"arc_{int(time.time())}"
            topic_lower = latest_event_topic.lower()
            if "trust" in topic_lower or "betrayal" in topic_lower or "lie" in topic_lower:
                theme = "Trust Calibration"
            elif "sadness" in topic_lower or "distress" in topic_lower or "cry" in topic_lower:
                theme = "Supporting Distress"
            elif "anger" in topic_lower or "mad" in topic_lower:
                theme = "Conflict De-escalation"
            else:
                theme = "Intense Volatility"
                
            # See if an open arc with this theme exists
            existing_arc = next((a for a in self.active_arcs.values() if a.theme == theme and a.status == "open"), None)
            
            if existing_arc:
                existing_arc.intensity = min(1.0, existing_arc.intensity + 0.3)
                existing_arc.last_updated = time.time()
            else:
                self.active_arcs[arc_id] = NarrativeArc(
                    id=arc_id,
                    theme=theme,
                    intensity=shock
                )
                
    def get_dominant_arc(self) -> Optional[NarrativeArc]:
        if not self.active_arcs:
            return None
        # Find highest intensity open arc
        open_arcs = [a for a in self.active_arcs.values() if a.status == "open"]
        if not open_arcs:
            return None
        return max(open_arcs, key=lambda a: a.intensity)
