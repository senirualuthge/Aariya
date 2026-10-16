"""
aigirl_bridge.py — Bridges Pulse AI News alerts into the AI Girl event bus.

When Pulse's AlertAgent decides an article is alert-worthy, this module
sends a signal to the AI Girl server's /api/signals/ingest endpoint.
Gracefully falls back to logging if the AI Girl server is unreachable.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("pulse.aigirl")

AIGIRL_API_URL = os.getenv("AIGIRL_API_URL", "http://localhost:8000")


async def dispatch_alert_to_aigirl(article: Dict[str, Any]) -> bool:
    """Send a breaking news alert to the AI Girl event bus.

    Emits the formal ``news.alert`` contract (the server validates it and
    projects it into the news feed BrainV2 reads). All fields are taken from the
    real article — nothing is invented; missing fields are simply omitted.
    """
    priority = article.get("alert_priority", "normal")
    importance = article.get("importance", 0) or 0

    severity = "critical" if priority == "critical" else "high" if priority == "high" else "info"

    payload: Dict[str, Any] = {
        "headline": str(article.get("title", "") or "").strip(),
        "summary": str(article.get("summary", "") or ""),
        "importance": min(1.0, max(0.0, float(importance) / 10.0)),
        "category": str(article.get("category", "general") or "general"),
        "topics": [str(t) for t in (article.get("key_entities") or []) if str(t).strip()],
        "url": str(article.get("url", "") or ""),
    }
    published = article.get("published_at") or article.get("timestamp")
    if isinstance(published, (int, float)):
        payload["ts"] = float(published)

    signal = {
        "type": "news.alert",
        "severity": severity,
        "source": {
            "system": "pulse-news",
            "file": "services/aigirl_bridge.py",
            "function": "dispatch_alert_to_aigirl",
        },
        "context": {
            "platform": "pulse",
        },
        "payload": payload,
        "confidence": min(1.0, float(importance) / 10.0),
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{AIGIRL_API_URL}/api/signals/ingest",
                json=signal,
            )
            if resp.status_code in (200, 201):
                logger.info("[AIGirl] Alert dispatched: %s", payload["headline"][:60])
                return True
            else:
                logger.warning("[AIGirl] Dispatch returned %s: %s", resp.status_code, resp.text[:100])
                return False
    except httpx.ConnectError:
        logger.debug("[AIGirl] AI Girl server unreachable at %s", AIGIRL_API_URL)
        return False
    except Exception as exc:
        logger.debug("[AIGirl] Dispatch failed: %s", exc)
        return False


async def dispatch_briefing_to_aigirl(briefing: Dict[str, Any]) -> bool:
    """Send a daily briefing signal to the AI Girl event bus."""
    signal = {
        "type": "system",
        "severity": "info",
        "source": {
            "system": "pulse-news",
            "file": "services/aigirl_bridge.py",
            "function": "dispatch_briefing_to_aigirl",
        },
        "context": {
            "platform": "pulse",
        },
        "payload": {
            "title": "Pulse News Briefing Ready",
            "description": json.dumps({
                "headline_count": briefing.get("headline_count", 0),
                "top_story": briefing.get("top_story", {}).get("title"),
                "risk_count": len(briefing.get("risk_alerts", [])),
            }),
        },
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{AIGIRL_API_URL}/api/signals/ingest",
                json=signal,
            )
            return resp.status_code in (200, 201)
    except Exception as exc:
        logger.debug("[AIGirl] Briefing dispatch failed: %s", exc)
        return False
