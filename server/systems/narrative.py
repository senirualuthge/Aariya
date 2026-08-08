"""
FIXV3 Narrative System
Long-term narrative and shared history.
Stores significant events with emotional weight.
Tracks relationship stage. Enables "remember when..." callbacks.
"""

import json
import os
import time
from typing import List, Optional


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

class NarrativeSystem:
    """
    Maintains the overarching story of the relationship with the user.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.path = os.path.join(DATA_DIR, f"narrative_{user_id}.json")
        self.data = self._load()

    def _load(self) -> dict:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        
        data = {
            "stage": "early context-building",
            "recent_events": [],  # High level summaries of major relationship events
            "turn_count": 0,
        }
        self._save(data)
        return data

    def _save(self, data: dict):
        try:
            with open(self.path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def evaluate(self, trust: float, attachment: float, event_summary: Optional[str] = None) -> dict:
        """
        Updates relationship stage and tracks events.
        """
        self.data["turn_count"] += 1

        # Update stage based on trust and attachment
        if trust > 0.8 and attachment > 0.7:
            self.data["stage"] = "deep connection"
        elif trust > 0.6 and attachment > 0.5:
            self.data["stage"] = "developing bond"
        elif trust < 0.3 and attachment > 0.6:
            self.data["stage"] = "strained but attached"
        elif trust < 0.3:
            self.data["stage"] = "distant or defensive"
        else:
            self.data["stage"] = "familiar / context-building"

        if event_summary:
            self.data["recent_events"].append({
                "summary": event_summary,
                "timestamp": time.time(),
                "trust_at_time": trust
            })
            # Keep only the last 10 major events
            self.data["recent_events"] = self.data["recent_events"][-10:]

        # Save periodically
        if self.data["turn_count"] % 20 == 0 or event_summary:
            self._save(self.data)

        return self.data

    def get_context(self) -> dict:
        events = [e["summary"] for e in self.data["recent_events"][-3:]]
        return {
            "stage": self.data["stage"],
            "recent_events": ", ".join(events) if events else "none yet"
        }
