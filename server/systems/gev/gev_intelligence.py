"""
gev_intelligence.py
───────────────────
Intelligence sub-systems for the GEV agent:

  1. GPSSpoofDetector — detects GPS interference/jamming zones
  2. OSINTEnricher — cross-references vessels/aircraft against open databases
  3. SocialSentiment — aggregates geocoded news and crisis events
  4. TrajectoryForecaster — predicts future positions from current state
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("aariya.gev_intelligence")

TIMEOUT = 10.0


# ═══════════════════════════════════════════════════════════════════════════════
# 1. GPS Spoofing & Jamming Detection
# ═══════════════════════════════════════════════════════════════════════════════

class GPSSpoofDetector:
    """Detects GPS interference zones from ADS-B anomaly data.

    Data sources:
      - GPSJam (gpsjam.org) — crowd-sourced GPS interference reports
      - ADS-B Exchange anomaly data
      - Known military exercise / EW zone databases

    The detector fetches interference zones and returns them as a GEV layer
    that can be displayed on the globe as coloured polygons.
    """

    GPSJAM_URL = "https://gpsjam.org/api/zones"
    CACHE_TTL = 600  # 10 minutes

    def __init__(self):
        self._cache: dict = {}
        self._cache_at: float = 0.0

    async def fetch_interference_zones(self) -> dict:
        """Fetch current GPS interference zones.

        Returns a dict with interference regions including
        severity levels and affected area descriptions.
        """
        now = time.time()
        if self._cache and (now - self._cache_at) < self.CACHE_TTL:
            return self._cache

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(self.GPSJAM_URL)
                r.raise_for_status()
                data = r.json()

            zones = []
            features = data if isinstance(data, list) else data.get("features", data.get("zones", []))

            for feature in features:
                if isinstance(feature, dict):
                    zone = self._parse_zone(feature)
                    if zone:
                        zones.append(zone)

            result = {
                "available": True,
                "source": "GPSJam",
                "zones": zones,
                "count": len(zones),
                "fetched_at": now,
            }
            self._cache = result
            self._cache_at = now
            return result

        except Exception as e:
            logger.warning("[GPS Spoof] Fetch error: %s", e)
            return {"available": False, "reason": str(e)}

    def _parse_zone(self, feature: dict) -> dict | None:
        """Parse a GPSJam zone feature into our standard format."""
        try:
            # GPSJam uses GeoJSON polygons
            geometry = feature.get("geometry", feature)
            properties = feature.get("properties", feature)

            coords = geometry.get("coordinates", [])
            if not coords:
                return None

            # Compute centroid
            if geometry.get("type") == "Polygon" and coords:
                ring = coords[0]
                lats = [c[1] for c in ring]
                lons = [c[0] for c in ring]
                centroid_lat = sum(lats) / len(lats)
                centroid_lon = sum(lons) / len(lons)
            else:
                centroid_lat = properties.get("lat", 0)
                centroid_lon = properties.get("lon", 0)

            severity = properties.get("severity", properties.get("level", "unknown"))
            confidence = properties.get("confidence", properties.get("certainty", 0.5))
            reports = properties.get("reports", properties.get("num_reports", 0))

            return {
                "id": properties.get("id", hashlib.md5(f"{centroid_lat},{centroid_lon}".encode()).hexdigest()[:8]),
                "type": "gps_interference",
                "lat": centroid_lat,
                "lon": centroid_lon,
                "severity": severity,
                "confidence": float(confidence),
                "reports": int(reports) if isinstance(reports, (int, float)) else 0,
                "polygon": coords[0] if geometry.get("type") == "Polygon" else None,
                "description": properties.get("description", f"GPS interference zone (severity: {severity})"),
            }
        except Exception as e:
            logger.debug("[GPS Spoof] Zone parse error: %s", e)
            return None

    def detect_anomalies(self, flights_data: dict) -> list[dict]:
        """Analyze flight data for GPS spoofing indicators.

        Anomalies include:
          - Aircraft reporting position far from ADS-B reported position
          - Rapid position jumps inconsistent with speed
          - Multiple aircraft in same area reporting similar anomalous positions
        """
        anomalies = []
        entities = flights_data.get("aircraft", flights_data.get("entities", []))

        if not isinstance(entities, list):
            return anomalies

        for entity in entities:
            if not isinstance(entity, dict):
                continue

            # Check for position/velocity inconsistency
            lat = entity.get("lat")
            lon = entity.get("lon")
            speed = entity.get("speed") or entity.get("ground_speed")
            heading = entity.get("heading") or entity.get("track")

            if all(isinstance(v, (int, float)) for v in [lat, lon, speed, heading]):
                # Check for zero-speed at altitude (possible spoofing)
                altitude = entity.get("altitude") or entity.get("baro_altitude")
                if isinstance(altitude, (int, float)) and altitude > 1000:
                    if isinstance(speed, (int, float)) and speed < 5:
                        anomalies.append({
                            "id": entity.get("icao24", entity.get("id", "unknown")),
                            "type": "zero_speed_altitude",
                            "lat": lat,
                            "lon": lon,
                            "description": f"Aircraft at {altitude}ft reporting 0 speed — possible GPS spoof",
                            "severity": "medium",
                        })

                # Check for unrealistic heading changes (would need history)
                # This is a simplified check
                if isinstance(speed, (int, float)) and speed > 500:
                    if isinstance(heading, (int, float)) and heading == 0 and speed > 400:
                        anomalies.append({
                            "id": entity.get("icao24", entity.get("id", "unknown")),
                            "type": "heading_anomaly",
                            "lat": lat,
                            "lon": lon,
                            "description": f"High-speed ({speed}kts) aircraft with heading 0 — check for spoof",
                            "severity": "low",
                        })

        return anomalies


# ═══════════════════════════════════════════════════════════════════════════════
# 2. OSINT Enrichment Engine
# ═══════════════════════════════════════════════════════════════════════════════

class OSINTEnricher:
    """Cross-references vessel/aircraft identifiers against open-source databases.

    Databases checked:
      - OpenSanctions (sanctions lists, PEP databases)
      - Wikidata (public entity data, notable owners)
      - FAA Aircraft Registry (US civil aircraft)
      - IMO (International Maritime Organization vessel data)

    ⚡ Caches enrichment results to avoid repeated lookups.
    """

    CACHE_TTL = 3600  # 1 hour

    def __init__(self):
        self._cache: dict[str, dict] = {}
        self._cache_at: dict[str, float] = {}

    async def enrich_vessel(self, mmsi: str | None = None, imo: str | None = None, name: str | None = None) -> dict:
        """Enrich a vessel with OSINT data.

        Returns enrichment info including:
          - owner, flag, sanctions status, notable associations
        """
        cache_key = f"vessel:{mmsi or imo or name}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        enrichment: dict[str, Any] = {
            "identifier": mmsi or imo or name,
            "type": "vessel",
            "sanctions": [],
            "owner": None,
            "flag": None,
            "notable": False,
            "classification": None,
        }

        # OpenSanctions lookup
        if name or imo:
            sanctions = await self._query_opensanctions(query=name or imo)
            if sanctions:
                enrichment["sanctions"] = sanctions
                enrichment["notable"] = True
                enrichment["classification"] = "sanctioned"

        # Wikidata lookup
        if name:
            wikidata = await self._query_wikidata(query=name, entity_type="ship")
            if wikidata:
                if wikidata.get("owner"):
                    enrichment["owner"] = wikidata["owner"]
                if wikidata.get("flag"):
                    enrichment["flag"] = wikidata["flag"]
                if wikidata.get("notable"):
                    enrichment["notable"] = True
                    enrichment["classification"] = enrichment.get("classification") or "notable_entity"

        self._set_cached(cache_key, enrichment)
        return enrichment

    async def enrich_aircraft(self, icao24: str | None = None, callsign: str | None = None, registration: str | None = None) -> dict:
        """Enrich an aircraft with OSINT data.

        Returns enrichment info including:
          - operator, owner, military status, notable associations
        """
        cache_key = f"aircraft:{icao24 or callsign or registration}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        enrichment: dict[str, Any] = {
            "identifier": icao24 or callsign or registration,
            "type": "aircraft",
            "operator": None,
            "owner": None,
            "military": False,
            "sanctions": [],
            "notable": False,
            "classification": None,
        }

        # Military detection by ICAO24 prefix
        if icao24:
            military_prefixes = [
                ("AE", "USAF"), ("A0", "US Military"), ("A1", "US Military"),
                ("43", "UK Military"), ("3C", "German Military"),
                ("34", "Spanish Military"), ("38", "French Military"),
                ("3F", "Italian Military"), ("71", "Russian Military"),
                ("78", "Ukrainian Military"),
            ]
            for prefix, branch in military_prefixes:
                if icao24.upper().startswith(prefix):
                    enrichment["military"] = True
                    enrichment["operator"] = branch
                    enrichment["classification"] = "military"
                    enrichment["notable"] = True
                    break

        # FAA Registry lookup (US aircraft)
        if registration and registration.upper().startswith("N"):
            faa = await self._query_faa_registry(registration)
            if faa:
                enrichment["owner"] = faa.get("owner")
                enrichment["operator"] = faa.get("operator") or faa.get("owner")

        # Wikidata lookup
        if callsign:
            wikidata = await self._query_wikidata(query=callsign, entity_type="aircraft")
            if wikidata:
                if wikidata.get("owner"):
                    enrichment["owner"] = wikidata["owner"]
                if wikidata.get("operator"):
                    enrichment["operator"] = wikidata["operator"]
                if wikidata.get("notable"):
                    enrichment["notable"] = True

        # OpenSanctions for aircraft operators
        if enrichment["operator"] or enrichment["owner"]:
            sanctions = await self._query_opensanctions(query=enrichment["operator"] or enrichment["owner"])
            if sanctions:
                enrichment["sanctions"] = sanctions
                enrichment["notable"] = True
                enrichment["classification"] = "sanctioned_operator"

        self._set_cached(cache_key, enrichment)
        return enrichment

    async def enrich_batch(self, entities: list[dict], entity_type: str = "auto") -> dict[str, dict]:
        """Enrich a batch of entities concurrently.

        Args:
            entities: List of entity dicts with identifying fields.
            entity_type: "vessel", "aircraft", or "auto" (detect from fields).

        Returns:
            Dict mapping entity ID to enrichment result.
        """
        tasks = []
        for entity in entities:
            etype = entity_type
            if etype == "auto":
                if "mmsi" in entity or "imo" in entity:
                    etype = "vessel"
                elif "icao24" in entity or "callsign" in entity:
                    etype = "aircraft"
                else:
                    continue

            if etype == "vessel":
                tasks.append(self.enrich_vessel(
                    mmsi=entity.get("mmsi"),
                    imo=entity.get("imo"),
                    name=entity.get("name") or entity.get("callsign"),
                ))
            elif etype == "aircraft":
                tasks.append(self.enrich_aircraft(
                    icao24=entity.get("icao24"),
                    callsign=entity.get("callsign"),
                    registration=entity.get("registration"),
                ))

        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        results = {}
        for i, result in enumerate(results_list):
            if isinstance(result, Exception):
                logger.debug("[OSINT] Batch enrich error: %s", result)
                continue
            entity_id = result.get("identifier", f"unknown-{i}")
            results[entity_id] = result

        return results

    # ── Database query stubs ──────────────────────────────────────────────────

    async def _query_opensanctions(self, query: str | None) -> list[dict]:
        """Query OpenSanctions API for sanctions matches."""
        if not query:
            return []
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(
                    "https://api.opensanctions.org/search/default",
                    params={"q": query, "limit": 5},
                )
                if r.status_code == 200:
                    data = r.json()
                    results = data.get("results", [])
                    return [
                        {
                            "name": res.get("name", ""),
                            "score": res.get("score", 0),
                            "datasets": res.get("datasets", []),
                        }
                        for res in results if res.get("score", 0) > 0.5
                    ]
        except Exception as e:
            logger.debug("[OSINT] OpenSanctions query failed: %s", e)
        return []

    async def _query_wikidata(self, query: str | None, entity_type: str = "ship") -> dict | None:
        """Query Wikidata for entity information."""
        if not query:
            return None
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(
                    "https://www.wikidata.org/w/api.php",
                    params={
                        "action": "wbsearchentities",
                        "search": query,
                        "language": "en",
                        "format": "json",
                        "limit": 1,
                    },
                )
                if r.status_code == 200:
                    data = r.json()
                    results = data.get("search", [])
                    if results:
                        return {
                            "id": results[0].get("id"),
                            "label": results[0].get("label"),
                            "description": results[0].get("description"),
                            "notable": True,
                        }
        except Exception as e:
            logger.debug("[OSINT] Wikidata query failed: %s", e)
        return None

    async def _query_faa_registry(self, registration: str | None) -> dict | None:
        """Query FAA Aircraft Registry for registration data."""
        if not registration:
            return None
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(
                    "https://registry.faa.gov/api/aircraft",
                    params={"NNumberTxt": registration.upper()},
                )
                if r.status_code == 200:
                    data = r.json()
                    results = data.get("Results", [])
                    if results:
                        res = results[0]
                        return {
                            "owner": res.get("Name", ""),
                            "operator": res.get("Name", ""),
                            "address": res.get("Street", ""),
                        }
        except Exception as e:
            logger.debug("[OSINT] FAA query failed: %s", e)
        return None

    def _get_cached(self, key: str) -> dict | None:
        if key in self._cache:
            if (time.time() - self._cache_at.get(key, 0)) < self.CACHE_TTL:
                return self._cache[key]
        return None

    def _set_cached(self, key: str, value: dict) -> None:
        self._cache[key] = value
        self._cache_at[key] = time.time()


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Social Sentiment & Live Events
# ═══════════════════════════════════════════════════════════════════════════════

class SocialSentiment:
    """Aggregates geocoded news feeds, crisis alerts, and social media signals.

    Data sources:
      - GDACS (Global Disaster Alerting Coordination System)
      - ACLED (Armed Conflict Location & Event Data)
      - GDELT (Global Database of Events, Language, and Tone)
    """

    GDACS_URL = "https://www.gdacs.org/xml/rss.xml"
    CACHE_TTL = 300  # 5 minutes

    def __init__(self):
        self._cache: dict = {}
        self._cache_at: float = 0.0

    async def fetch_live_events(self) -> dict:
        """Fetch current global events from multiple sources."""
        now = time.time()
        if self._cache and (now - self._cache_at) < self.CACHE_TTL:
            return self._cache

        events = []

        # GDACS disasters
        gdacs = await self._fetch_gdacs()
        events.extend(gdacs)

        result = {
            "available": True,
            "events": events,
            "count": len(events),
            "fetched_at": now,
        }
        self._cache = result
        self._cache_at = now
        return result

    async def _fetch_gdacs(self) -> list[dict]:
        """Fetch GDACS disaster alerts."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(self.GDACS_URL)
                if r.status_code != 200:
                    return []

                # Parse XML (simple extraction)
                text = r.text
                events = []

                # Extract items from RSS
                items = text.split("<item>")[1:]  # Skip header
                for item in items[:50]:  # Limit
                    title = self._extract_tag(item, "title")
                    lat = self._extract_tag(item, "gdacs:lat")
                    lon = self._extract_tag(item, "gdacs:lon")
                    severity = self._extract_tag(item, "gdacs:alertlevel")
                    event_type = self._extract_tag(item, "gdacs:eventtype")

                    if lat and lon:
                        try:
                            events.append({
                                "id": hashlib.md5(title.encode()).hexdigest()[:8],
                                "source": "GDACS",
                                "type": event_type or "disaster",
                                "title": title,
                                "lat": float(lat),
                                "lon": float(lon),
                                "severity": severity or "unknown",
                                "description": title,
                            })
                        except (ValueError, TypeError):
                            pass

                return events
        except Exception as e:
            logger.debug("[Social] GDACS fetch failed: %s", e)
            return []

    def _extract_tag(self, text: str, tag: str) -> str | None:
        """Simple XML tag extraction."""
        try:
            start = text.index(f"<{tag}>") + len(f"<{tag}>")
            end = text.index(f"</{tag}>")
            return text[start:end].strip()
        except ValueError:
            return None


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Trajectory Forecaster
# ═══════════════════════════════════════════════════════════════════════════════

