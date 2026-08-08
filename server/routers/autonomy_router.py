"""
Autonomy Router — REST control plane for Aariya's autonomy layer.
Provides the inner-world state, plan approval/rejection, enable toggle,
and manual knowledge-gap queueing. The WebSocket command path in main.py
mirrors these for in-session control.
"""

import logging
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from server.autonomy.daemon import get_daemon
from server.autonomy.state import AutonomyStore

logger = logging.getLogger("aariya.autonomy.router")
router = APIRouter(prefix="/api/autonomy", tags=["autonomy"])


class EnableRequest(BaseModel):
    enabled: bool = True


class GapRequest(BaseModel):
    topic: str
    context: str = ""
    priority: int = 5


@router.get("/state")
async def autonomy_state():
    """Full snapshot of Aariya's inner world (goals, plans, insights...)."""
    return get_daemon().get_inner_world()


@router.post("/enable")
async def set_enabled(req: EnableRequest):
    return get_daemon().set_enabled(req.enabled)


@router.post("/plans/{plan_id}/approve")
async def approve_plan(plan_id: str):
    return await get_daemon().approve_plan(plan_id)


@router.post("/plans/{plan_id}/reject")
async def reject_plan(plan_id: str):
    return await get_daemon().reject_plan(plan_id)


@router.post("/gaps")
async def queue_gap(req: GapRequest):
    """Manually ask Aariya to research something in the background."""
    store = AutonomyStore()
    added = store.add_gap(req.topic, req.context, req.priority)
    if not added:
        return {"ok": False, "error": "gap already queued", "topic": req.topic}
    logger.info("[AutonomyRouter] Gap queued: %s", req.topic)
    return {"ok": True, "topic": req.topic, "priority": req.priority}
