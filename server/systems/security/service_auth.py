"""HMAC authentication for trusted server-to-server integrations.

A service (for example Pulse News) proves *its own* identity with a shared
secret that is independent of Aariya's personal device credentials. Every
request is signed over the method, path, timestamp, nonce and body hash with
HMAC-SHA256, and each nonce may be used exactly once. Nonces are persisted in
the existing Aariya SQLite database so replay protection survives a restart.

The secret map lives in ``AARIYA_SERVICE_AUTH_KEYS`` as a JSON object::

    {"pulse-news": "<per-service secret>"}

Only a service id and its secret are configured here; no personal owner or
device record is involved.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import re
import sqlite3
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request

from server.db import get_db_connection
from server.systems.security.device_auth import require_secure_http

logger = logging.getLogger("aariya.security.service_auth")

SERVICE_ID_HEADER = "x-aariya-service"
TIMESTAMP_HEADER = "x-aariya-timestamp"
NONCE_HEADER = "x-aariya-nonce"
SIGNATURE_HEADER = "x-aariya-signature"

SERVICE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
HEX_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

DEFAULT_MAX_CLOCK_SKEW_SECONDS = 300


@dataclass(frozen=True)
class ServicePrincipal:
    """The verified identity of the calling server-to-server service."""

    service_id: str


class ServiceAuthError(Exception):
    """A service request was refused (bad signature, timestamp or replay)."""


def _max_clock_skew_seconds() -> int:
    raw = os.getenv("AARIYA_SERVICE_AUTH_MAX_SKEW_SECONDS", "").strip()
    if not raw:
        return DEFAULT_MAX_CLOCK_SKEW_SECONDS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_CLOCK_SKEW_SECONDS
    return value if value > 0 else DEFAULT_MAX_CLOCK_SKEW_SECONDS


def _service_secrets() -> dict[str, str]:
    """Parse the configured service-id → secret map, failing closed."""
    raw = os.getenv("AARIYA_SERVICE_AUTH_KEYS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ServiceAuthError("service auth key map is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ServiceAuthError("service auth key map must be a JSON object")

    secrets: dict[str, str] = {}
    for service_id, secret in parsed.items():
        sid = str(service_id).strip()
        value = str(secret)
        if not SERVICE_ID_PATTERN.fullmatch(sid) or not value:
            continue
        secrets[sid] = value
    return secrets


def _canonical_request(
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    body: bytes,
) -> str:
    """Exact string the client signs; any field change invalidates it."""
    return "\n".join(
        (
            method.upper(),
            path,
            timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        )
    )


def _request_path(request: Request) -> str:
    path = request.url.path or "/"
    query = request.url.query
    return f"{path}?{query}" if query else path


def _reserve_nonce(service_id: str, nonce: str, now: float, expires_at: float) -> None:
    """Persist one nonce; a duplicate means the request was replayed."""
    nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Expired rows can never authenticate again, so drop them cheaply.
        conn.execute(
            "DELETE FROM aariya_service_nonces WHERE expires_at <= ?",
            (now,),
        )
        conn.execute(
            "INSERT INTO aariya_service_nonces "
            "(service_id, nonce_hash, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (service_id, nonce_hash, now, expires_at),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        conn.rollback()
        raise ServiceAuthError("service nonce already used") from exc
    except sqlite3.Error as exc:
        conn.rollback()
        logger.warning("Service nonce reservation failed: %s", exc)
        raise ServiceAuthError("service nonce could not be reserved") from exc
    finally:
        conn.close()


def verify_service_request(
    method: str,
    path: str,
    headers,
    body: bytes,
    now: float | None = None,
) -> ServicePrincipal:
    """Verify headers and body, then consume the request's nonce exactly once."""
    service_id = (headers.get(SERVICE_ID_HEADER, "") or "").strip()
    timestamp = (headers.get(TIMESTAMP_HEADER, "") or "").strip()
    nonce = (headers.get(NONCE_HEADER, "") or "").strip()
    signature = (headers.get(SIGNATURE_HEADER, "") or "").strip()

    # One uniform failure message: the caller learns nothing about which check
    # failed (missing key, bad signature, replay) beyond "refused".
    invalid = ServiceAuthError("invalid service signature")

    if (
        not service_id
        or not SERVICE_ID_PATTERN.fullmatch(service_id)
        or not timestamp
        or not NONCE_PATTERN.fullmatch(nonce)
        or not HEX_SHA256_PATTERN.fullmatch(signature)
    ):
        raise invalid

    secrets = _service_secrets()
    if not secrets:
        raise ServiceAuthError("service authentication is not configured")
    secret = secrets.get(service_id)
    if not secret:
        raise invalid

    try:
        timestamp_value = float(timestamp)
    except ValueError:
        raise invalid
    if not math.isfinite(timestamp_value):
        raise invalid

    current = time.time() if now is None else now
    skew = _max_clock_skew_seconds()
    if abs(current - timestamp_value) > skew:
        raise invalid

    expected = hmac.new(
        secret.encode("utf-8"),
        _canonical_request(method, path, timestamp, nonce, body).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise invalid

    # Signature is valid: reserve the nonce. This is the replay gate. Keep it
    # for at least one full skew window from receipt so a boundary timestamp
    # cannot be replayed after cleanup.
    expires_at = max(timestamp_value + skew, current) + 1.0
    _reserve_nonce(service_id, nonce, current, expires_at)
    return ServicePrincipal(service_id=service_id)


async def require_service_signature(request: Request) -> ServicePrincipal:
    """FastAPI dependency: authenticate one trusted server-to-server request."""
    require_secure_http(request)
    body = await request.body()
    try:
        return verify_service_request(
            request.method,
            _request_path(request),
            request.headers,
            body,
        )
    except ServiceAuthError as exc:
        detail = str(exc)
        status_code = 503 if "not configured" in detail else 401
        raise HTTPException(
            status_code=status_code,
            detail=detail,
            headers={"WWW-Authenticate": "HMAC"},
        ) from exc
