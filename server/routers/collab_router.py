"""
Real-Time Collaboration API (AccessFIles §75).

REST:
  GET    /api/collab/workspaces            — real workspace summaries
  POST   /api/collab/{name}                — create (idempotent)
  GET    /api/collab/{name}                — full workspace state
  POST   /api/collab/{name}/join           — participant joins
  POST   /api/collab/{name}/heartbeat      — presence heartbeat
  POST   /api/collab/{name}/leave          — participant leaves
  POST   /api/collab/{name}/notes          — post shared note
  POST   /api/collab/{name}/tasks          — add shared task
  PATCH  /api/collab/{name}/tasks/{tid}    — flip task open/done
  POST   /api/collab/{name}/merge          — merge a peer workspace envelope

WebSocket:
  WS     /ws/collab/{name}?participant=X   — live updates: join/note/task
                                            events broadcast to every
                                            connected client in that room.
"""

import asyncio
import json
import logging
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.collab_router")

router = APIRouter(prefix="/api/collab", tags=["collaboration"])

# Per-workspace live connections for the WebSocket rooms.
_rooms: Dict[str, set] = {}
_room_locks_lock = asyncio.Lock()


def _room(slug: str) -> set:
    return _rooms.setdefault(slug, set())


async def _broadcast(slug: str, payload: Dict[str, Any]) -> None:
    """Fan a real state-change event out to every client in the room."""
    dead: List[WebSocket] = []
    message = json.dumps(payload)
    for ws in list(_room(slug)):
        try:
            await ws.send_text(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _room(slug).discard(ws)


class ParticipantBody(BaseModel):
    participant: str


class NoteBody(BaseModel):
    author: str
    text: str


class TaskBody(BaseModel):
    author: str
    text: str


class TaskPatch(BaseModel):
    status: Optional[str] = None


class MergeBody(BaseModel):
    workspaces: List[dict]


@router.get("/workspaces")
async def workspaces():
    from server.systems.collaboration.shared_workspace import get_workspace_store

    return {"ok": True, "workspaces": get_workspace_store().list()}


@router.post("/{name}")
async def create_workspace(name: str, body: ParticipantBody):
    from server.systems.collaboration.shared_workspace import get_workspace_store

    ws = get_workspace_store().create(name, body.participant or "owner")
    return {"ok": True, "workspace": get_workspace_store().summary(ws)}


@router.get("/{name}")
async def workspace_state(name: str):
    from server.systems.collaboration.shared_workspace import get_workspace_store

    ws = get_workspace_store().get(name)
    if ws is None:
        raise HTTPException(status_code=404, detail="no such workspace")
    return {"ok": True, "workspace": ws}


async def _mutate(name: str, fn, event_type: str) -> Dict[str, Any]:
    """Run a store mutation; on success broadcast the real result to the room."""
    result = fn()
    if result is None:
        raise HTTPException(status_code=404, detail="no such workspace")
    await _broadcast(_slug_of(name), {
        "type": event_type,
        "data": result,
        "workspace": name,
    })
    return {"ok": True, **(result if isinstance(result, dict) else {"item": result})}


def _slug_of(name: str) -> str:
    from server.systems.collaboration.shared_workspace import _slug

    return _slug(name)


@router.post("/{name}/join")
async def join(name: str, body: ParticipantBody):
    return await _mutate(
        name,
        lambda: get_store().join(name, body.participant),
        "collab.join",
    )


def get_store():
    from server.systems.collaboration.shared_workspace import get_workspace_store

    return get_workspace_store()


@router.post("/{name}/heartbeat")
async def heartbeat(name: str, body: ParticipantBody):
    ok = get_store().heartbeat(name, body.participant)
    if not ok:
        raise HTTPException(status_code=404, detail="not a participant")
    return {"ok": True}


@router.post("/{name}/leave")
async def leave(name: str, body: ParticipantBody):
    ok = get_store().leave(name, body.participant)
    if not ok:
        raise HTTPException(status_code=404, detail="not a participant")
    await _broadcast(_slug_of(name), {"type": "collab.leave",
                                      "participant": body.participant})
    return {"ok": True}


@router.post("/{name}/notes")
async def post_note(name: str, body: NoteBody):
    note = get_store().post_note(name, body.author, body.text)
    if note is None:
        raise HTTPException(status_code=404, detail="no such workspace")
    await _broadcast(_slug_of(name), {"type": "collab.note", "data": note})
    return {"ok": True, "note": note}


@router.post("/{name}/tasks")
async def add_task(name: str, body: TaskBody):
    task = get_store().add_task(name, body.author, body.text)
    if task is None:
        raise HTTPException(status_code=404, detail="no such workspace")
    await _broadcast(_slug_of(name), {"type": "collab.task", "data": task})
    return {"ok": True, "task": task}


@router.patch("/{name}/tasks/{task_id}")
async def patch_task(name: str, task_id: str, body: TaskPatch):
    task = get_store().update_task(name, task_id, status=body.status)
    if task is None:
        raise HTTPException(status_code=404, detail="no such task")
    await _broadcast(_slug_of(name), {"type": "collab.task.update", "data": task})
    return {"ok": True, "task": task}


@router.post("/{name}/merge")
async def merge_envelope(name: str, body: MergeBody):
    counts = get_store().import_envelope(body.workspaces)
    await _broadcast(_slug_of(name), {"type": "collab.merge", "counts": counts})
    return {"ok": True, **counts}


# ── Live room channel ─────────────────────────────────────────────────────────
# Separate router because /ws/* must not carry the /api/collab prefix.

ws_router = APIRouter()


@ws_router.websocket("/ws/collab/{name}")
async def collab_room(ws: WebSocket, name: str, participant: str = "guest"):
    """Live collaboration room: join/leave/note/task events for this workspace.

    On connect the client is registered as a real participant (store-level)
    so presence survives disconnects until an explicit leave."""
    from server.systems.collaboration.shared_workspace import get_workspace_store

    store = get_workspace_store()
    slug = _slug_of(name)
    if store.get(slug) is None:
        await ws.close(code=4404)
        return

    await ws.accept()
    _room(slug).add(ws)
    joined = store.join(slug, participant)
    if joined:
        await _broadcast(slug, {"type": "collab.join",
                                "participant": participant})
    try:
        while True:
            # Client → server frames are heartbeats only; content flows via
            # the REST endpoints so every mutation persists exactly once.
            raw = await ws.receive_text()
            try:
                frame = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if frame.get("type") == "heartbeat":
                store.heartbeat(slug, participant)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("[collab] ws %s error: %s", name, exc)
    finally:
        _room(slug).discard(ws)
