"""
Real event-log feed for light clients (mobile Companion strip).

The dashboard's Event Log receives events live over /ws/brain_metrics; the
phone has no such socket. This endpoint exposes the SAME real events — the
signal bus's 1000-entry ring of actual autonomy / governance / brain actions
(never synthetic) — over plain REST so the mobile app can poll a compact
strip of the latest activity between turns.

The response shape mirrors what the dashboard derives from each signal:
  { "events": [ { id, ts, tag, text, severity }, ... ] }  (newest first)
"""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("/latest")
async def events_latest(
    limit: int = Query(12, ge=1, le=50),
    sources: str = Query("", description="Comma-separated tag filter, e.g. DAEMON,PLANNER,GOVERNANCE; empty = all"),
) -> Dict[str, Any]:
    """Return the most recent REAL events from the signal-bus ring.

    Events are only ever produced by genuine system actions (daemon proactive
    moments, planner goals/plans, learning cycles, model retrains, governance
    consent/age-band/personality changes, brain/mobile turns). Nothing here is
    fabricated on request — an empty list simply means nothing has happened yet
    since boot.

    The optional `sources` filter lets light clients scope their strip (e.g.
    the phone's Companion view asks for autonomy + governance tags only);
    empty sources means no filter, mirroring the dashboard Event Log.
    """
    from server.systems.signal_bus import bus

    # Direct calls (tests) don't get FastAPI's Query-default resolution.
    if not isinstance(sources, str):
        sources = ""
    wanted = {s.strip().upper() for s in sources.split(",") if s.strip()}
    events: List[Dict[str, Any]] = []
    for sig in reversed(bus.active_signals):
        source = sig.get("source") or {}
        tag = str(source.get("system") or "SYSTEM").upper()
        if wanted and tag not in wanted:
            continue
        payload = sig.get("payload") or {}
        text = payload.get("title") or sig.get("type") or "Event"
        events.append({
            "id": sig.get("id", ""),
            "ts": sig.get("timestamp"),
            "tag": tag,
            "text": str(text),
            "severity": str(sig.get("severity") or "info"),
        })
        if len(events) >= limit:
            break
    return {"events": events}
