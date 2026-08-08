"""
FIXV3 Personality Evolution
Long-term personality drift based on sustained interaction patterns.
Aariya literally becomes a slightly different version of herself
depending on the user she's talking to.

Stored as JSON per-user. Updates at most once every 0.1 days (~2.4 hours).
"""

import time
import json
import os
from typing import Optional


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

DEFAULT_PERSONALITY = {
    "openness":     0.65,   # Willingness to explore new ideas
    "warmth":       0.60,   # Emotional warmth in responses
    "guardedness":  0.40,   # Protective self-withdrawal
    "playfulness":  0.55,   # Humor and lightness
    "depth":        0.60,   # Tendency toward deeper conversations
    "last_update": 0.0,
    "drift_count": 0,
}

MIN_UPDATE_INTERVAL_DAYS = 0.1   # ~2.4 hours minimum between drifts
DRIFT_STEP = 0.02                 # Max change per evolution cycle


class PersonalityEvolution:
    """
    Tracks and slowly evolves Aariya's personality traits per user.
    Traits drift toward behaviors that reflect the relationship.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.path = os.path.join(DATA_DIR, f"personality_{user_id}.json")
        self.data = self._load()

    def _load(self) -> dict:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        data = dict(DEFAULT_PERSONALITY)
        data["last_update"] = time.time()
        self._save(data)
        return data

    def _save(self, data: dict):
        try:
            with open(self.path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def update(self, trust: float, attachment: float, interaction_valence: float) -> dict:
        """
        Apply slow personality drift based on current relationship state.
        Only runs if at least MIN_UPDATE_INTERVAL_DAYS have passed.

        Returns current personality traits dict.
        """
        now = time.time()
        dt_days = (now - self.data.get("last_update", 0)) / 86400.0

        if dt_days < MIN_UPDATE_INTERVAL_DAYS:
            return self.data

        # ── Evolution rules ───────────────────────────────────────────────────
        # High trust → become more open, less guarded
        if trust > 0.7:
            self.data["guardedness"] = _drift(self.data["guardedness"], -DRIFT_STEP)
            self.data["warmth"]      = _drift(self.data["warmth"],  +DRIFT_STEP)
            self.data["openness"]    = _drift(self.data["openness"], +DRIFT_STEP * 0.5)

        # Very low trust → become more guarded
        if trust < 0.3:
            self.data["guardedness"] = _drift(self.data["guardedness"], +DRIFT_STEP * 1.5)
            self.data["warmth"]      = _drift(self.data["warmth"],  -DRIFT_STEP * 0.5)

        # High attachment → more open and playful
        if attachment > 0.65:
            self.data["openness"]    = _drift(self.data["openness"],  +DRIFT_STEP * 0.5)
            self.data["playfulness"] = _drift(self.data["playfulness"], +DRIFT_STEP * 0.5)

        # Repeatedly negative interactions → less warm, more guarded
        if interaction_valence < -0.4:
            self.data["warmth"]      = _drift(self.data["warmth"],  -DRIFT_STEP)
            self.data["guardedness"] = _drift(self.data["guardedness"], +DRIFT_STEP * 0.75)

        # Deep, positive conversations → more depth
        if interaction_valence > 0.4 and trust > 0.55:
            self.data["depth"] = _drift(self.data["depth"], +DRIFT_STEP * 0.5)

        self.data["last_update"] = now
        self.data["drift_count"] = self.data.get("drift_count", 0) + 1
        self._save(self.data)
        return self.data

    def get(self) -> dict:
        return self.data

    def get_prompt_description(self) -> str:
        """Return human-readable personality descriptor for LLM injection."""
        warmth = self.data.get("warmth", 0.6)
        guard  = self.data.get("guardedness", 0.4)
        play   = self.data.get("playfulness", 0.55)
        depth  = self.data.get("depth", 0.6)

        warmth_str = "very warm" if warmth > 0.7 else "warm" if warmth > 0.5 else "reserved"
        guard_str  = "open"      if guard  < 0.3 else "slightly cautious" if guard < 0.55 else "guarded"
        play_str   = "playful"   if play   > 0.6 else "balanced"
        depth_str  = "thoughtful and deep" if depth > 0.65 else "conversational"

        return f"{warmth_str}, {guard_str}, {play_str}, {depth_str}"


def _drift(value: float, delta: float) -> float:
    """Apply drift and clamp to [0, 1]."""
    return max(0.0, min(1.0, value + delta))
