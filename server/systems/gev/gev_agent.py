"""
gev_agent.py
────────────
God's Eye View (GEV) Swarm Agent for Aariya.

Role: Geospatial Intelligence — on-demand agent that fetches GEV's
data layers and writes canonical snapshots into WorldState["environment"]
so the brain, the autonomy daemon, and REST consumers all share one
spatial picture.

⚡ POWER-SAVING DESIGN (no background polling):
  This agent does NOT poll continuously.  It only fetches data when:
    1. The brain explicitly requests it via act(task, ...)
    2. The daemon's learning tick decides geospatial data is needed
    3. A REST consumer hits a /api/gev/* endpoint (client-side)
    4. A WebSocket client connects to /api/gev/stream
  This keeps CPU/network usage at zero when Aariya isn't actively
  learning about the world.

Registry metadata:
  kind:      "geospatial"
  detection: "static"      (not auto-discovered from file scan; explicitly registered)
  capabilities: [full list of supported layers]

Lifecycle:
  get_gev_agent().refresh()         — one-shot fetch + WorldState write (no loop)
  get_gev_agent().refresh_diff()    — fetch + diff-aware WorldState write
  get_gev_agent().act(task)         — one-shot task handler for the brain
  get_gev_agent().get_timeline()    — retrieve historical snapshots (DVR mode)
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from typing import Any

from server.systems.swarm.agents.base import Agent
from server.systems.gev.gev_client import get_gev_client, compute_snapshot_diff
from server.systems.world_model.world_state import get_world_state
from server.systems.gev.geofencing import get_geofence_engine, GeofenceRule, TriggerType, CircleRegion, TriggerAction
from server.systems.gev.gev_intelligence import GPSSpoofDetector, OSINTEnricher, SocialSentiment, TrajectoryForecaster
from server.systems.gev.swarm_synergy import get_swarm_synergy_bridge
from server.systems.gev.satellite_vision import get_satellite_vision, ImageryRequest
from server.systems.gev.obsidian_integration import get_obsidian_integration
from server.systems.rag.obsidian_indexer import get_obsidian_indexer

logger = logging.getLogger("aariya.gev_agent")

# All layer keys the agent manages
ALL_LAYER_KEYS = [
    # Original
    "flights", "vessels", "fires", "earthquakes", "satellites",
    # Environmental
    "weather", "radar", "aqi", "volcanoes",
    # Human/Infrastructure
    "power_outages", "traffic", "transit",
    # Space
    "space_weather", "neos",
]

# Maximum number of historical snapshots to retain in memory (DVR mode)
MAX_TIMELINE_SNAPSHOTS = 360  # ~3 hours at 30s interval


class GEVAgent(Agent):
    """Geospatial Intelligence Agent — on-demand bridge between GEV and Aariya.

    ⚡ Power-saving: no background polling.  Data is only fetched when the
    brain, daemon, or a REST consumer explicitly requests it.

    🎬 DVR mode: retains a bounded ring buffer of historical snapshots
    so the brain can query past states ("Where were the vessels 2h ago?").
    """

    # ── Registry metadata ─────────────────────────────────────────────────────
    KIND = "geospatial"
    DETECTION = "static"
    CAPABILITIES = [
        "flights", "vessels", "fires", "earthquakes", "satellites",
        "weather", "radar", "aqi", "volcanoes",
        "power_outages", "traffic", "transit",
        "space_weather", "neos",
        "snapshot", "snapshot_diff", "status",
        # Intelligence sub-systems
        "geofence_register", "geofence_unregister", "geofence_list", "geofence_fired",
        "gps_spoofing",
        "osint_enrich",
        "social_events",
        "trajectory_forecast",
        "satellite_analyse",
        "obsidian_notes", "obsidian_write_report",
    ]
    DESCRIPTION = (
        "God's Eye View integration agent. On-demand geospatial intelligence: "
        "live aircraft, AIS vessels, fires, earthquakes, satellites, weather, "
        "radar, AQI, volcanic activity, power outages, traffic, transit, "
        "space weather, and near-Earth objects.  Only fetches data when the "
        "brain or daemon explicitly requests it (power-saving).  Supports "
        "snapshot diffing and historical DVR playback."
    )
    # Minimum seconds between two consecutive full fetches.
    MIN_REFRESH_INTERVAL = 30

    def __init__(self):
        super().__init__(name="GEVAgent")
        self._client = get_gev_client()
        self._world = get_world_state()
        self._last_snapshot: dict = {}
        self._last_fetch_at: float = 0.0
        self._refresh_lock = asyncio.Lock()

        # DVR timeline: bounded ring buffer of (timestamp, snapshot) tuples
        self._timeline: collections.deque[tuple[float, dict]] = collections.deque(
            maxlen=MAX_TIMELINE_SNAPSHOTS,
        )
        # Diff cache: previous snapshot for computing diffs
        self._previous_snapshot: dict | None = None

        # Intelligence sub-systems
        self._geofence = get_geofence_engine()
        self._synergy = get_swarm_synergy_bridge()
        self._gps_detector = GPSSpoofDetector()
        self._osint = OSINTEnricher()
        self._social = SocialSentiment()
        self._trajectory = TrajectoryForecaster()
        self._sat_vision = get_satellite_vision()
        self._obsidian = get_obsidian_integration()

        # Intelligence enrichment cache
        self._enrichment_cache: dict[str, dict] = {}

    # ── On-demand fetch (no background loop) ─────────────────────────────────

    async def refresh(self) -> dict:
        """Fetch a fresh GEV snapshot and write each layer to WorldState.

        Called on-demand by the brain, daemon, or REST router.
        Deduplicates concurrent requests and respects MIN_REFRESH_INTERVAL.
        """
        async with self._refresh_lock:
            now = time.time()
            if (now - self._last_fetch_at) < self.MIN_REFRESH_INTERVAL and self._last_snapshot:
                logger.debug("[GEVAgent] Using cached snapshot (%.1fs old)", now - self._last_fetch_at)
                return self._last_snapshot

            snap = await self._client.snapshot()

            # DVR: rotate previous → timeline, store new
            if self._last_snapshot:
                self._previous_snapshot = self._last_snapshot
                self._timeline.append((self._last_fetch_at, self._last_snapshot))

            self._last_snapshot = snap
            self._last_fetch_at = now

            for layer, data in snap.items():
                self._world.update("environment", f"gev_{layer}", data)
            self._world.update("environment", "gev_last_poll", self._last_fetch_at)

            # Anomaly detection for Obsidian
            self._check_for_anomalies(snap)

            # Run geofence evaluation (proactive triggers)
            try:
                fired_events = self._geofence.evaluate(snap)
                if fired_events:
                    self._world.update("environment", "gev_fired_events", fired_events)
                    logger.info("[GEVAgent] %d geofence rule(s) fired", len(fired_events))
            except Exception as e:
                logger.warning("[GEVAgent] Geofence evaluation error: %s", e)

            logger.debug("[GEVAgent] WorldState updated with GEV snapshot (%d layers)", len(snap))
            return snap

    def _check_for_anomalies(self, snap: dict):
        """Check GEV snapshot for massive events and journal them to Obsidian."""
        try:
            indexer = get_obsidian_indexer()
            
            # Check Earthquakes
            eq_data = snap.get("earthquakes", {})
            if isinstance(eq_data, dict) and eq_data.get("available") is not False:
                features = eq_data.get("features", [])
                for eq in features:
                    props = eq.get("properties", {})
                    mag = props.get("mag")
                    if mag and mag >= 6.5: # Major earthquake
                        title = f"Major Earthquake: M{mag} - {props.get('place')}"
                        report = f"God's Eye View detected a major seismic event.\n\nMagnitude: {mag}\nLocation: {props.get('place')}\nTime: {props.get('time')}\nStatus: {props.get('status')}\n\nThis event has been logged for situational awareness."
                        indexer.append_runtime_note(report, title)
                        
            # Check Fires
            fire_data = snap.get("fires", {})
            if isinstance(fire_data, list) and len(fire_data) > 500:
                title = "Massive Regional Fire Activity Detected"
                report = f"God's Eye View detected highly elevated thermal anomalies (fires). Over {len(fire_data)} individual fire points were detected by NASA FIRMS.\n\nThis level of activity indicates a major wildfire event."
                indexer.append_runtime_note(report, title)
                
        except Exception as e:
            logger.error(f"[GEVAgent] Failed to check for anomalies: {e}")

    async def refresh_diff(self) -> dict:
        """Fetch a fresh snapshot and write a diff-aware update to WorldState.

        Instead of overwriting the full snapshot, computes a diff that only
        records changes (added/removed/updated items per layer). The full
        snapshot is still available via the regular WorldState keys, but
        a "gev_diff" key records the delta.
        """
        async with self._refresh_lock:
            now = time.time()
            if (now - self._last_fetch_at) < self.MIN_REFRESH_INTERVAL and self._last_snapshot:
                logger.debug("[GEVAgent] Using cached snapshot for diff (%.1fs old)", now - self._last_fetch_at)
                # Return cached diff
                diff = compute_snapshot_diff(self._previous_snapshot, self._last_snapshot)
                return diff

            snap = await self._client.snapshot()
            diff = compute_snapshot_diff(self._previous_snapshot, snap)

            # DVR: rotate previous → timeline, store new
            if self._last_snapshot:
                self._previous_snapshot = self._last_snapshot
                self._timeline.append((self._last_fetch_at, self._last_snapshot))

            self._last_snapshot = snap
            self._last_fetch_at = now

            # Write full snapshot to WorldState (so other consumers still work)
            for layer, data in snap.items():
                self._world.update("environment", f"gev_{layer}", data)
            self._world.update("environment", "gev_last_poll", self._last_fetch_at)

            # Also write the diff
            self._world.update("environment", "gev_diff", diff)
            logger.debug(
                "[GEVAgent] WorldState updated with GEV snapshot + diff (%d layers, diff_summary=%s)",
                len(snap),
                diff.get("diff_summary"),
            )
            return diff

    # ── DVR / Timeline ────────────────────────────────────────────────────────

    def get_timeline(
        self,
        since_ts: float | None = None,
        limit: int = 60,
    ) -> list[dict]:
        """Retrieve historical snapshots for DVR playback.

        Args:
            since_ts: Only return snapshots after this timestamp. If None,
                      returns the most recent `limit` snapshots.
            limit: Maximum number of snapshots to return.

        Returns:
            List of {"timestamp": float, "snapshot": dict} objects,
            oldest first.
        """
        if not self._timeline:
            return []

        items = list(self._timeline)
        if since_ts is not None:
            items = [(ts, snap) for ts, snap in items if ts >= since_ts]

        # Return the most recent `limit` items
        items = items[-limit:]

        return [
            {"timestamp": ts, "snapshot": snap}
            for ts, snap in items
        ]

    def get_snapshot_at(self, target_ts: float) -> dict | None:
        """Find the snapshot closest to a target timestamp.

        Returns the snapshot dict, or None if the timeline is empty.
        """
        if not self._timeline:
            return None

        best_ts = None
        best_snap = None
        for ts, snap in self._timeline:
            if best_ts is None or abs(ts - target_ts) < abs(best_ts - target_ts):
                best_ts = ts
                best_snap = snap

        return best_snap

    @property
    def timeline_length(self) -> int:
        """Number of historical snapshots currently retained."""
        return len(self._timeline)

    @property
    def timeline_oldest(self) -> float | None:
        """Timestamp of the oldest retained snapshot, or None."""
        if not self._timeline:
            return None
        return self._timeline[0][0]

    @property
    def timeline_newest(self) -> float | None:
        """Timestamp of the newest retained snapshot, or None."""
        if not self._timeline:
            return None
        return self._timeline[-1][0]

    # ── Deprecated lifecycle stubs ────────────────────────────────────────────

    def start(self) -> None:
        logger.info("[GEVAgent] start() is a no-op — on-demand mode")

    def stop(self) -> None:
        logger.info("[GEVAgent] stop() — no background loop to cancel")

    # ── Agent API (called by brain / orchestrator) ────────────────────────────

    async def act(self, state: dict[str, Any]) -> Any:
        """
        Handle a GEV task from the swarm orchestrator or brain.

        Expected state keys:
          task (str): one of the CAPABILITIES
          lat, lon (float, optional): geographic anchor
          radius_km (float, optional): search radius
          bbox (dict, optional): {"min_lat", "max_lat", "min_lon", "max_lon"}
          since_ts (float, optional): for timeline queries
          target_ts (float, optional): for DVR playback
          limit (int, optional): max timeline entries
        """
        from server.systems.gev.gev_client import BoundingBox

        task = state.get("task", "snapshot")

        if task == "snapshot":
            return await self.refresh()

        if task == "snapshot_diff":
            return await self.refresh_diff()

        if task == "status":
            return await self._client.status()

        # Build bbox if provided
        bbox = None
        if "bbox" in state and state["bbox"]:
            b = state["bbox"]
            bbox = BoundingBox(
                min_lat=b["min_lat"],
                max_lat=b["max_lat"],
                min_lon=b["min_lon"],
                max_lon=b["max_lon"],
            )

        if task == "flights":
            return await self._client.flights(
                lat=state.get("lat"),
                lon=state.get("lon"),
                radius_km=state.get("radius_km", 250),
                bbox=bbox,
            )

        if task == "vessels":
            return await self._client.vessels(
                lat=state.get("lat"),
                lon=state.get("lon"),
                radius_km=state.get("radius_km", 200),
                bbox=bbox,
            )

        if task == "fires":
            return await self._client.fires(
                lat=state.get("lat"),
                lon=state.get("lon"),
            )

        if task == "earthquakes":
            return await self._client.earthquakes()

        if task == "satellites":
            return await self._client.satellites()

        if task == "iss_pass":
            lat = state.get("lat")
            lon = state.get("lon")
            if lat is None or lon is None:
                return {"error": "lat and lon are required for iss_pass"}
            return await self._client.iss_pass(lat, lon)

        # ── New environmental layers ──

        if task == "weather":
            return await self._client.weather(
                lat=state.get("lat"),
                lon=state.get("lon"),
            )

        if task == "radar":
            return await self._client.radar(
                lat=state.get("lat"),
                lon=state.get("lon"),
                radius_km=state.get("radius_km", 500),
            )

        if task == "aqi":
            return await self._client.aqi(
                lat=state.get("lat"),
                lon=state.get("lon"),
                radius_km=state.get("radius_km", 300),
            )

        if task == "volcanoes":
            return await self._client.volcanoes()

        # ── New human/infrastructure layers ──

        if task == "power_outages":
            return await self._client.power_outages(
                lat=state.get("lat"),
                lon=state.get("lon"),
                radius_km=state.get("radius_km", 500),
            )

        if task == "traffic":
            return await self._client.traffic(
                lat=state.get("lat"),
                lon=state.get("lon"),
                radius_km=state.get("radius_km", 200),
                bbox=bbox,
            )

        if task == "transit":
            return await self._client.transit(
                lat=state.get("lat"),
                lon=state.get("lon"),
                radius_km=state.get("radius_km", 100),
            )

        # ── Space & astronomy ──

        if task == "space_weather":
            return await self._client.space_weather()

        if task == "neos":
            return await self._client.neos()

        # ── Timeline / DVR ──

        if task == "timeline":
            return self.get_timeline(
                since_ts=state.get("since_ts"),
                limit=state.get("limit", 60),
            )

        if task == "playback":
            target_ts = state.get("target_ts")
            if target_ts is None:
                return {"error": "target_ts is required for playback"}
            snap = self.get_snapshot_at(target_ts)
            return snap or {"error": "No snapshot available for the requested timestamp"}

        # ── Intelligence sub-systems ──

        if task == "geofence_register":
            rule_data = state.get("rule", {})
            rule = GeofenceRule(
                id=rule_data.get("id", "auto"),
                name=rule_data.get("name", "Custom Rule"),
                layer=rule_data.get("layer", "flights"),
                trigger_type=TriggerType(rule_data.get("trigger_type", "presence")),
                region=CircleRegion(
                    lat=rule_data["region"]["lat"],
                    lon=rule_data["region"]["lon"],
                    radius_km=rule_data["region"]["radius_km"],
                ) if rule_data.get("region") else None,
                condition=rule_data.get("condition"),
                action=TriggerAction(**rule_data.get("action", {})),
            )
            rule_id = self._geofence.register(rule)
            return {"registered": rule_id}

        if task == "geofence_unregister":
            rule_id = state.get("rule_id", "")
            removed = self._geofence.unregister(rule_id)
            return {"removed": removed}

        if task == "geofence_list":
            return {"rules": self._geofence.list_rules(), "stats": self._geofence.get_stats()}

        if task == "geofence_fired":
            return {"events": self._geofence.get_fired_log(state.get("limit", 50))}

        if task == "gps_spoofing":
            zones = await self._gps_detector.fetch_interference_zones()
            # Also check current flights for anomalies
            flights_data = self._last_snapshot.get("flights", {})
            anomalies = self._gps_detector.detect_anomalies(flights_data)
            return {"zones": zones, "anomalies": anomalies}

        if task == "osint_enrich":
            entities = state.get("entities", [])
            entity_type = state.get("entity_type", "auto")
            if not entities:
                return {"error": "entities list is required"}
            return await self._osint.enrich_batch(entities, entity_type)

        if task == "social_events":
            return await self._social.fetch_live_events()

        if task == "trajectory_forecast":
            forecast_type = state.get("forecast_type", "flight")
            lat = state.get("lat")
            lon = state.get("lon")
            heading = state.get("heading", 0)
            speed = state.get("speed", 0)
            minutes = state.get("minutes", 30)

            if lat is None or lon is None:
                return {"error": "lat and lon are required"}

            if forecast_type == "flight":
                positions = self._trajectory.forecast_flight(
                    lat=lat, lon=lon, heading=heading, speed_kts=speed,
                    minutes=minutes,
                    wind_speed_kts=state.get("wind_speed", 0),
                    wind_heading=state.get("wind_heading", 0),
                )
            elif forecast_type == "vessel":
                positions = self._trajectory.forecast_vessel(
                    lat=lat, lon=lon, heading=heading, speed_kts=speed,
                    minutes=minutes,
                )
            elif forecast_type == "fire":
                positions = self._trajectory.forecast_fire_spread(
                    lat=lat, lon=lon,
                    wind_speed_kts=state.get("wind_speed", 0),
                    wind_heading=state.get("wind_heading", 0),
                    hours=state.get("hours", 6),
                )
            else:
                return {"error": f"Unknown forecast type: {forecast_type}"}
            return {"forecast_type": forecast_type, "positions": positions}

        if task == "satellite_analyse":
            lat = state.get("lat")
            lon = state.get("lon")
            question = state.get("question", "Describe what you see in this satellite image.")
            source = state.get("source", "sentinel2")
            model = state.get("model", "gemini")

            if lat is None or lon is None:
                return {"error": "lat and lon are required"}

            imagery = await self._sat_vision.fetch_imagery(ImageryRequest(
                lat=lat, lon=lon,
                radius_km=state.get("radius_km", 5),
                source=source,
            ))
            if not imagery.available:
                return {"error": imagery.error or "No imagery available"}

            analysis = await self._sat_vision.analyse(imagery, question, model=model)
            return {
                "imagery": {
                    "source": imagery.source,
                    "capture_date": imagery.capture_date,
                    "cloud_cover": imagery.cloud_cover_pct,
                    "resolution": imagery.resolution,
                    "thumbnail_url": imagery.thumbnail_url,
                },
                "analysis": {
                    "summary": analysis.summary,
                    "model_used": analysis.model_used,
                    "confidence": analysis.confidence,
                    "processing_time_ms": analysis.processing_time_ms,
                },
            }

        if task == "obsidian_notes":
            radius_km = state.get("radius_km", 50)
            lat = state.get("lat")
            lon = state.get("lon")
            if lat is not None and lon is not None:
                return {"notes": self._obsidian.find_notes_near(lat, lon, radius_km)}
            return {"notes": self._obsidian.get_notes()}

        if task == "obsidian_write_report":
            title = state.get("title", "GEV Intelligence Report")
            event_type = state.get("event_type", "general")
            summary = state.get("summary", "")
            details = state.get("details", {})
            sources = state.get("sources", [])
            file_path = self._obsidian.write_intel_report(
                title=title,
                event_type=event_type,
                summary=summary,
                details=details,
                sources=sources,
            )
            return {"file_path": file_path, "success": file_path is not None}

        return {"error": f"Unknown GEV task: {task!r}"}

    # ── Registry descriptor ───────────────────────────────────────────────────

    def registry_record(self) -> dict:
        """Return the metadata record the AgentRegistry expects."""
        import hashlib
        src = f"GEVAgent:{self.DESCRIPTION}"
        return {
            "id": "gev_agent",
            "name": "GEVAgent",
            "kind": self.KIND,
            "detection": self.DETECTION,
            "file": __file__,
            "file_hash": hashlib.md5(src.encode()).hexdigest(),
            "capabilities": self.CAPABILITIES,
            "description": self.DESCRIPTION,
            "status": "existing",
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_agent: GEVAgent | None = None


def get_gev_agent() -> GEVAgent:
    global _agent
    if _agent is None:
        _agent = GEVAgent()
    return _agent
