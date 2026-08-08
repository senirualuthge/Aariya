"""
Meeting Mode Control Router — FIXV4
─────────────────────────────────────
REST endpoints for controlling and monitoring Meeting Mode.

Endpoints:
  GET  /api/meeting/status       → current state + speaker estimate
  POST /api/meeting/toggle       → enable / disable
  POST /api/meeting/window       → set base direct-address window (seconds)
  POST /api/meeting/names        → replace name alias list
  POST /api/meeting/names/add    → append a single alias
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import List, Optional

from server.systems.meeting_mode import get_meeting_mode

router = APIRouter(prefix="/api/meeting", tags=["meeting"])


# ── Request models ─────────────────────────────────────────────────────────────

class ToggleRequest(BaseModel):
    active: Optional[bool] = None   # None = flip current state

class WindowRequest(BaseModel):
    seconds: float = Field(..., ge=10.0, le=300.0, description="Base window in seconds")

class NamesRequest(BaseModel):
    names: List[str] = Field(..., min_length=1)

class AddNameRequest(BaseModel):
    alias: str = Field(..., min_length=1, max_length=40)


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/status")
def get_status():
    """Return the full Meeting Mode state including speaker count estimate."""
    return get_meeting_mode().get_status()


@router.post("/toggle")
def toggle_meeting_mode(req: ToggleRequest):
    """Enable, disable, or flip Meeting Mode."""
    mode = get_meeting_mode()
    new_state = mode.toggle(req.active)
    return {
        "ok":     True,
        "active": new_state,
        "status": mode.get_status(),
    }


@router.post("/window")
def set_window(req: WindowRequest):
    """Set the base direct-address follow-up window in seconds."""
    mode = get_meeting_mode()
    mode.set_base_window(req.seconds)
    return {
        "ok":                True,
        "base_window":       mode._base_window,
        "current_window":    mode.direct_address_window,
    }


@router.post("/names")
def set_names(req: NamesRequest):
    """Replace the full AI name alias list."""
    mode = get_meeting_mode()
    mode.set_name_aliases(req.names)
    return {"ok": True, "ai_names": mode.ai_names}


@router.post("/names/add")
def add_name(req: AddNameRequest):
    """Append a single name alias without replacing the full list."""
    mode = get_meeting_mode()
    mode.add_name_alias(req.alias)
    return {"ok": True, "ai_names": mode.ai_names}
