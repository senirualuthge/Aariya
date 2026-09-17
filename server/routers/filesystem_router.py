"""
Filesystem Router — REST surface for the local-access stack (AccessFIles §1-§17).

Every endpoint operates on REAL disk state through the guarded FileSystemAgent
and the SafetyGovernor (audit journal + rollback). Mutating operations
(write / append / delete) and sandboxed code runs NEVER execute immediately:
they queue in fs_pending_actions (SQLite) until the user explicitly confirms
via /api/fs/pending/{id}/confirm. Denials are journaled too.

  GET  /api/fs/roots              → allowed roots from the safety policy
  GET  /api/fs/list               → directory listing (guarded)
  GET  /api/fs/read               → file contents, text (guarded)
  GET  /api/fs/search             → bounded filename search under a root
  GET  /api/fs/semantic           → semantic search over indexed documents
  GET  /api/fs/drives             → real disk partitions (psutil)
  GET  /api/fs/index/status       → background indexer/watcher status
  POST /api/fs/write|append|delete→ queues a gated action, returns pending id
  POST /api/fs/open               → open with OS default (audited)
  GET  /api/fs/pending            → queued actions awaiting confirmation
  POST /api/fs/pending/{id}/confirm | /cancel
  GET  /api/fs/audit              → recent journal entries
  POST /api/fs/rollback           → undo last n audited mutations
  POST /api/sandbox/run           → queued sandboxed Python execution
  GET  /api/vision/screen         → on-demand screenshot saved to disk
  GET  /api/vision/screen/text    → OCR of the current screen
"""

import asyncio
import logging
import os
import time
from typing import Optional

logger = logging.getLogger("aariya.filesystem_router")

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server.safety.filesystem_guard import allowed_roots
from server.safety.governor import get_safety_governor
from server.safety.pending_actions import get_pending_action_store
from server.systems.filesystem.access_events import tracked
from server.systems.filesystem.filesystem_agent import FileSystemAgent

logger = logging.getLogger("aariya.fs.router")
router = APIRouter(prefix="/api", tags=["filesystem"])

_agent: Optional[FileSystemAgent] = None


def _fs() -> FileSystemAgent:
    global _agent
    if _agent is None:
        _agent = FileSystemAgent()
    return _agent


def _governor():
    return get_safety_governor()


# ── Request models ────────────────────────────────────────────────────────────

class WriteRequest(BaseModel):
    path: str
    content: str
    actor: str = "ai"


class AppendRequest(WriteRequest):
    pass


class DeleteRequest(BaseModel):
    path: str
    actor: str = "ai"


class OpenRequest(BaseModel):
    path: str


class RollbackRequest(BaseModel):
    n: int = 1


class SandboxRequest(BaseModel):
    code: str
    actor: str = "ai"


# ── Read-only endpoints ───────────────────────────────────────────────────────

@router.get("/fs/roots")
async def fs_roots():
    return {"roots": allowed_roots()}


@router.get("/fs/list")
async def fs_list(path: str):
    async with tracked("list_directory", [path]):
        try:
            return {"path": path, "entries": _fs().list_directory(path)}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)[:200])


@router.get("/fs/read")
async def fs_read(path: str):
    async with tracked("read_file", [path]):
        content = _fs().read_file(path)
        if content == "File not accessible.":
            _governor().record_denial("read_file", path, "guard rejected or missing")
            raise HTTPException(status_code=403, detail="path not allowed by filesystem guard")
        return {"path": path, "content": content}


@router.get("/fs/search")
async def fs_search(root: str, query: str, limit: int = 50):
    async with tracked("search_files", [root]):
        matches = _fs().search_files(root, query, max_results=max(1, min(limit, 200)))
        return {"root": root, "query": query, "matches": matches, "count": len(matches)}


@router.get("/fs/semantic")
async def fs_semantic(query: str, k: int = 5):
    """Semantic search over the live document index built by the watcher."""
    async with tracked("semantic_search", []):
        try:
            from server.systems.filesystem.background_service import get_filesystem_service
            svc = get_filesystem_service()
            indexer = getattr(svc, "_indexer", None)
            if indexer is None:
                raise HTTPException(status_code=503, detail="indexer unavailable (deps missing?)")
            results = indexer.semantic_search(query, top_k=max(1, min(k, 20)))
            return {"query": query, **results}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)[:200])


@router.get("/fs/drives")
async def fs_drives():
    try:
        from server.systems.filesystem.drive_monitor import detect_external_drives
        return {"drives": detect_external_drives()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:200])


