"""Short-lived TURN credential issuance for paired mobile devices.

The TURN REST API credential format is defined in:
  https://tools.ietf.org/html/draft-uberti-behave-turn-rest-00

The shared secret (``TURN_SHARED_SECRET``) is the same value as Coturn's
``static-auth-secret``.  It lives in the server environment only — it is
never sent to the mobile client and is not stored in the codebase.

Generated credentials expire after ``TURN_CREDENTIAL_LIFETIME_SECONDS``
(default 3600 s / 1 hour).  The mobile app must call this endpoint before
each WebRTC session and must not cache credentials across sessions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.systems.security.device_auth import (
    DevicePrincipal,
    require_mobile_device,
)

router = APIRouter(tags=["webrtc"])

#: Permit 1 minute – 24 hours.  Shorter is safer; the default (1 hour) is
#: long enough to cover a voice session without forcing mid-call renegotiation.
_MIN_LIFETIME = 60
_MAX_LIFETIME = 86_400
_DEFAULT_LIFETIME = int(
    os.getenv("TURN_CREDENTIAL_LIFETIME_SECONDS", "3600")
)


class TURNCredentials(BaseModel):
    urls: list[str]
    username: str
    credential: str
    ttl: int


def generate_turn_credentials(
    *,
    lifetime_seconds: int = _DEFAULT_LIFETIME,
) -> dict:
    """Return short-lived TURN credentials.

    Raises ``RuntimeError`` when the server is not configured for TURN.
    Raises ``ValueError`` for out-of-range ``lifetime_seconds``.
    """
    secret = os.getenv("TURN_SHARED_SECRET", "").strip()
    urls = [
        item.strip()
        for item in os.getenv("TURN_URLS", "").split(",")
        if item.strip()
    ]

    if not secret:
        raise RuntimeError("TURN_SHARED_SECRET is not configured.")
    if not urls:
        raise RuntimeError("TURN_URLS is not configured.")
    if not _MIN_LIFETIME <= lifetime_seconds <= _MAX_LIFETIME:
        raise ValueError(
            f"TURN credential lifetime must be between "
            f"{_MIN_LIFETIME} and {_MAX_LIFETIME} seconds."
        )

    expiry = int(time.time()) + lifetime_seconds

    # TURN REST API credential format: "<expiry>:<username>"
    username = f"{expiry}:aariya"
    digest = hmac.new(
        secret.encode("utf-8"),
        username.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    credential = base64.b64encode(digest).decode("ascii")

    return {
        "urls": urls,
        "username": username,
        "credential": credential,
        "ttl": lifetime_seconds,
    }


@router.get(
    "/api/webrtc/turn-credentials",
    response_model=TURNCredentials,
    summary="Fetch short-lived TURN credentials (paired mobile only)",
)
async def get_turn_credentials(
    principal: DevicePrincipal = Depends(require_mobile_device),
) -> TURNCredentials:
    """Issue a fresh set of TURN credentials for the authenticated device.

    * Requires a paired mobile device credential (Bearer token).
    * Returns credentials valid for ``TURN_CREDENTIAL_LIFETIME_SECONDS``
      (default 3 600 s).
    * Returns 503 when ``TURN_SHARED_SECRET`` or ``TURN_URLS`` are not set
      in the server environment — the client should fall back to STUN only.
    """
    if not principal.authenticated:
        raise HTTPException(
            status_code=401,
            detail=(
                "TURN credential issuance requires a paired mobile device; "
                "legacy unauthenticated access is not supported"
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        creds = generate_turn_credentials()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return TURNCredentials(**creds)
