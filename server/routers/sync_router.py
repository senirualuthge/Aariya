"""
Distributed memory + embodiment API (AccessFIles §61 / §76).

  GET  /api/memory/export        — portable snapshot of real local state
  POST /api/memory/import        — merge a peer's envelope (last-write-wins)
  POST /api/memory/push          — push our envelope to AARIYA_PEER_URLS
  GET  /api/memory/ledger        — real sync history
  GET  /api/embodiment/status    — probe of actually-attached hardware
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["memory-sync", "embodiment"])


# ── §61 Distributed memory ────────────────────────────────────────────────────

@router.get("/memory/export")
async def memory_export():
    from server.systems.memory import sync
    try:
        return {"ok": True, "snapshot": sync.export_snapshot()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:200])


class ImportRequest(BaseModel):
    envelope: dict


@router.post("/memory/import")
async def memory_import(req: ImportRequest):
    from server.systems.memory import sync
    try:
        return sync.import_snapshot(req.envelope)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:200])


@router.post("/memory/push")
async def memory_push():
    from server.systems.memory import sync
    return await _push()


async def _push():
    import asyncio
    from server.systems.memory import sync
    return await asyncio.get_event_loop().run_in_executor(None, sync.push_to_peers)


@router.get("/memory/ledger")
async def memory_ledger(limit: int = 50):
    from server.systems.memory import sync
    entries = sync.read_ledger(limit=max(1, min(limit, 500)))
    return {"entries": entries, "count": len(entries),
            "device": sync.device_id(),
            "peers_configured": len(sync.peer_urls())}


# ── §76 Embodiment ────────────────────────────────────────────────────────────

@router.get("/embodiment/status")
async def embodiment_status():
    from server.systems.embodiment.device_registry import probe_devices
    try:
        import asyncio
        probe = await asyncio.get_event_loop().run_in_executor(
            None, probe_devices)
        return {"ok": True, **probe}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:200])