@router.get("/fs/index/status")
async def fs_index_status():
    from server.systems.filesystem.background_service import get_filesystem_service
    return get_filesystem_service().status()


# ── Gated mutations (queue → confirm) ────────────────────────────────────────

def _queue(action: str, path: str, content: str, actor: str) -> dict:
    store = get_pending_action_store()
    row = store.create(action, path=path, content=content, actor=actor)
    if row is None:
        raise HTTPException(status_code=400, detail=f"action not queueable: {action}")
    logger.info("[fs-router] queued %s %s (id=%s, actor=%s)", action, path, row["id"], actor)
    return {
        "ok": True,
        "pending_id": row["id"],
        "action": action,
        "path": path,
        "status": "pending",
        "note": "queued — call /api/fs/pending/{pending_id}/confirm to execute",
    }


@router.post("/fs/write")
async def fs_write(req: WriteRequest):
    return _queue("write_file", req.path, req.content, req.actor)


@router.post("/fs/append")
async def fs_append(req: AppendRequest):
    return _queue("append_file", req.path, req.content, req.actor)


@router.post("/fs/delete")
async def fs_delete(req: DeleteRequest):
    return _queue("delete_file", req.path, "", req.actor)


@router.post("/fs/open")
async def fs_open(req: OpenRequest):
    gov = _governor()
    ok = gov.open_path(req.path, actor="user")
    if not ok:
        gov.record_denial("open_path", req.path, "guard rejected or launch failed")
        raise HTTPException(status_code=400, detail="could not open path (guard rejected or launch failed)")
    return {"ok": True, "path": req.path}


# ── Confirmation gate ─────────────────────────────────────────────────────────

@router.get("/fs/pending")
async def pending_list(status: str = "pending"):
    return {"actions": get_pending_action_store().list(status=status)}


async def _resolve_pending(action_id: str, execute: bool) -> dict:
    store = get_pending_action_store()
    row = store.get(action_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown pending action id")
    if not execute:
        resolved = store.resolve(action_id, "cancelled")
        if resolved is None:
            raise HTTPException(status_code=409, detail="action is no longer pending")
        _governor().record_denial(row["action"], row.get("path") or "",
                                  "cancelled by user")
        return {"ok": True, "id": action_id, "status": "cancelled"}

    # Confirm: run the real mutation through the governor (audited + reversible).
    gov = _governor()
    action, path = row["action"], row.get("path") or ""
    content = row.get("content") or ""
    try:
        if action == "write_file":
            ok = gov.write_file(path, content, confirmed=True, actor=row.get("actor", "user"))
        elif action == "append_file":
            ok = gov.append_file(path, content, confirmed=True, actor=row.get("actor", "user"))
        elif action == "delete_file":
            ok = gov.delete_file(path, confirmed=True, actor=row.get("actor", "user"))
        elif action == "run_code":
            from server.systems.sandbox.code_executor import SandboxedExecutor
            async with tracked("run_code", ["<sandbox workdir>"],
                               actor=row.get("actor", "user")):
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: SandboxedExecutor().execute_python(content))
            ok = result.get("returncode") == 0
            resolved = store.resolve(
                action_id, "executed" if ok else "failed",
                result=f"rc={result.get('returncode')} out={str(result.get('stdout', ''))[:200]}",
            )
            if resolved is None:
                raise HTTPException(status_code=409, detail="action is no longer pending")
            return {"ok": ok, "id": action_id, "status": resolved["status"],
                    "result": result}
        else:
            raise HTTPException(status_code=400, detail=f"unknown action: {action}")
    except PermissionError as exc:
        resolved = store.resolve(action_id, "failed", result=str(exc)[:300])
        _governor().record_denial(action, path, str(exc))
        return {"ok": False, "id": action_id, "status": "failed",
                "error": str(exc)[:200]}
    except Exception as exc:
        store.resolve(action_id, "failed", result=str(exc)[:300])
        raise HTTPException(status_code=500, detail=str(exc)[:200])

    resolved = store.resolve(action_id, "executed" if ok else "failed")
    if resolved is None:
        raise HTTPException(status_code=409, detail="action is no longer pending")
    return {"ok": ok, "id": action_id, "status": resolved["status"]}


@router.post("/fs/pending/{action_id}/confirm")
async def pending_confirm(action_id: str):
    return await _resolve_pending(action_id, execute=True)


@router.post("/fs/pending/{action_id}/cancel")
async def pending_cancel(action_id: str):
    return await _resolve_pending(action_id, execute=False)


# ── Audit + rollback ──────────────────────────────────────────────────────────

