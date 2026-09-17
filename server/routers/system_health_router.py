"""
system_health_router.py
───────────────────────
REST surface for the SystemHealthMonitor — a fetch fallback for the
Analytics Dashboard's System Health tab (the primary path is the
`system_health` frame broadcast over /ws/brain_metrics).

Provides:
  GET /api/system/health          → full health snapshot (server perf +
                                    subsystem checks + auto-discovered
                                    functions + mobile telemetry + score)
  GET /api/system/health/checks   → lightweight summary (score + per-check
                                    status) for status bars / badges
"""

from fastapi import APIRouter

from server.systems.system_health import get_system_health

router = APIRouter(prefix="/api/system", tags=["system-health"])


@router.get("/health")
async def system_health() -> dict:
    """Full snapshot — same payload shape as the broadcast frame's `data`.

    Async so FastAPI runs it on the event loop: the 2 s broadcast loop also
    lives there, so the snapshot never races with collect() from a threadpool
    thread.
    """
    return get_system_health().snapshot()


@router.get("/health/checks")
async def system_health_checks() -> dict:
    """Compact checks-only summary for lightweight consumers."""
    snap = get_system_health().snapshot()
    return {
        "score": snap.get("score"),
        "ts": snap.get("ts"),
        "checks": [
            {"name": c.get("name"), "label": c.get("label"),
             "status": c.get("status"), "detail": c.get("detail")}
            for c in snap.get("checks", [])
        ],
        "mobile_connected": bool(snap.get("mobile", {}).get("connected")),
        "function_count": len(snap.get("functions", [])),
    }
