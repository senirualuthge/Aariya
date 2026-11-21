"""
self_knowledge_router.py
────────────────────────
FastAPI router exposing Aariya's data-location inventory.

Endpoints:
  GET  /api/self-knowledge              — full data-location inventory (JSON)
  GET  /api/self-knowledge/prompt       — the prompt-injection block text
  POST /api/self-knowledge/refresh      — force a re-scan of the filesystem

Mount in main.py:
  from server.routers.self_knowledge_router import router as self_knowledge_router
  app.include_router(self_knowledge_router)
"""

import logging

from fastapi import APIRouter, Depends

from ..systems.security.device_auth import (
    require_dashboard_device,
    require_personal_device,
)
from ..systems.self_knowledge import get_self_knowledge

logger = logging.getLogger("aariya.self_knowledge_router")
# The data inventory and prompt block describe the owner's machine; refresh
# walks the filesystem, so it stays desktop-only.
router = APIRouter(
    prefix="/api/self-knowledge",
    tags=["Self-Knowledge"],
    dependencies=[Depends(require_personal_device)],
)


@router.get("")
async def get_inventory():
    """Full JSON inventory of every data location (path, kind, size, status)."""
    return get_self_knowledge().inventory_json()


@router.get("/prompt")
async def get_prompt_block():
    """The exact text block injected into Aariya's conversation context."""
    return {"prompt": get_self_knowledge().format_for_prompt()}


@router.post("/refresh")
async def refresh_inventory(_dashboard=Depends(require_dashboard_device)):
    """Force a fresh filesystem scan and return the updated inventory."""
    inventory = get_self_knowledge(refresh=True).inventory_json()
    logger.info("[SelfKnowledge] inventory refreshed via API")
    return inventory
