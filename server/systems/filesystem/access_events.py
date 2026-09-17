"""
File-access event feed — REAL telemetry for the GUI's file-access panel.

Every local-file operation that flows through the SafetyGovernor (mutations,
opens, rollbacks, denials) or the filesystem router (listings, reads,
searches) emits a `file_access` frame over the shared session broadcast.
Frames carry only real data: the actual operation name, the actual paths
touched, the actual outcome and wall-clock duration.

Frame shape (both phases):
    {"type": "file_access",
     "phase": "start" | "end",
     "id": "<uuid>",            # correlates start/end of one operation
     "op": "read_file",         # governor/router action name
     "paths": ["/abs/path"],    # real paths involved
     "actor": "user"|"ai"|"governor",
     "status": "running"|"executed"|"denied"|"error",   # end frames only
     "duration_ms": 12.3,       # end frames only (real elapsed time)
     "detail": "...",           # optional human-readable outcome note
     "ts": 1720000000.0}

Nothing here fabricates activity: if no file access happens, no frame is
emitted and the GUI panel stays hidden.
"""

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Iterable, List, Optional

logger = logging.getLogger("aariya.fs.events")


def _frame(op: str, paths: Iterable[str], *, phase: str, actor: str,
           event_id: str, status: str = "running", detail: str = "",
           duration_ms: Optional[float] = None) -> dict:
    return {
        "type": "file_access",
        "phase": phase,
        "id": event_id,
        "op": op,
        "paths": [str(p) for p in paths],
        "actor": actor,
        "status": status,
        "detail": str(detail)[:300],
        "duration_ms": round(duration_ms, 1) if duration_ms is not None else None,
        "ts": time.time(),
    }


async def emit_file_access(frame: dict) -> None:
    """Broadcast one real file-access frame to every connected surface.
    Best-effort: a missing/dead session manager never breaks the caller."""
    try:
        from server.infrastructure.session_manager import manager
        await manager.broadcast(frame)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("[fs-events] broadcast skipped: %s", exc)


def notify_sync(op: str, paths: Iterable[str], *, phase: str = "end",
                actor: str = "ai", status: str = "executed",
                detail: str = "", duration_ms: Optional[float] = None) -> str:
    """Fire-and-forget emitter for SYNC code paths (the SafetyGovernor).

    Schedules the broadcast on the running loop when one exists; when called
    from a non-loop thread the frame is dropped with a log line (the audit
    journal still has the authoritative record). Returns the event id so
    callers can correlate phases if they want start/end pairing.
    """
    event_id = uuid.uuid4().hex[:12]
    frame = _frame(op, paths, phase=phase, actor=actor, event_id=event_id,
                   status=status, detail=detail, duration_ms=duration_ms)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("[fs-events] no loop for %s %s — frame dropped", op, paths)
        return event_id
    loop.create_task(emit_file_access(frame))
    return event_id


@asynccontextmanager
async def tracked(op: str, paths: Iterable[str], *, actor: str = "user"):
    """Async context manager for router endpoints: emits a real `start` frame
    before the body runs and a real `end` frame (with measured wall time and
    honest status) after it — including on HTTPException denials and errors.
    """
    event_id = uuid.uuid4().hex[:12]
    path_list: List[str] = list(paths)
    t0 = time.perf_counter()

    await emit_file_access(_frame(op, path_list, phase="start", actor=actor,
                                  event_id=event_id))
    try:
        yield
    except Exception as exc:
        from fastapi import HTTPException
        status = ("denied"
                  if isinstance(exc, HTTPException) and exc.status_code in (400, 403)
                  else "error")
        await emit_file_access(_frame(
            op, path_list, phase="end", actor=actor, event_id=event_id,
            status=status, detail=str(exc)[:200],
            duration_ms=(time.perf_counter() - t0) * 1000))
        raise
    else:
        await emit_file_access(_frame(
            op, path_list, phase="end", actor=actor, event_id=event_id,
            status="executed",
            duration_ms=(time.perf_counter() - t0) * 1000))
