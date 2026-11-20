"""Authenticated bridge from Pulse News into Aariya.

When Pulse's AlertAgent decides an article is alert-worthy, this module sends
an HMAC-signed signal to the Aariya server's ``/api/signals/ingest`` endpoint.

Pulse News has its own service identity (``AARIYA_SERVICE_ID`` +
``AARIYA_SERVICE_SECRET``) and never uses an Aariya personal device credential.
Every request is signed over the method, path, timestamp, nonce and body hash,
so an unsigned request, a modified body, or a replayed nonce is rejected.

The bridge degrades gracefully: if Aariya is unreachable or unconfigured, the
alert is logged and ``False`` is returned instead of breaking Pulse's pipeline.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Dict
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger("pulse.aigirl")


def _endpoint() -> str:
    base = os.getenv("AIGIRL_API_URL", "").strip().rstrip("/")
    if not base:
        raise RuntimeError(
            "AIGIRL_API_URL must be configured"
        )
    return f"{base}/api/signals/ingest"


def _service_credentials() -> tuple[str, str]:
    service_id = os.getenv("AARIYA_SERVICE_ID", "").strip()
    secret = os.getenv("AARIYA_SERVICE_SECRET", "").strip()
    if not service_id or not secret:
        raise RuntimeError(
            "AARIYA_SERVICE_ID and AARIYA_SERVICE_SECRET must be configured"
        )
    return service_id, secret


def _canonical_request(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    return "\n".join(
        (
            method.upper(),
            path,
            timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        )
    )


def _signed_headers(
    method: str,
    url: str,
    body: bytes,
) -> Dict[str, str]:
    """Build the HMAC headers for exactly these bytes and this URL."""
    service_id, secret = _service_credentials()
    parts = urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"

    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    signature = hmac.new(
        secret.encode("utf-8"),
        _canonical_request(
            method,
            path,
            timestamp,
            nonce,
            body,
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return {
        "content-type": "application/json",
        "x-aariya-service": service_id,
        "x-aariya-timestamp": timestamp,
        "x-aariya-nonce": nonce,
        "x-aariya-signature": signature,
    }


async def _post_signed(signal: Dict[str, Any]) -> httpx.Response:
    url = _endpoint()
    body = json.dumps(
        signal,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    headers = _signed_headers("POST", url, body)
    async with httpx.AsyncClient(timeout=5.0) as client:
        return await client.post(url, content=body, headers=headers)


def _build_alert_signal(article: Dict[str, Any]) -> Dict[str, Any]:
    """Project a real article onto the formal ``news.alert`` contract."""
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

    return {
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


async def dispatch_alert_to_aigirl(article: Dict[str, Any]) -> bool:
    """Send a breaking news alert to the AI Girl event bus.

    Emits the formal ``news.alert`` contract (the server validates it and
    projects it into the news feed BrainV2 reads). All fields are taken from the
    real article — nothing is invented; missing fields are simply omitted.
    """
    signal = _build_alert_signal(article)
    headline = signal["payload"]["headline"]

    try:
        resp = await _post_signed(signal)
        if resp.status_code in (200, 201):
            logger.info("[AIGirl] Alert dispatched: %s", headline[:60])
            return True

        logger.warning(
            "[AIGirl] Dispatch returned %s: %s",
            resp.status_code,
            resp.text[:100],
        )
        return False
    except httpx.ConnectError:
        logger.debug("[AIGirl] AI Girl server unreachable")
        return False
    except (RuntimeError, ValueError) as exc:
        logger.warning("[AIGirl] Dispatch not configured: %s", exc)
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
        resp = await _post_signed(signal)
        return resp.status_code in (200, 201)
    except (RuntimeError, ValueError) as exc:
        logger.warning("[AIGirl] Briefing not configured: %s", exc)
        return False
    except Exception as exc:
        logger.debug("[AIGirl] Briefing dispatch failed: %s", exc)
        return False
