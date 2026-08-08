"""
firebase_alerts.py — Firebase Cloud Messaging push notifications for Pulse AI News.

Sends push notifications when the AlertAgent decides an article is alert-worthy.
Gracefully falls back to logging if Firebase credentials are unavailable.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("pulse.firebase")

try:
    import firebase_admin  # type: ignore
    from firebase_admin import credentials, messaging  # type: ignore
    _FCM_AVAILABLE = True
except ImportError:
    _FCM_AVAILABLE = False


class FirebaseAlertManager:
    def __init__(self):
        self._initialized = False

    def initialize(self):
        if not _FCM_AVAILABLE:
            logger.warning("[Firebase] firebase-admin not installed — push unavailable")
            return
        if self._initialized:
            return
        try:
            cred_path = os.getenv("FIREBASE_CREDENTIALS", "firebase-credentials.json")
            if os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)
                self._initialized = True
                logger.info("[Firebase] Initialized from %s", cred_path)
            else:
                logger.info("[Firebase] No credentials file at %s — push disabled", cred_path)
        except Exception as exc:
            logger.warning("[Firebase] Initialization failed: %s", exc)

    def send_alert(self, article: Dict[str, Any]) -> bool:
        title = article.get("title", "Breaking News")
        summary = article.get("summary", "New critical update available.")
        priority = article.get("alert_priority", "normal")

        if priority not in ("critical", "high"):
            return False

        if not _FCM_AVAILABLE or not self._initialized:
            logger.info("[Firebase] (unavailable) Would push: %s", title)
            return True

        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=f"\U0001f514 {title}" if priority == "critical" else title,
                    body=summary[:200],
                ),
                data={
                    "article_id": article.get("id", ""),
                    "priority": priority,
                    "category": article.get("category", ""),
                    "importance": str(article.get("importance", 0)),
                },
                topic="breaking_news",
            )
            messaging.send(message)
            logger.info("[Firebase] Push sent: %s (priority=%s)", title, priority)
            return True
        except Exception as exc:
            logger.warning("[Firebase] Send failed: %s", exc)
            return False

    def send_briefing_alert(self, headline_count: int, risk_count: int):
        if not _FCM_AVAILABLE or not self._initialized:
            return
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title="\U0001f4f0 Pulse News Briefing",
                    body=f"{headline_count} top stories, {risk_count} risk alerts.",
                ),
                topic="daily_briefing",
            )
            messaging.send(message)
        except Exception as exc:
            logger.warning("[Firebase] Briefing push failed: %s", exc)


firebase = FirebaseAlertManager()