@router.get("/fs/audit")
async def fs_audit(limit: int = 50):
    gov = _governor()
    entries = gov.audit_log(limit=max(1, min(limit, 500)))
    return {"entries": entries, "count": len(entries), "journal": gov.status()["journal"]}


@router.post("/fs/rollback")
async def fs_rollback(req: RollbackRequest):
    return _governor().rollback(max(1, min(req.n, 50)))


# ── Sandboxed execution (gated like every other mutation) ────────────────────

@router.get("/sandbox/status")
async def sandbox_status():
    """§72: which isolation backend this machine can REALLY use right now."""
    from server.systems.sandbox.code_executor import (
        detect_container_runtime, _CONTAINER_IMAGE,
    )
    runtime = detect_container_runtime()
    return {"container_runtime": runtime,
            "image": _CONTAINER_IMAGE if runtime else None,
            "mode": "container" if runtime else "subprocess",
            "network_isolated": bool(runtime)}


@router.post("/sandbox/pull")
async def sandbox_pull():
    """Explicit operator action (§72): pull the sandbox image so container
    runs work offline afterwards. Never called automatically."""
    import asyncio
    from server.systems.sandbox.code_executor import pull_sandbox_image
    return await asyncio.get_event_loop().run_in_executor(None, pull_sandbox_image)


@router.post("/sandbox/run")
async def sandbox_run(req: SandboxRequest):
    return _queue("run_code", "", req.code, req.actor)


# ── Desktop vision (on-demand only — never continuous capture) ────────────────

_SCREENSHOT_DIR = os.path.join("data", "screenshots")


@router.get("/vision/screen")
async def vision_screen():
    async with tracked("screenshot_write", [os.path.join(_SCREENSHOT_DIR, "")]):
        try:
            from server.systems.vision.desktop_vision import DesktopVision
            frame = DesktopVision().capture_screen()
            if frame is None:
                raise HTTPException(status_code=503, detail="screen capture unavailable")
            os.makedirs(_SCREENSHOT_DIR, exist_ok=True)
            out_path = os.path.join(_SCREENSHOT_DIR, f"screen_{int(time.time())}.png")
            import cv2
            cv2.imwrite(out_path, frame)
            return {"ok": True, "path": out_path,
                    "size": [int(frame.shape[1]), int(frame.shape[0])]}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"screen capture failed: {str(exc)[:200]}")


@router.get("/vision/screen/text")
async def vision_screen_text():
    try:
        from server.systems.gui.gui_parser import GUIParser
        text = GUIParser().extract_text()
        return {"ok": True, "text": text[:5000], "chars": len(text)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"screen OCR failed: {str(exc)[:200]}")


class VisionReasonRequest(BaseModel):
    prompt: str = (
        "You are viewing a desktop screenshot. Identify: windows, buttons, "
        "forms, the active application, and possible next actions."
    )


@router.post("/vision/reason")
async def vision_reason(req: VisionReasonRequest):
    """Multimodal screen reasoning (AccessFIles §25): capture the REAL screen,
    send it to a vision-capable model, store the observation in the world
    state. Requires a configured vision endpoint (OPENAI_API_KEY); without one
    this returns 503 rather than pretending to see."""
    import base64

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="no vision model configured (set OPENAI_API_KEY)")

    try:
        from server.systems.vision.desktop_vision import DesktopVision
        frame = DesktopVision().capture_screen()
        import cv2
        ok, buf = cv2.imencode(".png", frame)
        if not ok:
            raise RuntimeError("PNG encode failed")
        image_b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"screen capture failed: {str(exc)[:200]}")

    try:
        import openai
        client = openai.AsyncOpenAI(api_key=api_key)
        response = await client.chat.completions.create(
            model=os.getenv("AARIYA_VISION_MODEL", "gpt-4o"),
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": req.prompt[:1000]},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                ],
            }],
            max_tokens=400,
        )
        observation = (response.choices[0].message.content or "").strip()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"vision model call failed: {str(exc)[:200]}")

    # Sink the real observation into the world state + event log.
    try:
        from server.systems.world_model.world_state import get_world_state
        get_world_state().update_many("system", {
            "last_vision_observation": observation[:1000],
            "last_vision_ts": time.time(),
        })
    except Exception as exc:
        logger.debug("[FilesystemRouter] world state update failed: %s", exc)
    try:
        from server.systems.signal_bus import emit_real_event
        await emit_real_event("VISION", "info",
                              f"Screen observation: {observation[:80]}", None)
    except Exception as exc:
        logger.debug("[FilesystemRouter] vision event emission failed: %s", exc)

    return {"ok": True, "observation": observation}
