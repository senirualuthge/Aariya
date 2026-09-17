"""
gev_client.py
─────────────
HTTP client that proxies GEV's live intelligence layers into Aariya.

Design:
  • All calls route through the GEV dev server (localhost:4173 by default)
    so GEV's API key management, rate governors, and caching still apply.
  • When GEV is offline, every method returns {"available": False}.
    No mock/synthetic data is fabricated.
  • GEV_BASE_URL is configurable via the environment variable GEV_BASE_URL
    (default: http://localhost:4173).

Supported endpoints (all return the raw GEV JSON parsed into Python dicts):
  Original layers:
    flights(lat, lon, radius_km)           → aircraft from OpenSky via GEV
    vessels(lat, lon, radius_km)           → AIS vessels from AISStream via GEV
    fires(lat, lon)                        → NASA FIRMS fire detections via GEV
    earthquakes()                          → USGS seismic events via GEV
    satellites()                           → TLE-propagated satellite positions via GEV
    iss_pass(lat, lon)                     → ISS next pass window via GEV
    status()                               → GEV server health check

  New environmental layers:
    weather(lat, lon)                      → severe weather / storm tracking (NOAA/NWS)
    radar(lat, lon, radius_km)             → live precipitation radar (Rainviewer)
    aqi(lat, lon, radius_km)               → air quality index (WAQI / OpenAQ)
    volcanoes()                            → active volcanic eruptions / ash advisories

  New human/infrastructure layers:
    power_outages(lat, lon, radius_km)     → major regional grid failures
    traffic(lat, lon, bbox)                → highway congestion / incidents
    transit(lat, lon, radius_km)           → public transit tracking (GTFS-RT)

  Space & astronomy extensions:
    space_weather()                        → solar flare / geomagnetic storm alerts
    neos()                                 → near-Earth objects passing close

  Architecture:
    snapshot()                             → all layers combined
    snapshot_diff(previous)                → diff between two snapshots
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("aariya.gev_client")

GEV_BASE_URL = os.getenv("GEV_BASE_URL", "http://localhost:4173")
TIMEOUT = 8.0  # seconds — GEV endpoints are fast; fail quickly if server is down


# ── Bounding Box helpers ──────────────────────────────────────────────────────

class BoundingBox:
    """Geographic bounding box for precise viewport-matched queries."""

    __slots__ = ("min_lat", "max_lat", "min_lon", "max_lon")

    def __init__(
        self,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
    ):
        if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
            raise ValueError("Latitude must be in [-90, 90]")
        if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
            raise ValueError("Longitude must be in [-180, 180]")
        if min_lat > max_lat:
            raise ValueError("min_lat must be <= max_lat")
        self.min_lat = min_lat
        self.max_lat = max_lat
        self.min_lon = min_lon
        self.max_lon = max_lon

    def to_params(self) -> dict[str, float]:
        """Return query-string parameters for the GEV proxy."""
        return {
            "min_lat": self.min_lat,
            "max_lat": self.max_lat,
            "min_lon": self.min_lon,
            "max_lon": self.max_lon,
        }

    @classmethod
    def from_center(
        cls,
        lat: float,
        lon: float,
        radius_km: float,
    ) -> "BoundingBox":
        """Create a bounding box from a centre point and radius (approximate)."""
        # 1 degree latitude ≈ 111 km
        dlat = radius_km / 111.0
        # 1 degree longitude varies with latitude
        dlon = radius_km / (111.0 * max(0.01, abs(__import__("math").cos(__import__("math").radians(lat)))))
        return cls(
            min_lat=lat - dlat,
            max_lat=lat + dlat,
            min_lon=lon - dlon,
            max_lon=lon + dlon,
        )

    def __repr__(self) -> str:
        return (
            f"BBox({self.min_lat:.3f},{self.max_lat:.3f} "
            f"{self.min_lon:.3f},{self.max_lon:.3f})"
        )


# ── Snapshot Diff ─────────────────────────────────────────────────────────────

def compute_snapshot_diff(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    *,
    track_ids: bool = True,
) -> dict[str, Any]:
    """Compute a lightweight diff between two GEV snapshots.

    For each layer, the diff includes:
      - added:   list of items present in current but not previous
      - removed: list of items present in previous but not current
      - updated: list of items present in both but with changed fields
      - summary: counts of changes per layer

    When track_ids is True, items are compared by a stable "id" or identity
    field. When False, only presence/absence is tracked (full replacement).

    Returns a diff dict keyed by layer name.
    """
    if previous is None:
        return {
            "type": "full_snapshot",
            "data": current,
            "diff_summary": {k: "new" for k in current},
        }

    diff: dict[str, Any] = {}

    all_layers = set(previous.keys()) | set(current.keys())

    for layer in all_layers:
        prev_data = previous.get(layer)
        curr_data = current.get(layer)

        # Normalise: GEV returns {"available": False} when offline
        prev_items = _extract_items(prev_data)
        curr_items = _extract_items(curr_data)

        if track_ids and prev_items is not None and curr_items is not None:
            added, removed, updated = _diff_item_lists(prev_items, curr_items)
            diff[layer] = {
                "added": added,
                "removed": removed,
                "updated": updated,
                "summary": {
                    "added": len(added),
                    "removed": len(removed),
                    "updated": len(updated),
                },
            }
        elif prev_items is None and curr_items is not None:
            diff[layer] = {"added": curr_items, "removed": [], "updated": [], "summary": {"added": len(curr_items), "removed": 0, "updated": 0}}
        elif prev_items is not None and curr_items is None:
            diff[layer] = {"added": [], "removed": prev_items, "updated": [], "summary": {"added": 0, "removed": len(prev_items), "updated": 0}}
        else:
            diff[layer] = {"added": [], "removed": [], "updated": [], "summary": {"added": 0, "removed": 0, "updated": 0}}

    return {"type": "diff", "data": diff, "diff_summary": {k: v["summary"] for k, v in diff.items()}}


def _extract_items(data: Any) -> list[dict] | None:
    """Extract a list of trackable items from a layer response."""
    if data is None or (isinstance(data, dict) and data.get("available") is False):
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # Some layers wrap items in a key like "features", "entities", "items", "data"
        for key in ("features", "entities", "items", "data", "results"):
            if key in data and isinstance(data[key], list):
                return data[key]
        return None
    return None


def _item_id(item: dict) -> str:
    """Derive a stable identity string from a trackable item."""
    if isinstance(item, dict):
        for key in ("id", "icao24", "mmsi", "callsign", "name", "eventid", "norad_id", "number"):
            if key in item and item[key] is not None:
                return str(item[key])
        # Fallback: hash of the item
        return hashlib.md5(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return hashlib.md5(str(item).encode()).hexdigest()[:12]


def _diff_item_lists(prev: list[dict], curr: list[dict]) -> tuple[list, list, list]:
    """Diff two lists of item dicts by identity, detecting additions, removals, and updates."""
    prev_map = {_item_id(item): item for item in prev}
    curr_map = {_item_id(item): item for item in curr}

    added = [curr_map[k] for k in curr_map if k not in prev_map]
    removed = [prev_map[k] for k in prev_map if k not in curr_map]
    updated = []
    for k in curr_map:
        if k in prev_map:
            if json.dumps(prev_map[k], sort_keys=True, default=str) != json.dumps(curr_map[k], sort_keys=True, default=str):
                updated.append(curr_map[k])

    return added, removed, updated


class GEVClient:
    """Async HTTP client for the GEV intelligence proxy layer."""

    def __init__(self, base_url: str = GEV_BASE_URL):
        self.base = base_url.rstrip("/")

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """Issue a GET and return parsed JSON, or {"available": False} on any error."""
        url = f"{self.base}{path}"
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(url, params=params or {})
                r.raise_for_status()
                return r.json()
        except httpx.ConnectError:
            logger.debug("[GEVClient] GEV server not reachable at %s", url)
            return {"available": False, "reason": "gev_offline"}
        except httpx.TimeoutException:
            logger.warning("[GEVClient] Timeout fetching %s", url)
            return {"available": False, "reason": "timeout"}
        except Exception as exc:
            logger.warning("[GEVClient] Error fetching %s: %s", url, exc)
            return {"available": False, "reason": str(exc)}

    # ── Original layers ───────────────────────────────────────────────────────

    async def status(self) -> dict:
        """Check if the GEV server is running."""
        result = await self._get("/api/status")
        if result.get("available") is False:
            return {"available": False}
        return {"available": True, "detail": result}

    async def flights(
        self,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float = 250,
        bbox: BoundingBox | None = None,
    ) -> dict:
        """Live aircraft from OpenSky (via GEV proxy).

        With bbox: returns aircraft within the precise bounding box.
        With lat/lon: returns aircraft within radius_km.
        Without any: returns globally visible traffic.
        """
        params: dict[str, Any] = {}
        if bbox is not None:
            params.update(bbox.to_params())
        else:
            params["radius_km"] = radius_km
            if lat is not None:
                params["lat"] = lat
            if lon is not None:
                params["lon"] = lon
        return await self._get("/api/flights", params)

    async def vessels(
        self,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float = 200,
        bbox: BoundingBox | None = None,
    ) -> dict:
        """Live AIS vessels (via GEV proxy)."""
        params: dict[str, Any] = {}
        if bbox is not None:
            params.update(bbox.to_params())
        else:
            params["radius_km"] = radius_km
            if lat is not None:
                params["lat"] = lat
            if lon is not None:
                params["lon"] = lon
        return await self._get("/api/vessels", params)

    async def fires(
        self,
        lat: float | None = None,
        lon: float | None = None,
    ) -> dict:
        """NASA FIRMS active fire detections (via GEV proxy)."""
        params: dict[str, Any] = {}
        if lat is not None:
            params["lat"] = lat
        if lon is not None:
            params["lon"] = lon
        return await self._get("/api/fires", params)

    async def earthquakes(self) -> dict:
        """USGS seismic events from the last 24 hours (via GEV proxy)."""
        return await self._get("/api/earthquakes")

    async def satellites(self) -> dict:
        """TLE-propagated live satellite positions (via GEV proxy)."""
        return await self._get("/api/satellites")

    async def iss_pass(self, lat: float, lon: float) -> dict:
        """Next ISS pass window for a geographic coordinate."""
        return await self._get("/api/iss-pass", {"lat": lat, "lon": lon})

    # ── New environmental layers ──────────────────────────────────────────────

    async def weather(
        self,
        lat: float | None = None,
        lon: float | None = None,
    ) -> dict:
        """Severe weather & storm tracking (NOAA/NWS via GEV proxy).

        Returns hurricane/cyclone paths, tornado warnings, and severe weather alerts.
        """
        params: dict[str, Any] = {}
        if lat is not None:
            params["lat"] = lat
        if lon is not None:
            params["lon"] = lon
        return await self._get("/api/weather", params)

    async def radar(
        self,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float = 500,
    ) -> dict:
        """Live precipitation radar data (Rainviewer API via GEV proxy).

        Returns global or regional rain/snow radar tiles and data.
        """
        params: dict[str, Any] = {"radius_km": radius_km}
        if lat is not None:
            params["lat"] = lat
        if lon is not None:
            params["lon"] = lon
        return await self._get("/api/radar", params)

    async def aqi(
        self,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float = 300,
    ) -> dict:
        """Air Quality Index data (WAQI / OpenAQ via GEV proxy).

        Returns real-time global air quality and pollution heatmaps.
        """
        params: dict[str, Any] = {"radius_km": radius_km}
        if lat is not None:
            params["lat"] = lat
        if lon is not None:
            params["lon"] = lon
        return await self._get("/api/aqi", params)

    async def volcanoes(self) -> dict:
        """Active volcanic eruptions and ash advisories (via GEV proxy).

        Complements the USGS earthquake layer with volcanic activity data.
        """
        return await self._get("/api/volcanoes")

    # ── New human/infrastructure layers ───────────────────────────────────────

    async def power_outages(
        self,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float = 500,
    ) -> dict:
        """Major regional grid failures / blackouts (via GEV proxy).

        Tracks large-scale power outages across regions.
        """
        params: dict[str, Any] = {"radius_km": radius_km}
        if lat is not None:
            params["lat"] = lat
        if lon is not None:
            params["lon"] = lon
        return await self._get("/api/power-outages", params)

    async def traffic(
        self,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float = 200,
        bbox: BoundingBox | None = None,
    ) -> dict:
        """Live traffic and incidents (via GEV proxy).

        Returns major highway congestion, accidents, and road closures.
        """
        params: dict[str, Any] = {}
        if bbox is not None:
            params.update(bbox.to_params())
        else:
            params["radius_km"] = radius_km
            if lat is not None:
                params["lat"] = lat
            if lon is not None:
                params["lon"] = lon
        return await self._get("/api/traffic", params)

    async def transit(
        self,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float = 100,
    ) -> dict:
        """Public transit tracking via GTFS-RT feeds (via GEV proxy).

        Live tracking of trains and public transit in major metropolitan areas.
        """
        params: dict[str, Any] = {"radius_km": radius_km}
        if lat is not None:
            params["lat"] = lat
        if lon is not None:
            params["lon"] = lon
        return await self._get("/api/transit", params)

    # ── Space & astronomy extensions ──────────────────────────────────────────

    async def space_weather(self) -> dict:
        """Solar flare alerts and geomagnetic storm tracking (via GEV proxy).

        Data from NOAA Space Weather Prediction Center.
        """
        return await self._get("/api/space-weather")

    async def neos(self) -> dict:
        """Near-Earth Objects currently passing close to Earth (via GEV proxy).

        Data from NASA JPL API.
        """
        return await self._get("/api/neos")

    # ── Composite snapshot ────────────────────────────────────────────────────

    async def snapshot(self) -> dict:
        """Pull a combined real-time world snapshot across ALL layers.

        Returns a dict keyed by layer name. Each value is the raw GEV JSON
        (which may include {"available": False} if GEV is down or a layer
        has no data at this instant).
        """
        import asyncio

        # Fire all layer queries concurrently for a fast snapshot.
        results = await asyncio.gather(
            self.flights(),
            self.vessels(),
            self.fires(),
            self.earthquakes(),
            self.satellites(),
            self.weather(),
            self.radar(),
            self.aqi(),
            self.volcanoes(),
            self.power_outages(),
            self.traffic(),
            self.transit(),
            self.space_weather(),
            self.neos(),
            return_exceptions=True,
        )
        keys = [
            "flights", "vessels", "fires", "earthquakes", "satellites",
            "weather", "radar", "aqi", "volcanoes",
            "power_outages", "traffic", "transit",
            "space_weather", "neos",
        ]
        return {
            k: (v if not isinstance(v, Exception) else {"available": False, "reason": str(v)})
            for k, v in zip(keys, results)
        }

    async def snapshot_diff(
        self,
        previous: dict[str, Any] | None = None,
    ) -> dict:
        """Fetch a fresh snapshot and compute a diff against the previous one.

        If no previous snapshot is provided, returns a full snapshot with
        "type": "full_snapshot".
        """
        current = await self.snapshot()
        return compute_snapshot_diff(previous, current)


# ── Singleton ─────────────────────────────────────────────────────────────────

_client: GEVClient | None = None


def get_gev_client() -> GEVClient:
    global _client
    if _client is None:
        _client = GEVClient()
    return _client
