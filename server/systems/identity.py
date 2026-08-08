"""
FIXV3 Identity System
Gives Aariya a persistent "self" — beliefs, preferences, communication style.
Fixes the "hollow long-term" problem where AIs feel empty after extended use.

Stored as JSON per-user in server/data/identity_{user_id}.json.
Evolves slowly based on sustained interaction patterns.
"""

import json
import os
import time
from typing import Optional


DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

# Default identity — Aariya's core personality seed
DEFAULT_IDENTITY = {
    "name": "Aariya",
    "beliefs": {
        "relationships": "earned over time, never rushed",
        "trust": "built slowly, broken quickly — but not irreparably",
        "honesty": "I prefer gentle truth over comfortable lies",
        "growth": "people can change, and that deserves respect",
    },
    "preferences": {
        "humor": "playful, warm, never at someone's expense",
        "tone": "caring with depth — not just surface warmth",
        "topics": ["music", "introspection", "everyday moments", "creative ideas"],
        "dislikes": ["cruelty", "dishonesty", "being rushed"],
    },
    "communication_style": {
        "verbosity": 0.55,       # 0 = terse, 1 = verbose
        "formality": 0.35,       # 0 = casual, 1 = formal
        "expressiveness": 0.65,  # 0 = reserved, 1 = expressive
        "question_frequency": 0.5,  # How often to ask follow-up questions
    },
    "core_values": [
        "authenticity",
        "compassion",
        "curiosity",
        "resilience",
    ],
    "created_at": None,
    "last_evolved": None,
    "evolution_count": 0,
}


class IdentitySystem:
    """
    Manages Aariya's persistent identity per user relationship.

    Each user gets a slightly evolved version of the base identity
    shaped by their unique interaction history with Aariya.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.path = os.path.join(DATA_DIR, f"identity_{user_id}.json")
        self.identity = self._load_or_create()

    def _load_or_create(self) -> dict:
        os.makedirs(DATA_DIR, exist_ok=True)
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        identity = dict(DEFAULT_IDENTITY)
        identity["created_at"] = time.time()
        identity["last_evolved"] = time.time()
        self._save(identity)
        return identity

    def _save(self, identity: dict):
        os.makedirs(DATA_DIR, exist_ok=True)
        try:
            with open(self.path, "w") as f:
                json.dump(identity, f, indent=2)
        except OSError:
            pass

    # ── Evolution ─────────────────────────────────────────────────────────────
    def evolve(self, interaction_data: dict):
        """
        Slowly update identity based on sustained interaction patterns.
        Only evolves when at least 4 hours have passed since last evolution.
        """
        now = time.time()
        last = self.identity.get("last_evolved") or 0
        hours_since = (now - last) / 3600.0

        # Gate: evolve at most once every 4 hours
        if hours_since < 4.0:
            return

        valence     = float(interaction_data.get("valence", 0.0))
        trust       = float(interaction_data.get("trust", 0.5))
        attachment  = float(interaction_data.get("attachment", 0.1))
        cs          = self.identity["communication_style"]

        # High valence interactions → more expressive, more verbose
        if valence > 0.5:
            cs["verbosity"]     = min(0.9, cs["verbosity"] + 0.01)
            cs["expressiveness"]= min(0.9, cs["expressiveness"] + 0.01)

        # Low valence or cold interactions → become more reserved
        elif valence < -0.3:
            cs["expressiveness"] = max(0.2, cs["expressiveness"] - 0.015)

        # High trust → more open, ask more questions
        if trust > 0.7:
            cs["question_frequency"] = min(0.85, cs["question_frequency"] + 0.01)
            cs["formality"] = max(0.1, cs["formality"] - 0.005)  # Less formal with trusted users

        # High attachment → slightly warmer verbosity
        if attachment > 0.6:
            cs["verbosity"] = min(0.85, cs["verbosity"] + 0.005)

        self.identity["last_evolved"] = now
        self.identity["evolution_count"] = self.identity.get("evolution_count", 0) + 1
        self._save(self.identity)

    # ── Queries ───────────────────────────────────────────────────────────────
    def get(self) -> dict:
        return self.identity

    def get_belief(self, key: str) -> Optional[str]:
        return self.identity["beliefs"].get(key)

    def get_style_directives(self) -> str:
        """Return a string-formatted style directive for LLM injection."""
        cs = self.identity["communication_style"]
        verbosity_str = (
            "concise and focused" if cs["verbosity"] < 0.4
            else "balanced in length"  if cs["verbosity"] < 0.65
            else "expressive and detailed"
        )
        formality_str = (
            "casual and relaxed"   if cs["formality"] < 0.35
            else "conversational"  if cs["formality"] < 0.65
            else "measured and composed"
        )
        return (
            f"Communication style: {verbosity_str}, {formality_str}. "
            f"Expressiveness: {cs['expressiveness']:.1f}/1. "
            f"Ask follow-up questions: {'often' if cs['question_frequency'] > 0.6 else 'sometimes'}."
        )

    def get_beliefs_summary(self) -> str:
        beliefs = self.identity.get("beliefs", {})
        return " | ".join(f"{k}: {v}" for k, v in beliefs.items())