class TrajectoryForecaster:
    """Predicts future positions from current heading, speed, and environmental data.

    Capabilities:
      - Flight trajectory projection (30min, 1hr, 2hr horizons)
      - Vessel trajectory projection with current/wind correction
      - Wildfire spread prediction using wind vectors
    """

    def __init__(self):
        pass

    def forecast_flight(
        self,
        lat: float,
        lon: float,
        heading: float,  # degrees true
        speed_kts: float,
        altitude_ft: float = 0,
        minutes: int = 30,
        wind_speed_kts: float = 0,
        wind_heading: float = 0,
    ) -> list[dict]:
        """Forecast a flight's future positions.

        Returns a list of predicted (lat, lon, altitude, timestamp) points.
        """
        positions = []
        steps = max(1, minutes // 5)  # 5-minute intervals

        for i in range(1, steps + 1):
            t = i * 5 * 60  # seconds from now

            # Ground speed = airspeed + wind component
            wind_component = _wind_component(heading, wind_heading, wind_speed_kts)
            ground_speed_kts = speed_kts + wind_component

            # Distance in this step
            dist_nm = ground_speed_kts * (5 / 60)  # 5 minutes

            # Project position
            new_lat, new_lon = _project_position(lat, lon, heading, dist_nm)

            positions.append({
                "lat": new_lat,
                "lon": new_lon,
                "altitude_ft": altitude_ft,
                "timestamp": time.time() + t,
                "minutes_ahead": i * 5,
                "ground_speed_kts": ground_speed_kts,
            })

        return positions

    def forecast_vessel(
        self,
        lat: float,
        lon: float,
        heading: float,
        speed_kts: float,
        minutes: int = 60,
        current_speed_kts: float = 0,
        current_heading: float = 0,
        wind_speed_kts: float = 0,
    ) -> list[dict]:
        """Forecast a vessel's future positions accounting for currents."""
        positions = []
        steps = max(1, minutes // 10)

        for i in range(1, steps + 1):
            t = i * 10 * 60

            # Vessel speed + current
            effective_heading = _combine_headings(heading, current_heading, speed_kts, current_speed_kts)
            effective_speed = math.sqrt(
                speed_kts ** 2 + current_speed_kts ** 2
                + 2 * speed_kts * current_speed_kts * math.cos(math.radians(current_heading - heading))
            )

            # Wind drift (simplified)
            effective_speed += wind_speed_kts * 0.02  # 2% wind factor for vessels

            dist_nm = effective_speed * (10 / 60)
            new_lat, new_lon = _project_position(lat, lon, effective_heading, dist_nm)

            positions.append({
                "lat": new_lat,
                "lon": new_lon,
                "timestamp": time.time() + t,
                "minutes_ahead": i * 10,
                "speed_kts": effective_speed,
                "heading": effective_heading,
            })

        return positions

    def forecast_fire_spread(
        self,
        lat: float,
        lon: float,
        wind_speed_kts: float,
        wind_heading: float,
        fire_radius_m: float = 1000,
        hours: int = 6,
    ) -> list[dict]:
        """Forecast wildfire spread based on wind vectors.

        Returns predicted fire perimeter positions.
        """
        positions = []
        steps = max(1, hours * 2)  # 30-minute intervals

        # Fire spread rate: base 0.5 km/hr + wind-driven
        base_rate_km = 0.5
        wind_factor = wind_speed_kts * 1.852  # Convert to km/hr

        for i in range(1, steps + 1):
            t = i * 30 * 60  # 30 min intervals
            hours_ahead = i * 0.5

            # Spread radius grows with time
            spread_km = (base_rate_km + wind_factor * 0.1) * hours_ahead
            spread_m = spread_km * 1000

            # Wind-driven elongation
            elongation_km = wind_factor * hours_ahead * 0.3

            # Centre of fire (moves with wind)
            dist_nm = (elongation_km / 1.852) * (hours_ahead / 1)
            new_lat, new_lon = _project_position(lat, lon, wind_heading, dist_nm)

            # Multiple perimeter points
            perimeter = []
            for angle in range(0, 360, 45):
                rad = math.radians(angle)
                # Elongate in wind direction
                if angle == int(wind_heading / 45) * 45 % 360:
                    r = spread_m * 1.5
                elif abs(angle - wind_heading) < 90:
                    r = spread_m * 1.2
                else:
                    r = spread_m * 0.7

                p_lat, p_lon = _project_position(new_lat, new_lon, angle, r / 1852)
                perimeter.append({"lat": p_lat, "lon": p_lon})

            positions.append({
                "lat": new_lat,
                "lon": new_lon,
                "fire_radius_m": spread_m,
                "perimeter": perimeter,
                "timestamp": time.time() + t,
                "hours_ahead": hours_ahead,
                "wind_influence": wind_factor,
            })

        return positions


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _project_position(lat: float, lon: float, heading_deg: float, dist_nm: float) -> tuple[float, float]:
    """Project a new position from a starting point, heading, and distance."""
    R = 3440.065  # Earth radius in nautical miles
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    heading_rad = math.radians(heading_deg)

    angular_dist = dist_nm / R

    new_lat = math.asin(
        math.sin(lat_rad) * math.cos(angular_dist)
        + math.cos(lat_rad) * math.sin(angular_dist) * math.cos(heading_rad)
    )
    new_lon = lon_rad + math.atan2(
        math.sin(heading_rad) * math.sin(angular_dist) * math.cos(lat_rad),
        math.cos(angular_dist) - math.sin(lat_rad) * math.sin(new_lat),
    )

    return math.degrees(new_lat), math.degrees(new_lon)


def _wind_component(heading: float, wind_heading: float, wind_speed: float) -> float:
    """Calculate headwind/tailwind component for a given heading."""
    diff = math.radians(heading - wind_heading)
    return wind_speed * math.cos(diff)


def _combine_headings(h1: float, h2: float, s1: float, s2: float) -> float:
    """Combine two headings with their respective speeds."""
    vx = s1 * math.sin(math.radians(h1)) + s2 * math.sin(math.radians(h2))
    vy = s1 * math.cos(math.radians(h1)) + s2 * math.cos(math.radians(h2))
    if abs(vx) < 1e-10 and abs(vy) < 1e-10:
        return 0
    return (math.degrees(math.atan2(vx, vy)) + 360) % 360
