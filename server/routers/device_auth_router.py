"""Device authentication REST API (Patch 2/3).

  POST   /api/auth/device/enroll      redeem a one-use pairing code
  POST   /api/auth/ws-ticket          issue a path-bound WS ticket
  GET    /api/auth/mode               authentication mode only (no identity)
  GET    /api/auth/me                 authenticated owner + device identity
  GET    /api/auth/devices            trusted devices for this owner
  DELETE /api/auth/devices/{device_id} revoke one device

The enrollment request deliberately accepts no owner, device id or role: the
server takes all three from the pairing record it created locally.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.systems.security import auth as token_auth
from server.systems.security.device_auth import (
    TICKET_TTL_SECONDS,
    DeviceAuthError,
    DevicePrincipal,
    PairingRateLimited,
    clear_pairing_failures,
    device_auth_enabled,
    enroll_device,
    issue_ws_ticket,
    list_devices,
    require_dashboard_device,
    require_device,
    require_secure_http,
    reserve_pairing_attempt,
    revoke_device_and_disconnect,
)

router = APIRouter(prefix="/api/auth", tags=["device-auth"])


class EnrollDeviceRequest(BaseModel):
    pairing_code: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=80)
    platform: str = Field(min_length=1, max_length=30)


class WsTicketRequest(BaseModel):
    path: str = Field(min_length=1, max_length=200)


@router.post("/device/enroll")
def enroll(body: EnrollDeviceRequest, request: Request):
    """Exchange a pairing code for a device credential (returned once).

    Every failure returns the same message, so the endpoint cannot be used to
    probe whether a guessed code exists. Failed attempts are rate-limited per
    source and globally in SQLite, before the code is looked up.
    """
    require_secure_http(request)
    source = token_auth._effective_client_host(request)
    try:
        reserve_pairing_attempt(source)
    except PairingRateLimited as exc:
        raise HTTPException(
            status_code=429,
            detail="Too many pairing attempts; try again later",
            headers={
                "Retry-After": str(exc.retry_after),
            },
        )
    except DeviceAuthError as exc:
        raise HTTPException(
            status_code=503,
            detail="Pairing protection is not configured",
        ) from exc

    try:
        principal, credential = enroll_device(
            pairing_code=body.pairing_code,
            label=body.label,
            platform=body.platform,
        )
    except DeviceAuthError:
        raise HTTPException(
            status_code=400,
            detail="invalid, expired, or already used pairing code",
        )

    clear_pairing_failures(source)
    return {
        "device_id": principal.device_id,
        "owner_id": principal.owner_id,
        "role": principal.role,
        "label": principal.label,
        "credential": credential,
    }


@router.post("/ws-ticket")
def create_ws_ticket(
    request: WsTicketRequest,
    principal: DevicePrincipal = Depends(require_device),
):
    """Issue a single-use ticket for one WebSocket path."""
    try:
        ticket = issue_ws_ticket(principal, request.path, ttl_seconds=TICKET_TTL_SECONDS)
    except DeviceAuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return {
        "ticket": ticket,
        "path": request.path,
        "expires_in": TICKET_TTL_SECONDS,
    }


@router.get("/mode")
def auth_mode():
    """Return only the authentication mode required by the server."""
    enabled = device_auth_enabled()
    return {
        "mode": "device" if enabled else "legacy",
        "device_auth_enabled": enabled,
    }


@router.get("/me")
def me(principal: DevicePrincipal = Depends(require_device)):
    return {
        "owner_id": principal.owner_id,
        "device_id": principal.device_id,
        "role": principal.role,
        "label": principal.label,
    }


@router.get("/devices")
def devices(principal: DevicePrincipal = Depends(require_device)):
    return {"devices": list_devices(principal.owner_id)}


@router.delete("/devices/{device_id}")
async def revoke(
    device_id: str,
    principal: DevicePrincipal = Depends(require_dashboard_device),
):
    if not await revoke_device_and_disconnect(device_id, principal.owner_id):
        raise HTTPException(status_code=404, detail="Device not found or already revoked")
    return {"revoked": True, "device_id": device_id}
