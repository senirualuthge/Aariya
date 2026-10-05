"""
WebSocket Authentication Layer — Zero-Trust token validation.

In development: token validation is OPTIONAL (soft mode).
In production:  set REQUIRE_WS_AUTH=1 and WS_SECRET_TOKEN env vars.

Usage (in WebSocket handler):
    from server.systems.security.auth import verify_ws_token
    if not await verify_ws_token(websocket):
        return   # connection was already closed
"""
import hmac
import hashlib
import logging
import os
from typing import Set
from fastapi import WebSocket

logger = logging.getLogger("aariya.security.auth")

# Dev default is permissive; tighten by setting env vars in production
REQUIRE_AUTH = os.getenv("REQUIRE_WS_AUTH", "0") == "1"
SECRET_TOKEN = os.getenv("WS_SECRET_TOKEN", "")

# Allowlisted dev tokens (dev-only; never use in production)
_DEV_TOKENS: Set[str] = {"dev-token", "aariya-dev-2026"}


async def verify_ws_token(websocket: WebSocket) -> bool:
    """
    Validate the token passed as a WebSocket query-param or header.

    ?token=<value>   ← primary method (easy for Flutter / Unity clients)
    Authorization: Bearer <value>   ← alternative

    Returns True if auth passes (or if auth is not required).
    Closes the WebSocket with code 1008 and returns False on failure.
    """
    if not REQUIRE_AUTH:
        return True   # soft mode — skip in development

    token = (
        websocket.query_params.get("token")
        or _extract_bearer(websocket)
    )

    if not token:
        logger.warning("[WsAuth] Rejected: no token presented")
        await websocket.close(code=1008, reason="Authentication required")
        return False

    if _is_valid(token):
        return True

    logger.warning(f"[WsAuth] Rejected: invalid token")
    await websocket.close(code=1008, reason="Invalid token")
    return False


def verify_message_signature(message: str, signature: str) -> bool:
    """
    HMAC-SHA256 message integrity check.
    Used for high-trust channels (e.g., admin control messages).

    Fails CLOSED once auth is required: with REQUIRE_WS_AUTH=1 a deployment must
    also set WS_SECRET_TOKEN, otherwise no signature could ever validate and
    every signed frame would be accepted unsigned. Soft mode (auth not required)
    keeps the historical pass-through so local dev needs no secret.
    """
    if not SECRET_TOKEN:
        return not REQUIRE_AUTH

    expected = hmac.new(
        SECRET_TOKEN.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _extract_bearer(websocket: WebSocket) -> str:
    """Pull the token from an Authorization: Bearer <token> header."""
    auth = websocket.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def _is_valid(token: str) -> bool:
    """Validate against secret or dev allowlist."""
    if SECRET_TOKEN and hmac.compare_digest(token, SECRET_TOKEN):
        return True
    return token in _DEV_TOKENS
