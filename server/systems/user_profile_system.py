"""
User Profile System - Social QoS
Tracks communicative style and topic preferences to enable mirroring and better alignment.

Profiles are PERSISTED to SQLite (data/user_profiles.db) with a write-through
in-memory cache, so learned style survives restarts — no reset-to-zero data loss.
"""

import json
import os
import sqlite3
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict

_DB_PATH = os.path.join("data", "user_profiles.db")

@dataclass
class UserStyleProfile:
    user_id: str
    avg_verbosity: float = 0.5  # 0 (short) to 1 (long)
    sentiment_bias: float = 0.0  # -1 to 1
    fav_topics: Dict[str, float] = field(default_factory=dict)
    interaction_count: int = 0
    last_updated: float = field(default_factory=time.time)

class UserProfileSystem:
    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path
        self.profiles: Dict[str, UserStyleProfile] = {}
        self._init_db()
        self._load_all()

    # ── SQLite persistence ────────────────────────────────────────────────────

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_style_profiles (
                    user_id TEXT PRIMARY KEY,
                    payload   TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

    def _load_all(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT user_id, payload FROM user_style_profiles").fetchall()
            for user_id, blob in rows:
                try:
                    data = json.loads(blob)
                    self.profiles[user_id] = UserStyleProfile(**data)
                except (json.JSONDecodeError, TypeError) as exc:
                    print(f"[UserProfile] corrupt row for {user_id}: {exc}")
        except sqlite3.Error as exc:
            print(f"[UserProfile] load failed: {exc}")

    def _persist(self, profile: UserStyleProfile):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT INTO user_style_profiles (user_id, payload, updated_at) "
                    "VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
                    "payload=excluded.payload, updated_at=excluded.updated_at",
                    (profile.user_id, json.dumps(asdict(profile)),
                     profile.last_updated))
        except sqlite3.Error as exc:
            print(f"[UserProfile] persist failed: {exc}")

    def get_profile(self, user_id: str) -> UserStyleProfile:
        if user_id not in self.profiles:
            self.profiles[user_id] = UserStyleProfile(user_id=user_id)
        return self.profiles[user_id]

    def update_style(self, user_id: str, text: str, sentiment: float):
        """
        Calculates style metrics and updates the profile using EMA.
        """
        profile = self.get_profile(user_id)
        
        # 1. Update Verbosity (EMA)
        word_count = len(text.split())
        # Normalize: 0 to 40 words maps to 0 to 1
        current_verbosity = min(word_count / 40.0, 1.0)
        alpha = 0.2  # Smoothing factor
        profile.avg_verbosity = (1 - alpha) * profile.avg_verbosity + alpha * current_verbosity

        # 2. Update Sentiment Bias (EMA)
        profile.sentiment_bias = (1 - alpha) * profile.sentiment_bias + alpha * sentiment

        # 3. Topic Detection (very basic heuristic)
        topics = {
            "work": ["work", "job", "career", "boss", "meeting"],
            "leisure": ["play", "game", "movie", "fun", "hobby"],
            "emotional": ["feel", "sad", "happy", "love", "alone"],
            "technical": ["code", "ai", "system", "bug", "build"]
        }
        
        text_lower = text.lower()
        for topic, keywords in topics.items():
            if any(kw in text_lower for kw in keywords):
                profile.fav_topics[topic] = profile.fav_topics.get(topic, 0.0) + 0.1
                # Decay others slightly
                for other in profile.fav_topics:
                    if other != topic:
                        profile.fav_topics[other] *= 0.95

        profile.interaction_count += 1
        profile.last_updated = time.time()
        self._persist(profile)

    def get_style_directives(self, user_id: str) -> str:
        """
        Generates prompt instructions based on user style to encourage mirroring.
        """
        profile = self.get_profile(user_id)
        if profile.interaction_count < 3:
            return ""

        directives = []
        
        # Verbosity Mirroring
        if profile.avg_verbosity < 0.3:
            directives.append("The user prefers short, concise communication. Respond briefly.")
        elif profile.avg_verbosity > 0.7:
            directives.append("The user is talkative and uses detail. Provide more elaborate responses.")

        # Sentiment Mirroring
        if profile.sentiment_bias > 0.4:
            directives.append("The user is generally positive. Match their upbeat tone.")
        elif profile.sentiment_bias < -0.4:
            directives.append("The user seems somber or serious. Be more reflective and empathetic.")

        # Topic Focus
        if profile.fav_topics:
            top_topic = max(profile.fav_topics.items(), key=lambda x: x[1])
            if top_topic[1] > 0.5:
                directives.append(f"The user has been focusing on {top_topic[0]}-related themes recently.")

        return " ".join(directives)

_profile_manager = UserProfileSystem()

def get_user_profile_system() -> UserProfileSystem:
    return _profile_manager
