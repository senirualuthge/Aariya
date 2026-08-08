from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import uuid4

from db import db_cursor, get_user_settings  # type: ignore

logger = logging.getLogger("pulse.personalization")

_DEFAULT_PREFS = {
    "interests": ["AI", "economy", "startups"],
    "region": "global",
    "risk_mode": True,
    "alert_threshold": 7,
}


class PersonalizationEngine:
    def __init__(self):
        self._affinity_cache: Dict[str, Dict[str, float]] = {}
        self._prefs_cache: Dict[str, Dict[str, Any]] = {}

    def _load_prefs(self, user_id: str) -> Dict[str, Any]:
        prefs = get_user_settings(user_id)
        try:
            with db_cursor() as cur:
                cur.execute(
                    "SELECT topic, affinity FROM user_topic_prefs WHERE user_id = %s",
                    (user_id,),
                )
                rows = cur.fetchall()
                if user_id not in self._affinity_cache:
                    self._affinity_cache[user_id] = {}
                for row in rows:
                    self._affinity_cache[user_id][row["topic"]] = float(row["affinity"])
        except Exception as exc:
            logger.debug("[Personalization] DB load failed: %s", exc)
        return prefs

    def _save_affinity(self, user_id: str, topic: str, affinity: float):
        try:
            with db_cursor() as cur:
                cur.execute(
                    """INSERT INTO user_topic_prefs (user_id, topic, affinity)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, topic)
                    DO UPDATE SET affinity = EXCLUDED.affinity""",
                    (user_id, topic, round(affinity, 4)),
                )
        except Exception as exc:
            logger.debug("[Personalization] DB save failed: %s", exc)

    def user_prefs(self, user_id: str) -> Dict[str, Any]:
        if user_id not in self._prefs_cache:
            self._prefs_cache[user_id] = self._load_prefs(user_id)
        return self._prefs_cache[user_id]

    def topic_affinity(self, user_id: str) -> Dict[str, float]:
        return dict(self._affinity_cache.get(user_id, {}))

    def process_feedback(self, article_id: str, feedback_type: str, user_id: str = "anonymous"):
        logger.info("[Personalization] %s on %s (user=%s)", feedback_type, article_id, user_id)
        try:
            with db_cursor() as cur:
                cur.execute("SELECT category FROM articles WHERE id = %s", (article_id,))
                row = cur.fetchone()
                if not row:
                    return
                category = row["category"] or "other"

                cur.execute(
                    """INSERT INTO user_interactions (id, user_id, article_id, feedback_type)
                    VALUES (%s, %s, %s, %s)""",
                    (str(uuid4()), user_id, article_id, feedback_type),
                )

            reward = 1.0 if feedback_type in ("click", "save", "share") else -0.5
            if feedback_type == "dismiss":
                reward = -1.0

            if user_id not in self._affinity_cache:
                self._affinity_cache[user_id] = {}
            current = self._affinity_cache[user_id].get(category, 0.8)
            lr = 0.05
            new_affinity = current + lr * reward
            new_affinity = max(0.1, min(2.0, new_affinity))
            self._affinity_cache[user_id][category] = new_affinity
            self._save_affinity(user_id, category, new_affinity)

        except Exception as exc:
            logger.error("[Personalization] Feedback error: %s", exc)

    def adapt_score(self, article: Dict[str, Any], user_id: str = "anonymous") -> float:
        base_score = article.get("importance", 5) or 5
        category = article.get("category", "other") or "other"

        affinities = self._affinity_cache.get(user_id, {})
        affinity = affinities.get(category, 0.8)
        adapted = base_score * affinity

        prefs = self.user_prefs(user_id)
        if prefs.get("risk_mode") and article.get("is_risk"):
            adapted *= 1.3

        return round(min(10.0, adapted), 2)

    def personalize_rank(self, articles: List[Dict[str, Any]], user_id: str = "anonymous") -> List[Dict[str, Any]]:
        for a in articles:
            a["personalized_score"] = self.adapt_score(a, user_id)
        prefs = self.user_prefs(user_id)
        threshold = prefs.get("alert_threshold", 7)
        for a in articles:
            if a.get("importance", 0) >= threshold and a.get("is_risk"):
                a["personalized_score"] = min(10.0, a["personalized_score"] * 1.2)
        articles.sort(key=lambda x: x.get("personalized_score", 0), reverse=True)
        return articles


personalizer = PersonalizationEngine()
