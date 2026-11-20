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
import ipaddress
import logging
import os
from typing import Set
from fastapi import HTTPException, Request, WebSocket

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


def require_health_auth(request: Request) -> None:
    """Guarding dependency for diagnostic REST endpoints (System Health).

    The health payload includes per-user session/lock state, so it must not be
    readable by an anonymous off-box client:

      * ``REQUIRE_WS_AUTH=1`` (production): every request needs a valid token,
        loopback or not.
      * soft mode (dev): loopback requests pass without a token; a request from
        any other address still needs one.

    Token sources match the WebSocket layer: ``Authorization: Bearer <token>``
    or ``?token=<token>``. Raises HTTP 401 when access is refused.
    """
    token = (
        request.query_params.get("token")
        or _http_bearer(request.headers)
    )
    if REQUIRE_AUTH:
        if token and _is_valid(token):
            return
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client_host = _effective_client_host(request)
    if _is_loopback(client_host):
        return
    if token and _is_valid(token):
        return
    raise HTTPException(
        status_code=401,
        detail="Remote access to diagnostic endpoints requires a bearer token",
        headers={"WWW-Authenticate": "Bearer"},
    )


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


def _http_bearer(headers) -> str:
    """Pull the token from a plain HTTP request's Authorization header."""
    auth = headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


#: Starlette's TestClient uses this sentinel host; treat it as loopback so
#: in-process tests exercise the endpoint without a token in soft mode.
_LOOPBACK_HOSTS = {"testclient"}


def _trusted_proxy_networks() -> list:
    """Configured proxies whose X-Forwarded-For may be believed.

    AARIYA_TRUSTED_PROXIES is a comma-separated list of IPs / CIDRs
    (e.g. ``127.0.0.1,10.0.0.0/8``). Empty by default: a forwarded header is
    then ignored entirely, because any client could otherwise claim to be
    loopback and read the health payload anonymously.
    """
    raw = os.getenv("AARIYA_TRUSTED_PROXIES", "")
    networks = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            logger.warning("[Auth] ignoring invalid trusted proxy %r", part)
    return networks


def _is_trusted_proxy(host: str, networks: list) -> bool:
    if not host:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in networks)


def _effective_client_host(request: Request) -> str:
    """Client address, honouring X-Forwarded-For only from trusted proxies.

    Behind a reverse proxy every request's transport peer is the proxy, so the
    real client lives in X-Forwarded-For. The header is client-controlled
    otherwise, so it is used only when the immediate peer is configured in
    AARIYA_TRUSTED_PROXIES. The chain is walked right-to-left, skipping trusted
    hops; the first untrusted address is the client. This is what keeps the
    loopback exemption from turning into a remote bypass through a proxy.
    """
    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded:
        return peer

    networks = _trusted_proxy_networks()
    if not networks or not _is_trusted_proxy(peer, networks):
        return peer

    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    for hop in reversed(hops):
        if not _is_trusted_proxy(hop, networks):
            return hop
    return hops[0] if hops else peer


def _is_loopback(host: str) -> bool:
    """True for localhost / 127.0.0.0/8 / ::1 / the ASGI test client."""
    if not host:
        return False
    if host in _LOOPBACK_HOSTS or host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_valid(token: str) -> bool:
    """Validate against secret or dev allowlist."""
    if SECRET_TOKEN and hmac.compare_digest(token, SECRET_TOKEN):
        return True
    return token in _DEV_TOKENS
