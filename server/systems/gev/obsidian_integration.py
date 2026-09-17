"""
obsidian_integration.py
───────────────────────
Obsidian Integration — the "Mind Map" for GEV.

Features:
  1. Geotagged Obsidian Notes
     Scans an Obsidian vault for notes with location tags and renders
     them as glowing nodes on the GEV map. Clicking a location pulls
     up personal notes about that place.

  2. Automated Intelligence Journaling
     When GEV detects a major global anomaly, Aariya autonomously
     generates an intelligence report and saves it to the Obsidian vault
     as a permanent memory.

Location tag formats supported:
  - #location/tokyo
  - #location/51.5074,-0.1278  (lat,lon)
  - YAML frontmatter: location: {lat: 51.5074, lon: -0.1278}
  - YAML frontmatter: geolocation: "51.5074, -0.1278"
  - Body text: @geolocation(51.5074, -0.1278)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("aariya.obsidian_integration")


@dataclass
class GeotaggedNote:
    """An Obsidian note with geographic coordinates."""
    id: str
    title: str
    path: str               # Relative path in vault
    lat: float
    lon: float
    tags: list[str] = field(default_factory=list)
    snippet: str = ""       # First ~200 chars of content
    created: float = 0.0
    modified: float = 0.0


@dataclass
class IntelReport:
    """An auto-generated intelligence report."""
    id: str
    title: str
    timestamp: float
    event_type: str
    summary: str
    details: dict = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    file_path: str = ""


class ObsidianIntegration:
    """Scans and manages geotagged Obsidian notes for the GEV map.

    Vault path is configured via the OBSIDIAN_VAULT_PATH environment variable.
    """

    # Regex patterns for location extraction
    LOCATION_TAG = re.compile(r"#location/([-\d.]+),([-\d.]+)")
    LOCATION_TAG_NAME = re.compile(r"#location/([a-zA-Z]+)")
    GEOLOCATION_BODY = re.compile(r"@geolocation\(([-\d.]+),\s*([-\d.]+)\)")
    YAML_LOCATION = re.compile(
        r"^location:\s*\{?\s*lat:\s*([-\d.]+)\s*,\s*lon:\s*([-\d.]+)\s*\}?",
        re.MULTILINE,
    )
    YAML_GEOLOCATION = re.compile(
        r"^geolocation:\s*\"?([-\d.]+),\s*([-\d.]+)\"?",
        re.MULTILINE,
    )

    # Well-known city coordinates for #location/name tags
    CITY_COORDS = {
        "tokyo": (35.6762, 139.6503),
        "london": (51.5074, -0.1278),
        "newyork": (40.7128, -74.0060),
        "new_york": (40.7128, -74.0060),
        "paris": (48.8566, 2.3522),
        "berlin": (52.5200, 13.4050),
        "moscow": (55.7558, 37.6173),
        "beijing": (39.9042, 116.4074),
        "sydney": (-33.8688, 151.2093),
        "dubai": (25.2048, 55.2708),
        "singapore": (1.3521, 103.8198),
        "hongkong": (22.3193, 114.1694),
        "mumbai": (19.0760, 72.8777),
        "losangeles": (34.0522, -118.2437),
        "chicago": (41.8781, -87.6298),
        "sanfrancisco": (37.7749, -122.4194),
        "washington": (38.9072, -77.0369),
        "rome": (41.9028, 12.4964),
        "madrid": (40.4168, -3.7038),
        "amsterdam": (52.3676, 4.9041),
        "brussels": (50.8503, 4.3517),
        "zurich": (47.3769, 8.5417),
        "taipei": (25.0330, 121.5654),
        "seoul": (37.5665, 126.9780),
        "bangkok": (13.7563, 100.5018),
        "cairo": (30.0444, 31.2357),
        "lagos": (6.5244, 3.3792),
        "nairobi": (-1.2921, 36.8219),
        "capetown": (-33.9249, 18.4241),
        "buenosaires": (-34.6037, -58.3816),
        "mexicocity": (19.4326, -99.1332),
        "texas": (31.9686, -99.9018),
        "california": (36.7783, -119.4179),
        "florida": (27.6648, -81.5158),
        "alaska": (64.2008, -149.4937),
        "hawaii": (19.8968, -155.5828),
        "ukraine": (48.3794, 31.1656),
        "iran": (32.4279, 53.6880),
        "taiwan": (23.6978, 120.9605),
        "israel": (31.0461, 34.8516),
        "palestine": (31.9522, 35.2332),
    }

    def __init__(self, vault_path: str | None = None):
        self._vault_path = vault_path or os.getenv("OBSIDIAN_VAULT_PATH", "")
        self._notes: dict[str, GeotaggedNote] = {}
        self._last_scan_at: float = 0.0
        self._scan_interval = 300  # 5 minutes

    # ── Vault scanning ────────────────────────────────────────────────────────

    def scan_vault(self, force: bool = False) -> dict[str, GeotaggedNote]:
        """Scan the Obsidian vault for geotagged notes.

        Returns a dict of note_id → GeotaggedNote.
        """
        now = time.time()
        if not force and (now - self._last_scan_at) < self._scan_interval:
            return self._notes

        if not self._vault_path or not os.path.isdir(self._vault_path):
            logger.warning("[Obsidian] Vault path not configured or not found: %s", self._vault_path)
            return self._notes

        self._notes.clear()
        vault = Path(self._vault_path)

        for md_file in vault.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
                note = self._parse_note(md_file, content, vault)
                if note:
                    self._notes[note.id] = note
            except Exception as e:
                logger.debug("[Obsidian] Error reading %s: %s", md_file, e)

        self._last_scan_at = now
        logger.info("[Obsidian] Scanned vault: %d geotagged notes found", len(self._notes))
        return self._notes

    def _parse_note(self, path: Path, content: str, vault_root: Path) -> GeotaggedNote | None:
        """Parse an Obsidian note for geolocation data."""
        title = path.stem
        relative_path = str(path.relative_to(vault_root))

        # Try #location/name tags
        match = self.LOCATION_TAG_NAME.search(content)
        if match:
            name = match.group(1).lower().replace("-", "").replace("_", "")
            coords = self.CITY_COORDS.get(name)
            if coords:
                return self._create_note(title, relative_path, coords[0], coords[1], content)

        # Try #location/lat,lon tags
        match = self.LOCATION_TAG.search(content)
        if match:
            lat, lon = float(match.group(1)), float(match.group(2))
            return self._create_note(title, relative_path, lat, lon, content)

        # Try @geolocation(lat, lon) in body
        match = self.GEOLOCATION_BODY.search(content)
        if match:
            lat, lon = float(match.group(1)), float(match.group(2))
            return self._create_note(title, relative_path, lat, lon, content)

        # Try YAML frontmatter
        yaml_match = self.YAML_LOCATION.search(content)
        if yaml_match:
            lat, lon = float(yaml_match.group(1)), float(yaml_match.group(2))
            return self._create_note(title, relative_path, lat, lon, content)

        yaml_geo = self.YAML_GEOLOCATION.search(content)
        if yaml_geo:
            lat, lon = float(yaml_geo.group(1)), float(yaml_geo.group(2))
            return self._create_note(title, relative_path, lat, lon, content)

        return None

    def _create_note(
        self,
        title: str,
        path: str,
        lat: float,
        lon: float,
        content: str,
    ) -> GeotaggedNote:
        """Create a GeotaggedNote from parsed data."""
        # Extract first ~200 chars as snippet (skip YAML frontmatter)
        lines = content.split("\n")
        body_lines = []
        in_frontmatter = False
        for line in lines:
            if line.strip() == "---":
                in_frontmatter = not in_frontmatter
                continue
            if not in_frontmatter and line.strip():
                body_lines.append(line.strip())
            if len(body_lines) >= 3:
                break
        snippet = " ".join(body_lines)[:200]

        # Extract tags
        tags = re.findall(r"#([a-zA-Z_]+)", content)

        note_id = hashlib.md5(f"{title}:{path}".encode()).hexdigest()[:8]
        return GeotaggedNote(
            id=note_id,
            title=title,
            path=path,
            lat=lat,
            lon=lon,
            tags=tags,
            snippet=snippet,
            created=os.path.getmtime(path) if os.path.exists(path) else 0,
            modified=os.path.getmtime(path) if os.path.exists(path) else 0,
        )

    # ── Note access ───────────────────────────────────────────────────────────

    def get_notes(self) -> list[dict]:
        """Return all geotagged notes as serialisable dicts."""
        self.scan_vault()
        return [
            {
                "id": n.id,
                "title": n.title,
                "path": n.path,
                "lat": n.lat,
                "lon": n.lon,
                "tags": n.tags,
                "snippet": n.snippet,
            }
            for n in self._notes.values()
        ]

    def get_note_content(self, note_id: str) -> str | None:
        """Read the full content of a geotagged note."""
        note = self._notes.get(note_id)
        if not note:
            return None

        full_path = os.path.join(self._vault_path, note.path)
        try:
            return Path(full_path).read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("[Obsidian] Failed to read note %s: %s", note_id, e)
            return None

    def find_notes_near(self, lat: float, lon: float, radius_km: float = 50) -> list[dict]:
        """Find geotagged notes within a radius of a point."""
        import math
        results = []
        for note in self._notes.values():
            dlat = abs(note.lat - lat) * 111.0
            dlon = abs(note.lon - lon) * 111.0 * max(0.01, math.cos(math.radians(lat)))
            dist = math.sqrt(dlat ** 2 + dlon ** 2)
            if dist <= radius_km:
                results.append({
                    "id": note.id,
                    "title": note.title,
                    "path": note.path,
                    "lat": note.lat,
                    "lon": note.lon,
                    "distance_km": round(dist, 2),
                    "snippet": note.snippet,
                })
        results.sort(key=lambda x: x["distance_km"])
        return results

    # ── Automated intelligence journaling ─────────────────────────────────────

    def write_intel_report(
        self,
        title: str,
        event_type: str,
        summary: str,
        details: dict | None = None,
        sources: list[str] | None = None,
        folder: str = "Intelligence",
    ) -> str | None:
        """Write an automated intelligence report to the Obsidian vault.

        Returns the file path if successful, None otherwise.
        """
        if not self._vault_path:
            logger.warning("[Obsidian] Vault path not configured — cannot write report")
            return None

        now = time.time()
        timestamp_str = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(now))
        date_str = time.strftime("%Y-%m-%d", time.gmtime(now))
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:60]

        # Build YAML frontmatter
        frontmatter = {
            "title": title,
            "date": date_str,
            "type": "intelligence_report",
            "event_type": event_type,
            "generated_by": "Aariya GEV Intelligence",
            "timestamp": now,
        }
        if details and "lat" in details and "lon" in details:
            frontmatter["geolocation"] = f"{details['lat']}, {details['lon']}"
            frontmatter["location"] = {"lat": details["lat"], "lon": details["lon"]}

        # Build markdown content
        fm_yaml = "\n".join(f"{k}: {json.dumps(v) if isinstance(v, (dict, list)) else v}" for k, v in frontmatter.items())
        body = f"""---
{fm_yaml}
---

# {title}

**Generated:** {timestamp_str}
**Event Type:** {event_type}

## Summary

{summary}
"""
        if details:
            body += "\n## Details\n\n"
            for k, v in details.items():
                body += f"- **{k}:** {v}\n"

        if sources:
            body += "\n## Sources\n\n"
            for src in sources:
                body += f"- {src}\n"

        body += f"\n---\n*Auto-generated by Aariya GEV Intelligence on {timestamp_str}*\n"

        # Write to vault
        target_dir = os.path.join(self._vault_path, folder)
        os.makedirs(target_dir, exist_ok=True)
        file_path = os.path.join(target_dir, f"{date_str}-{slug}.md")

        try:
            Path(file_path).write_text(body, encoding="utf-8")
            logger.info("[Obsidian] Intel report written: %s", file_path)
            return file_path
        except Exception as e:
            logger.warning("[Obsidian] Failed to write report: %s", e)
            return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_integration: ObsidianIntegration | None = None


def get_obsidian_integration() -> ObsidianIntegration:
    global _integration
    if _integration is None:
        _integration = ObsidianIntegration()
    return _integration
