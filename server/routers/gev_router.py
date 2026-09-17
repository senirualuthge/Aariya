"""
gev_router.py
─────────────
FastAPI router for God's Eye View (GEV) geospatial intelligence.

Mounts at:  /api/gev
Requires:   GEV dev server running (default: http://localhost:4173)
            Configure via env: GEV_BASE_URL

REST endpoints:
  GET  /api/gev/status              — GEV server health check
  POST /api/gev/manual-refresh      — trigger on-demand fetch (dashboard button)

  Original layers:
    GET  /api/gev/flights             — live aircraft (?lat=&lon=&radius_km=)
    GET  /api/gev/vessels             — AIS vessels (?lat=&lon=&radius_km=)
    GET  /api/gev/fires               — NASA FIRMS (?lat=&lon=)
    GET  /api/gev/earthquakes         — USGS seismic (last 24 h)
    GET  /api/gev/satellites          — TLE-propagated satellite positions
    GET  /api/gev/iss-pass            — ISS next pass (?lat=&lon=)

  New environmental layers:
    GET  /api/gev/weather             — severe weather / storms (?lat=&lon=)
    GET  /api/gev/radar               — live precipitation radar (?lat=&lon=&radius_km=)
    GET  /api/gev/aqi                 — air quality index (?lat=&lon=&radius_km=)
    GET  /api/gev/volcanoes           — active volcanic eruptions

  New human/infrastructure layers:
    GET  /api/gev/power-outages       — grid failures / blackouts (?lat=&lon=&radius_km=)
    GET  /api/gev/traffic             — highway congestion / incidents
    GET  /api/gev/transit             — public transit tracking (?lat=&lon=&radius_km=)

  Space & astronomy:
    GET  /api/gev/space-weather       — solar flares / geomagnetic storms
    GET  /api/gev/neos                — near-Earth objects

  Composite:
    GET  /api/gev/snapshot            — all layers combined
    POST /api/gev/snapshot-diff       — diff between consecutive snapshots

  DVR / Timeline:
    GET  /api/gev/timeline            — historical snapshots (?since_ts=&limit=)
    GET  /api/gev/playback            — closest snapshot to target_ts

WebSocket:
  WS   /api/gev/stream               — live push of full snapshots every 30 s
  WS   /api/gev/stream-diff          — live push of diffs only (bandwidth-efficient)

No mock/synthetic data is produced. When GEV is offline every endpoint
returns {"available": false, "reason": "gev_offline"}.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from server.systems.gev.gev_client import get_gev_client, BoundingBox
from server.systems.gev.gev_agent import get_gev_agent
from server.systems.world_model.world_state import get_world_state

logger = logging.getLogger("aariya.gev_router")
router = APIRouter(prefix="/api/gev", tags=["GEV Intelligence"])

# ── WebSocket fan-out ─────────────────────────────────────────────────────────

_ws_clients: set[WebSocket] = set()
_ws_diff_clients: set[WebSocket] = set()
_stream_task: asyncio.Task | None = None
_diff_stream_task: asyncio.Task | None = None


async def _fanout(payload: dict, targets: set[WebSocket] | None = None) -> None:
    """Send a payload to all connected WebSocket clients."""
    targets = targets or _ws_clients
    text = json.dumps(payload)
    stale: list[WebSocket] = []
    for ws in list(targets):
        try:
            await ws.send_text(text)
        except Exception:
            stale.append(ws)
    for ws in stale:
        targets.discard(ws)


async def _stream_loop() -> None:
    """Push a GEV snapshot to all WS clients on-demand.

    ⚡ Power-saving: no background timer.  The snapshot is fetched once
    when the first client connects (via the /stream endpoint), then again
    only when a new client connects and enough time has passed.
    """
    while _ws_clients:
        try:
            await get_gev_agent().refresh()
            cached = {
                k: get_world_state().get("environment", f"gev_{k}")
                for k in [
                    "flights", "vessels", "fires", "earthquakes", "satellites",
                    "weather", "radar", "aqi", "volcanoes",
                    "power_outages", "traffic", "transit",
                    "space_weather", "neos",
                ]
            }
            cached_valid = {k: v for k, v in cached.items() if v is not None}
            if _ws_clients and cached_valid:
                await _fanout({"type": "gev_snapshot", "source": "on_demand", "data": cached_valid})
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[GEV stream] error: %s", exc)
        await asyncio.sleep(get_gev_agent().MIN_REFRESH_INTERVAL)


async def _diff_stream_loop() -> None:
    """Push GEV diffs (only changes) to diff-mode WebSocket clients.

    Same power-saving design: fetches on-demand when clients are connected.
    """
    while _ws_diff_clients:
        try:
            diff = await get_gev_agent().refresh_diff()
            if _ws_diff_clients:
                await _fanout({"type": "gev_diff", "source": "on_demand", "data": diff}, _ws_diff_clients)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[GEV diff-stream] error: %s", exc)
        await asyncio.sleep(get_gev_agent().MIN_REFRESH_INTERVAL)


def _ensure_stream() -> None:
    global _stream_task
    if _stream_task is None or _stream_task.done():
        try:
            loop = asyncio.get_event_loop()
            _stream_task = loop.create_task(_stream_loop(), name="gev-ws-stream")
        except RuntimeError:
            pass


def _ensure_diff_stream() -> None:
    global _diff_stream_task
    if _diff_stream_task is None or _diff_stream_task.done():
        try:
            loop = asyncio.get_event_loop()
            _diff_stream_task = loop.create_task(_diff_stream_loop(), name="gev-ws-diff-stream")
        except RuntimeError:
            pass


# ── Helper: parse optional bounding box from query params ─────────────────────

def _parse_bbox(
    min_lat: Optional[float] = None,
    max_lat: Optional[float] = None,
    min_lon: Optional[float] = None,
    max_lon: Optional[float] = None,
) -> BoundingBox | None:
    """If all four bbox params are provided, return a BoundingBox."""
    if min_lat is not None and max_lat is not None and min_lon is not None and max_lon is not None:
        return BoundingBox(
            min_lat=min_lat,
            max_lat=max_lat,
            min_lon=min_lon,
            max_lon=max_lon,
        )
    return None


# ── REST endpoints ────────────────────────────────────────────────────────────

@router.get("/status")
async def gev_status():
    """Check whether the GEV server is reachable."""
    return await get_gev_client().status()


@router.post("/manual-refresh")
async def gev_manual_refresh():
    """Trigger an on-demand GEV data fetch from the dashboard.

    Returns the fresh snapshot.  Respects the agent's MIN_REFRESH_INTERVAL
    (30 s) so rapid button clicks don't hammer the GEV server.
    """
    snap = await get_gev_agent().refresh()
    cached_valid = {k: v for k, v in snap.items() if isinstance(v, dict) and v.get("available") is not False}
    if _ws_clients and cached_valid:
        await _fanout({"type": "gev_snapshot", "source": "manual_refresh", "data": cached_valid})
    return {"source": "manual_refresh", "data": snap, "ws_broadcast": bool(_ws_clients)}


# ── Original layer endpoints ──────────────────────────────────────────────────

@router.get("/flights")
async def gev_flights(
    lat: Optional[float] = Query(None, description="Centre latitude"),
    lon: Optional[float] = Query(None, description="Centre longitude"),
    radius_km: float = Query(250, description="Search radius in kilometres"),
    min_lat: Optional[float] = Query(None),
    max_lat: Optional[float] = Query(None),
    min_lon: Optional[float] = Query(None),
    max_lon: Optional[float] = Query(None),
):
    """Live aircraft from OpenSky via the GEV proxy."""
    bbox = _parse_bbox(min_lat, max_lat, min_lon, max_lon)
    return await get_gev_client().flights(lat=lat, lon=lon, radius_km=radius_km, bbox=bbox)


@router.get("/vessels")
async def gev_vessels(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    radius_km: float = Query(200),
    min_lat: Optional[float] = Query(None),
    max_lat: Optional[float] = Query(None),
    min_lon: Optional[float] = Query(None),
    max_lon: Optional[float] = Query(None),
):
    """Live AIS vessels from AISStream via the GEV proxy."""
    bbox = _parse_bbox(min_lat, max_lat, min_lon, max_lon)
    return await get_gev_client().vessels(lat=lat, lon=lon, radius_km=radius_km, bbox=bbox)


@router.get("/fires")
async def gev_fires(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
):
    """NASA FIRMS active fire detections via the GEV proxy."""
    return await get_gev_client().fires(lat=lat, lon=lon)


@router.get("/earthquakes")
async def gev_earthquakes():
    """USGS seismic events from the last 24 hours via the GEV proxy."""
    return await get_gev_client().earthquakes()


@router.get("/satellites")
async def gev_satellites():
    """TLE-propagated live satellite positions via the GEV proxy."""
    return await get_gev_client().satellites()


@router.get("/iss-pass")
async def gev_iss_pass(
    lat: float = Query(..., description="Observer latitude"),
    lon: float = Query(..., description="Observer longitude"),
):
    """Next ISS pass window for a geographic coordinate."""
    return await get_gev_client().iss_pass(lat=lat, lon=lon)


# ── New environmental layer endpoints ─────────────────────────────────────────

@router.get("/weather")
async def gev_weather(
    lat: Optional[float] = Query(None, description="Centre latitude"),
    lon: Optional[float] = Query(None, description="Centre longitude"),
):
    """Severe weather & storm tracking (NOAA/NWS via GEV proxy)."""
    return await get_gev_client().weather(lat=lat, lon=lon)


@router.get("/radar")
async def gev_radar(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    radius_km: float = Query(500),
):
    """Live precipitation radar data (Rainviewer via GEV proxy)."""
    return await get_gev_client().radar(lat=lat, lon=lon, radius_km=radius_km)


@router.get("/aqi")
async def gev_aqi(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    radius_km: float = Query(300),
):
    """Air Quality Index data (WAQI / OpenAQ via GEV proxy)."""
    return await get_gev_client().aqi(lat=lat, lon=lon, radius_km=radius_km)


@router.get("/volcanoes")
async def gev_volcanoes():
    """Active volcanic eruptions and ash advisories via the GEV proxy."""
    return await get_gev_client().volcanoes()


# ── New human/infrastructure layer endpoints ───────────────────────────────────

@router.get("/power-outages")
async def gev_power_outages(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    radius_km: float = Query(500),
):
    """Major regional grid failures / blackouts via the GEV proxy."""
    return await get_gev_client().power_outages(lat=lat, lon=lon, radius_km=radius_km)


@router.get("/traffic")
async def gev_traffic(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    radius_km: float = Query(200),
    min_lat: Optional[float] = Query(None),
    max_lat: Optional[float] = Query(None),
    min_lon: Optional[float] = Query(None),
    max_lon: Optional[float] = Query(None),
):
    """Live traffic and incidents via the GEV proxy."""
    bbox = _parse_bbox(min_lat, max_lat, min_lon, max_lon)
    return await get_gev_client().traffic(lat=lat, lon=lon, radius_km=radius_km, bbox=bbox)


@router.get("/transit")
async def gev_transit(
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    radius_km: float = Query(100),
):
    """Public transit tracking via GTFS-RT feeds via the GEV proxy."""
    return await get_gev_client().transit(lat=lat, lon=lon, radius_km=radius_km)


# ── Space & astronomy endpoints ───────────────────────────────────────────────

@router.get("/space-weather")
async def gev_space_weather():
    """Solar flare alerts and geomagnetic storm tracking via the GEV proxy."""
    return await get_gev_client().space_weather()


@router.get("/neos")
async def gev_neos():
    """Near-Earth Objects currently passing close to Earth via the GEV proxy."""
    return await get_gev_client().neos()


# ── Composite snapshot endpoints ──────────────────────────────────────────────

@router.get("/snapshot")
async def gev_snapshot():
    """Combined snapshot across all GEV layers.

    Fetches on-demand via the agent (deduplicated, cached for 30 s).
    Falls back to WorldState cache when GEV is offline.
    """
    snap = await get_gev_agent().refresh()

    world = get_world_state()
    any_live = any(
        not v.get("available") is False
        for v in snap.values()
        if isinstance(v, dict)
    )
    if not any_live:
        cached = {
            k: world.get("environment", f"gev_{k}")
            for k in [
                "flights", "vessels", "fires", "earthquakes", "satellites",
                "weather", "radar", "aqi", "volcanoes",
                "power_outages", "traffic", "transit",
                "space_weather", "neos",
            ]
        }
        cached_valid = {k: v for k, v in cached.items() if v is not None}
        if cached_valid:
            return {
                "source": "world_state_cache",
                "last_poll": world.get("environment", "gev_last_poll"),
                "data": cached_valid,
            }

    return {"source": "live", "data": snap}


@router.post("/snapshot-diff")
async def gev_snapshot_diff():
    """Compute and return a diff between the current and previous snapshot.

    Only items that were added, removed, or updated are included.
    """
    diff = await get_gev_agent().refresh_diff()
    return {"source": "live_diff", "data": diff}


# ── DVR / Timeline endpoints ──────────────────────────────────────────────────

@router.get("/timeline")
async def gev_timeline(
    since_ts: Optional[float] = Query(None, description="Only return snapshots after this Unix timestamp"),
    limit: int = Query(60, description="Maximum number of snapshots to return"),
):
    """Retrieve historical snapshots for DVR playback.

    Returns a list of {"timestamp": float, "snapshot": dict} objects.
    """
    return {
        "data": get_gev_agent().get_timeline(since_ts=since_ts, limit=limit),
        "timeline_length": get_gev_agent().timeline_length,
        "oldest": get_gev_agent().timeline_oldest,
        "newest": get_gev_agent().timeline_newest,
    }


@router.get("/playback")
async def gev_playback(
    target_ts: float = Query(..., description="Unix timestamp to find the closest snapshot"),
):
    """Find and return the snapshot closest to a target timestamp."""
    snap = get_gev_agent().get_snapshot_at(target_ts)
    if snap is None:
        return {"error": "No snapshots available in the timeline"}
    return {"source": "playback", "target_ts": target_ts, "data": snap}


# ── WebSocket endpoints ───────────────────────────────────────────────────────

@router.websocket("/stream")
async def gev_stream(ws: WebSocket):
    """
    WebSocket: push GEV snapshots on-demand to connected clients.

    ⚡ Power-saving: triggers a fresh fetch when a client connects
    (if the agent's cache is stale), then streams periodic refreshes
    only while clients are connected.
    """
    await ws.accept()
    _ws_clients.add(ws)
    logger.info("[GEV WS] client connected (%d total)", len(_ws_clients))

    # On-demand refresh — the agent deduplicates and caches for 30 s
    try:
        await get_gev_agent().refresh()
    except Exception:
        pass

    # Send current snapshot immediately
    world = get_world_state()
    cached = {
        k: world.get("environment", f"gev_{k}")
        for k in [
            "flights", "vessels", "fires", "earthquakes", "satellites",
            "weather", "radar", "aqi", "volcanoes",
            "power_outages", "traffic", "transit",
            "space_weather", "neos",
        ]
    }
    cached = {k: v for k, v in cached.items() if v is not None}
    if cached:
        try:
            await ws.send_text(json.dumps({
                "type": "gev_snapshot",
                "source": "on_demand",
                "data": cached,
            }))
        except Exception:
            pass

    _ensure_stream()

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_clients.discard(ws)
        logger.info("[GEV WS] client disconnected (%d remaining)", len(_ws_clients))


@router.websocket("/stream-diff")
async def gev_diff_stream(ws: WebSocket):
    """
    WebSocket: push GEV diffs (only changes) to connected clients.

    ⚡ Bandwidth-efficient: only sends items that were added, removed,
    or updated since the last snapshot, rather than the full payload.
    """
    await ws.accept()
    _ws_diff_clients.add(ws)
    logger.info("[GEV WS-DIFF] client connected (%d total)", len(_ws_diff_clients))

    # Send an initial full snapshot as context
    try:
        diff = await get_gev_agent().refresh_diff()
        await ws.send_text(json.dumps({
            "type": "gev_diff",
            "source": "initial",
            "data": diff,
        }))
    except Exception:
        pass

    _ensure_diff_stream()

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _ws_diff_clients.discard(ws)
        logger.info("[GEV WS-DIFF] client disconnected (%d remaining)", len(_ws_diff_clients))
