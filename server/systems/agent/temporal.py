from typing import List, Dict, Any, Optional
import logging
import re
from datetime import datetime
try:
    import dateparser
    HAS_DATEPARSER = True
except ImportError:
    HAS_DATEPARSER = False

logger = logging.getLogger(__name__)

class TemporalManager:
    """
    Handles temporal reasoning and consistency checking.
    """
    
    def extract_dates(self, text: str) -> List[datetime]:
        """
        Extract and normalize dates found in text.
        """
        found_dates = []
        
        # 1. Broad ISO/YYYY-MM-DD search
        iso_matches = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', text)
        for ds in iso_matches:
            try:
                found_dates.append(datetime.strptime(ds, "%Y-%m-%d"))
            except: pass
            
        # 2. Year-only 
        years = re.findall(r'\b(19|20)\d{2}\b', text)
        for ys in years:
            try:
                found_dates.append(datetime(int(ys), 1, 1))
            except: pass
            
        # 3. Natural language (if dateparser is available)
        if HAS_DATEPARSER:
            # We look for common date patterns like "January 2024" or "20th Oct"
            # This is expensive so we should only do it on smaller chunks
            pass
            
        return sorted(list(set(found_dates)))

    def detect_timeline_conflicts(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyze a list of events for chronological or factual contradictions.
        Each event: {"timestamp": datetime, "fact": str, "source": str, "value": Any}
        """
        conflicts = []
        # Sort by timestamp
        sorted_events = sorted([e for e in events if e.get("timestamp")], key=lambda x: x["timestamp"])
        
        for i in range(len(sorted_events)):
            for j in range(i + 1, len(sorted_events)):
                e1, e2 = sorted_events[i], sorted_events[j]
                
                # Conflict if same fact has different values at same time
                if e1["fact"] == e2["fact"] and e1["timestamp"] == e2["timestamp"]:
                    if e1["value"] != e2["value"]:
                        conflicts.append({
                            "type": "simultaneous_contradiction",
                            "fact": e1["fact"],
                            "time": e1["timestamp"],
                            "sources": [e1["source"], e2["source"]],
                            "values": [e1["value"], e2["value"]]
                        })
                        
                # Conflict if logically impossible (e.g., price dropped but trend says rose)
                # This requires deeper logic integration later
                
        return conflicts

# Global instance
temporal = TemporalManager()
