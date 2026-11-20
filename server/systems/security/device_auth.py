"""Device-level authentication for Aariya's personal channels (Patch 2/3).

The shared ``WS_SECRET_TOKEN`` proves *someone* knows a secret; it does not
prove *which device* is connecting, so any holder could claim any ``user_id``.
This module adds the missing identity layer:

  * a personal device is enrolled once with a one-use pairing code created by a
    LOCAL command (never an unauthenticated web endpoint);
  * the device keeps a long-lived credential, stored server-side only as a
    SHA-256 hash;
  * WebSockets authenticate with a one-use, path-bound, 30-second ticket sent
    as the ``aariya-ticket.<token>`` subprotocol — the credential itself never
    appears in a URL;
  * the owner identity is read from the server-side device record, never from
    the connection query string.

Strict device authentication is active when ``AARIYA_OWNER_ID`` is set. Until
then the server keeps the legacy shared-token behaviour so an existing
installation does not lock itself out before pairing any device; the legacy
path is reported by ``device_auth_enabled()`` and logged at boot.

All personal devices resolve to the single configured owner, because one human
may use several devices but owns one Aariya.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import secrets
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, Request, WebSocket

from server.db import get_db_connection
from server.systems.security import auth as token_auth

logger = logging.getLogger("aariya.security.device_auth")

#: Subprotocol echoed back on an accepted, device-authenticated WebSocket.
DEVICE_WS_SUBPROTOCOL = "aariya.v1"
#: Client-offered subprotocol carrying the one-use ticket.
TICKET_SUBPROTOCOL_PREFIX = "aariya-ticket."

PAIRING_ROLES = frozenset({"mobile", "dashboard"})

#: Which roles may open each private WebSocket channel.
WS_PATH_ROLES = {
    "/ws/mobile": frozenset({"mobile"}),
    "/ws/mobile/control": frozenset({"mobile"}),
    "/ws/mobile/analytics": frozenset({"mobile"}),
    "/ws/dashboard/stream": frozenset({"dashboard"}),
    "/ws/brain": frozenset({"dashboard"}),
    "/ws/brain_metrics": frozenset({"dashboard"}),
    "/api/security/stream": frozenset({"dashboard"}),
    "/ws/synoptics": frozenset({"dashboard"}),
    "/api/agents/ws": frozenset({"dashboard"}),
    "/api/swarm/ws": frozenset({"dashboard"}),
    "/api/gev/stream": frozenset({"dashboard"}),
    "/api/gev/stream-diff": frozenset({"dashboard"}),
}

PAIRING_TTL_SECONDS = 300
TICKET_TTL_SECONDS = 30

#: Prefix makes a leaked credential recognisable in redaction rules.
CREDENTIAL_PREFIX = "aariya-device."

_PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I/O/0/1
_PAIRING_GROUPS = 2
_PAIRING_GROUP_LEN = 4


class DeviceAuthError(Exception):
    """A device-auth operation was refused (invalid/expired/revoked input)."""


@dataclass(frozen=True)
class DevicePrincipal:
    """The authenticated identity behind one connection or request."""

    device_id: str
    owner_id: str
    role: str
    label: str = ""
    #: False only on the legacy shared-token path (no device record).
    authenticated: bool = True


# ── Configuration ────────────────────────────────────────────────────────────

def configured_owner_id() -> str:
    return os.getenv("AARIYA_OWNER_ID", "").strip()


def device_auth_enabled() -> bool:
    """Strict device auth is on once a canonical owner is configured."""
    return bool(configured_owner_id())


def _insecure_transport_allowed() -> bool:
    return os.getenv("AARIYA_ALLOW_INSECURE_DEVICE_AUTH", "0") == "1"


# ── Hashing helpers ──────────────────────────────────────────────────────────

def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_pairing_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


# ── Pairing code + enrollment ────────────────────────────────────────────────

def create_pairing_code(
    role: str,
    owner_id: Optional[str] = None,
    ttl_seconds: int = PAIRING_TTL_SECONDS,
) -> str:
    """Create a one-use pairing code. Only its hash is persisted.

    Intended to be called from ``python -m server.tools.create_device_pairing_code``
    on the server machine — never from an HTTP endpoint.
    """
    role = (role or "").strip().lower()
    if role not in PAIRING_ROLES:
        raise DeviceAuthError(f"role must be one of {sorted(PAIRING_ROLES)}")
    owner = (owner_id or configured_owner_id()).strip()
    if not owner:
        raise DeviceAuthError("AARIYA_OWNER_ID is not configured")
    if ttl_seconds <= 0:
        raise DeviceAuthError("ttl_seconds must be positive")

    groups = [
        "".join(secrets.choice(_PAIRING_ALPHABET) for _ in range(_PAIRING_GROUP_LEN))
        for _ in range(_PAIRING_GROUPS)
    ]
    display_code = "-".join(groups)
    now = time.time()

    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO aariya_pairing_codes "
            "(code_hash, owner_id, device_role, created_at, expires_at, consumed_at) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            (_hash_secret(_normalize_pairing_code(display_code)),
             owner, role, now, now + ttl_seconds),
        )
        conn.commit()
    finally:
        conn.close()
    return display_code


def enroll_device(
    pairing_code: str,
    label: str,
    platform: str,
) -> tuple[DevicePrincipal, str]:
    """Redeem a pairing code and return ``(principal, credential)``.

    The credential is returned exactly once; the database keeps only its hash.
    The device role and owner come from the server-side pairing record, so a
    caller cannot choose either.
    """
    normalized = _normalize_pairing_code(pairing_code)
    label = (label or "").strip()
    platform = (platform or "").strip()
    if not normalized:
        raise DeviceAuthError("invalid pairing code")
    if not label or len(label) > 80:
        raise DeviceAuthError("label must be 1-80 characters")
    if not platform or len(platform) > 30:
        raise DeviceAuthError("platform must be 1-30 characters")

    now = time.time()
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT owner_id, device_role, expires_at, consumed_at "
            "FROM aariya_pairing_codes WHERE code_hash = ?",
            (_hash_secret(normalized),),
        ).fetchone()
        if row is None:
            raise DeviceAuthError("invalid pairing code")
        if row["consumed_at"] is not None:
            raise DeviceAuthError("pairing code already used")
        if row["expires_at"] <= now:
            raise DeviceAuthError("pairing code expired")

        consumed = conn.execute(
            "UPDATE aariya_pairing_codes SET consumed_at = ? "
            "WHERE code_hash = ? AND consumed_at IS NULL",
            (now, _hash_secret(normalized)),
        )
        if consumed.rowcount != 1:
            raise DeviceAuthError("pairing code already used")

        device_id = str(uuid.uuid4())
        credential = CREDENTIAL_PREFIX + secrets.token_urlsafe(32)
        conn.execute(
            "INSERT INTO aariya_personal_devices "
            "(device_id, owner_id, device_role, label, platform, "
            " credential_hash, created_at, last_seen_at, revoked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)",
            (device_id, row["owner_id"], row["device_role"], label, platform,
             _hash_secret(credential), now, now),
        )
        conn.commit()
    except DeviceAuthError:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.warning("Device enrollment failed: %s", exc)
        raise DeviceAuthError("device enrollment failed") from exc
    finally:
        conn.close()

    principal = DevicePrincipal(
        device_id=device_id,
        owner_id=row["owner_id"],
        role=row["device_role"],
        label=label,
    )
    logger.info(
        "Enrolled %s device %s for owner %s",
        principal.role, device_id, principal.owner_id,
    )
    return principal, credential


# ── Credential authentication (REST) ─────────────────────────────────────────

def authenticate_credential(credential: str) -> DevicePrincipal:
    """Resolve a device credential to its principal, or raise DeviceAuthError."""
    credential = (credential or "").strip()
    if not credential:
        raise DeviceAuthError("device credential required")

    now = time.time()
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT device_id, owner_id, device_role, label, revoked_at "
            "FROM aariya_personal_devices WHERE credential_hash = ?",
            (_hash_secret(credential),),
        ).fetchone()
        if row is None:
            raise DeviceAuthError("unknown device credential")
        if row["revoked_at"] is not None:
            raise DeviceAuthError("device revoked")
        conn.execute(
            "UPDATE aariya_personal_devices SET last_seen_at = ? WHERE device_id = ?",
            (now, row["device_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return DevicePrincipal(
        device_id=row["device_id"],
        owner_id=row["owner_id"],
        role=row["device_role"],
        label=row["label"],
    )


# ── WebSocket tickets ────────────────────────────────────────────────────────

def roles_for_path(path: str) -> frozenset:
    """Roles allowed on a path, including parameterised collaboration rooms."""
    roles = WS_PATH_ROLES.get(path)
    if roles:
        return roles
    if path.startswith("/ws/collab/"):
        return frozenset({"dashboard"})
    return frozenset()


def role_for_path(path: str) -> Optional[str]:
    roles = roles_for_path(path)
    if not roles:
        return None
    # Personal channels are currently single-role; keep the mapping explicit.
    return next(iter(roles))


def role_allows_path(role: str, path: str) -> bool:
    return role in roles_for_path(path)


def issue_ws_ticket(
    principal: DevicePrincipal,
    path: str,
    ttl_seconds: int = TICKET_TTL_SECONDS,
) -> str:
    """Issue a one-use ticket bound to one device, owner and WS path."""
    path = (path or "").split("?", 1)[0]
    if not role_allows_path(principal.role, path):
        raise DeviceAuthError(
            f"device role {principal.role!r} may not open {path!r}"
        )
    if ttl_seconds <= 0:
        raise DeviceAuthError("ttl_seconds must be positive")

    now = time.time()
    ticket = secrets.token_urlsafe(32)
    conn = get_db_connection()
    try:
        device = conn.execute(
            "SELECT revoked_at FROM aariya_personal_devices WHERE device_id = ?",
            (principal.device_id,),
        ).fetchone()
        if device is None or device["revoked_at"] is not None:
            raise DeviceAuthError("device revoked")
        # Opportunistic cleanup: expired tickets are useless and cheap to drop.
        conn.execute("DELETE FROM aariya_ws_tickets WHERE expires_at <= ?", (now,))
        conn.execute(
            "INSERT INTO aariya_ws_tickets "
            "(ticket_hash, device_id, owner_id, path, created_at, expires_at, consumed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (_hash_secret(ticket), principal.device_id, principal.owner_id,
             path, now, now + ttl_seconds),
        )
        conn.commit()
    finally:
        conn.close()
    return ticket


def redeem_ws_ticket(ticket: str, path: str) -> DevicePrincipal:
    """Atomically consume a ticket and return the device principal.

    Redemption is a single ``BEGIN IMMEDIATE`` transaction with a conditional
    ``UPDATE ... WHERE consumed_at IS NULL``, so two sockets racing with the
    same ticket produce exactly one success.
    """
    ticket = (ticket or "").strip()
    path = (path or "").split("?", 1)[0]
    if not ticket:
        raise DeviceAuthError("websocket ticket required")

    now = time.time()
    ticket_hash = _hash_secret(ticket)
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT device_id, owner_id, path, expires_at, consumed_at "
            "FROM aariya_ws_tickets WHERE ticket_hash = ?",
            (ticket_hash,),
        ).fetchone()
        if row is None:
            raise DeviceAuthError("invalid websocket ticket")
        if row["consumed_at"] is not None:
            raise DeviceAuthError("websocket ticket already used")
        if row["expires_at"] <= now:
            raise DeviceAuthError("websocket ticket expired")
        if row["path"] != path:
            raise DeviceAuthError("websocket ticket is for another route")

        device = conn.execute(
            "SELECT device_id, owner_id, device_role, label, revoked_at "
            "FROM aariya_personal_devices WHERE device_id = ?",
            (row["device_id"],),
        ).fetchone()
        if device is None:
            raise DeviceAuthError("unknown device")
        if device["revoked_at"] is not None:
            raise DeviceAuthError("device revoked")

        consumed = conn.execute(
            "UPDATE aariya_ws_tickets SET consumed_at = ? "
            "WHERE ticket_hash = ? AND consumed_at IS NULL",
            (now, ticket_hash),
        )
        if consumed.rowcount != 1:
            raise DeviceAuthError("websocket ticket already used")
        conn.commit()
    except DeviceAuthError:
        conn.rollback()
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        logger.warning("Ticket redemption failed: %s", exc)
        raise DeviceAuthError("websocket ticket could not be redeemed") from exc
    finally:
        conn.close()

    return DevicePrincipal(
        device_id=device["device_id"],
        owner_id=device["owner_id"],
        role=device["device_role"],
        label=device["label"],
    )


# ── Device management ────────────────────────────────────────────────────────

def list_devices(owner_id: str) -> List[dict]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT device_id, owner_id, device_role, label, platform, "
            "created_at, last_seen_at, revoked_at "
            "FROM aariya_personal_devices WHERE owner_id = ? "
            "ORDER BY created_at ASC",
            (owner_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "device_id": row["device_id"],
            "owner_id": row["owner_id"],
            "role": row["device_role"],
            "label": row["label"],
            "platform": row["platform"],
            "created_at": row["created_at"],
            "last_seen_at": row["last_seen_at"],
            "revoked": row["revoked_at"] is not None,
        }
        for row in rows
    ]


def revoke_device(device_id: str, owner_id: str) -> bool:
    """Revoke one device and invalidate every outstanding ticket immediately."""
    now = time.time()
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        updated = conn.execute(
            "UPDATE aariya_personal_devices SET revoked_at = ? "
            "WHERE device_id = ? AND owner_id = ? AND revoked_at IS NULL",
            (now, device_id, owner_id),
        )
        if updated.rowcount != 1:
            conn.rollback()
            return False
        conn.execute("DELETE FROM aariya_ws_tickets WHERE device_id = ?", (device_id,))
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    finally:
        conn.close()
    logger.info("Revoked device %s for owner %s", device_id, owner_id)
    return True


# ── FastAPI dependencies ────────────────────────────────────────────────────

def _bearer(headers) -> str:
    value = headers.get("authorization", "")
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def require_device(request: Request) -> DevicePrincipal:
    """Authenticate a REST request from its device credential (Bearer)."""
    if not device_auth_enabled():
        raise HTTPException(
            status_code=503,
            detail="Device authentication is not configured (set AARIYA_OWNER_ID)",
        )
    require_secure_http(request)
    try:
        return authenticate_credential(_bearer(request.headers))
    except DeviceAuthError as exc:
        raise HTTPException(
            status_code=401,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        )


def current_owner_id(
    principal: DevicePrincipal = Depends(require_device),
) -> str:
    """FastAPI dependency: the server-owned identity for personal data."""
    return principal.owner_id


def personal_actor(request: Request) -> Optional[DevicePrincipal]:
    """Authenticated device for shared surfaces, or None in legacy mode."""
    if not device_auth_enabled():
        return None
    return require_device(request)


def personal_owner(
    request: Request,
    user_id: Optional[str] = Query(default=None),
) -> str:
    """Owner for personal REST data, preferring the authenticated device.

    With device auth enabled (AARIYA_OWNER_ID set) the query/body value is
    IGNORED entirely — the owner comes from the credential, so editing a URL
    cannot select another person's memories. Legacy mode (no owner configured)
    keeps the historical query contract so an installation keeps working until
    its devices are paired.
    """
    if device_auth_enabled():
        return require_device(request).owner_id
    return (user_id or "user_default").strip() or "user_default"


# ── Transport security ──────────────────────────────────────────────────────

def _is_loopback(host: str) -> bool:
    if host in {"testclient", "localhost"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _forwarded_proto(headers) -> str:
    return (headers.get("x-forwarded-proto", "").split(",", 1)[0]).strip().lower()


def _peer_is_trusted_proxy(peer: str) -> bool:
    return token_auth._is_trusted_proxy(peer, token_auth._trusted_proxy_networks())


def _secure_transport(scheme: str, peer: str, headers) -> bool:
    if _insecure_transport_allowed():
        return True
    if scheme in {"https", "wss"}:
        return True
    if _is_loopback(peer):
        return True
    # Behind a reverse proxy the transport to the peer is plain HTTP; only
    # believe X-Forwarded-Proto when the peer itself is a configured proxy.
    if _forwarded_proto(headers) == "https" and _peer_is_trusted_proxy(peer):
        return True
    return False


def require_secure_http(request: Request) -> None:
    peer = request.client.host if request.client else ""
    if not _secure_transport(request.url.scheme, peer, request.headers):
        raise HTTPException(
            status_code=403,
            detail="Device authentication requires HTTPS (or loopback in dev)",
        )


async def _close_insecure(websocket: WebSocket) -> None:
    await websocket.close(code=1008, reason="Secure transport required (wss)")


# ── WebSocket authentication ────────────────────────────────────────────────

def _offered_ticket(websocket: WebSocket) -> str:
    for proto in websocket.scope.get("subprotocols") or []:
        if proto.startswith(TICKET_SUBPROTOCOL_PREFIX):
            return proto[len(TICKET_SUBPROTOCOL_PREFIX):].strip()
    return ""


async def authenticate_personal_websocket(
    websocket: WebSocket,
    expected_path: Optional[str] = None,
) -> Optional[DevicePrincipal]:
    """Authenticate a private WebSocket, or close it and return ``None``.

    Strict mode (``AARIYA_OWNER_ID`` set) requires a valid one-use ticket in the
    ``aariya-ticket.<token>`` subprotocol. Legacy mode keeps the shared-token
    check and takes the owner from ``?user_id=`` so existing installations keep
    working until they pair their devices.
    """
    path = (expected_path or websocket.url.path).split("?", 1)[0]
    role = role_for_path(path)
    if role is None:
        logger.error("No device-auth policy for WebSocket path %s", path)
        await websocket.close(code=1008, reason="Unprotected WebSocket path")
        return None

    if not device_auth_enabled():
        if not await token_auth.verify_ws_token(websocket):
            return None
        return legacy_principal(websocket, role)

    peer = websocket.client.host if websocket.client else ""
    if not _secure_transport(websocket.url.scheme, peer, websocket.headers):
        await _close_insecure(websocket)
        return None

    ticket = _offered_ticket(websocket)
    if not ticket:
        logger.warning("[DeviceAuth] Rejected %s: no websocket ticket", path)
        await websocket.close(code=1008, reason="Device ticket required")
        return None

    try:
        principal = redeem_ws_ticket(ticket, path)
    except DeviceAuthError as exc:
        logger.warning("[DeviceAuth] Rejected %s: %s", path, exc)
        await websocket.close(code=1008, reason=str(exc))
        return None

    if not role_allows_path(principal.role, path):
        logger.warning(
            "[DeviceAuth] %s device tried to open %s", principal.role, path
        )
        await websocket.close(code=1008, reason="Device role not allowed")
        return None
    return principal


def legacy_principal(websocket: WebSocket, role: str) -> DevicePrincipal:
    """Pre-pairing identity derived from the old query contract."""
    return DevicePrincipal(
        # Empty means "no client-supplied id": the mobile gateway then assigns
        # a unique key per socket instead of collapsing all phones into one.
        device_id=websocket.query_params.get("client_id") or "",
        owner_id=websocket.query_params.get("user_id") or "user_default",
        role=role,
        label="legacy",
        authenticated=False,
    )


async def accept_personal_websocket(
    websocket: WebSocket,
    principal: DevicePrincipal,
) -> None:
    """Accept the socket, echoing the device subprotocol when offered."""
    offered = websocket.scope.get("subprotocols") or []
    subprotocol = (
        DEVICE_WS_SUBPROTOCOL
        if principal.authenticated and DEVICE_WS_SUBPROTOCOL in offered
        else None
    )
    await websocket.accept(subprotocol=subprotocol)
