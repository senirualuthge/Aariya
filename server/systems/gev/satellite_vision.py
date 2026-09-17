"""
satellite_vision.py
───────────────────
Satellite Vision AI — gives Aariya the ability to see the ground.

Integrates satellite imagery sources (Sentinel-2, Landsat, Planet Labs)
with vision models (Gemini Pro Vision) to answer questions about
geographic locations.

Capabilities:
  - Fetch most recent optical or SAR imagery for a coordinate
  - Analyse imagery for: vehicle counts, damage assessment, activity detection
  - Answer questions like "Is there anomalous activity at this port?"
  - Count aircraft on tarmacs, assess fire damage, monitor construction

Data sources:
  - Sentinel-2 (Copernicus Open Access Hub) — 10m resolution, free
  - Landsat (USGS EarthExplorer) — 30m resolution, free
  - Planet Labs — 3-5m resolution, API key required

Vision models:
  - Gemini Pro Vision (Google) — multimodal analysis
  - GPT-4V (OpenAI) — fallback option
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger("aariya.satellite_vision")

TIMEOUT = 30.0  # Image fetches can be slow


@dataclass
class ImageryRequest:
    """Request for satellite imagery at a specific location."""
    lat: float
    lon: float
    radius_km: float = 5.0              # Area of interest radius
    max_cloud_pct: float = 20.0         # Maximum cloud cover percentage
    source: str = "sentinel2"           # sentinel2 | landsat | planet
    date_from: str | None = None        # ISO date string
    date_to: str | None = None          # ISO date string
    resolution: str = "10m"             # Desired resolution


@dataclass
class ImageryResult:
    """Result from fetching satellite imagery."""
    available: bool = False
    source: str = ""
    image_url: str = ""
    thumbnail_url: str = ""
    capture_date: str = ""
    cloud_cover_pct: float = 0.0
    resolution: str = ""
    bbox: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class AnalysisResult:
    """Result from AI vision analysis of satellite imagery."""
    available: bool = False
    summary: str = ""
    objects_detected: list[dict] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    confidence: float = 0.0
    raw_response: str = ""
    model_used: str = ""
    processing_time_ms: float = 0.0
    error: str | None = None


class SatelliteVision:
    """Satellite imagery fetcher and AI analysis engine."""

    # Sentinel-2 Copernicus API (free tier)
    SENTINEL_SEARCH_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
    # USGS Landsat
    LANDSAT_SEARCH_URL = "https://landsatlook.usgs.gov/stable-server/scene/find"

    def __init__(self):
        self._cache: dict[str, ImageryResult] = {}
        self._cache_at: dict[str, float] = {}
        self._cache_ttl = 1800  # 30 minutes

        # API keys from environment
        self._gemini_key = os.getenv("GEMINI_API_KEY", "")
        self._openai_key = os.getenv("OPENAI_API_KEY", "")
        self._planet_key = os.getenv("PLANET_API_KEY", "")

    # ── Imagery fetching ──────────────────────────────────────────────────────

    async def fetch_imagery(self, request: ImageryRequest) -> ImageryResult:
        """Fetch the most recent satellite imagery for a location.

        Returns an ImageryResult with image URL and metadata.
        """
        cache_key = f"{request.lat:.4f},{request.lon:.4f},{request.source}"
        if cache_key in self._cache:
            cached_at = self._cache_at.get(cache_key, 0)
            if (time.time() - cached_at) < self._cache_ttl:
                return self._cache[cache_key]

        if request.source == "sentinel2":
            result = await self._fetch_sentinel2(request)
        elif request.source == "landsat":
            result = await self._fetch_landsat(request)
        elif request.source == "planet":
            result = await self._fetch_planet(request)
        else:
            result = ImageryResult(available=False, error=f"Unknown source: {request.source}")

        if result.available:
            self._cache[cache_key] = result
            self._cache_at[cache_key] = time.time()

        return result

    async def _fetch_sentinel2(self, request: ImageryRequest) -> ImageryResult:
        """Fetch from Copernicus Sentinel-2 (free)."""
        try:
            # Compute bounding box
            bbox = self._compute_bbox(request.lat, request.lon, request.radius_km)

            # Search for products
            params = {
                "$filter": (
                    f"Collection/Name eq 'SENTINEL-2' "
                    f"and OData.CSC.Intersects(area=geography'SRID=4326;POINT({request.lon} {request.lat})') "
                    f"and ContentDate/Start gt {request.date_from or '2024-01-01T00:00:00.000Z'} "
                    f"and Attributes/OData.CSC.DoubleAttribute/any(att:att/Name eq 'cloudCover' and att/OData.CSC.DoubleAttribute/Value le {request.max_cloud_pct})"
                ),
                "$orderby": "ContentDate/Start desc",
                "$top": 1,
                "$expand": "Attributes",
            }

            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(self.SENTINEL_SEARCH_URL, params=params)
                if r.status_code != 200:
                    return ImageryResult(available=False, error=f"Sentinel search HTTP {r.status_code}")

                data = r.json()
                products = data.get("value", [])
                if not products:
                    return ImageryResult(available=False, error="No Sentinel-2 imagery found for this location/date range")

                product = products[0]
                product_id = product.get("Id", "")
                name = product.get("Name", "")
                date = product.get("ContentDate", {}).get("Start", "")
                cloud = self._extract_cloud_cover(product)

                # Build download URL (requires authentication for full resolution)
                # Use the preview/thumbnail for immediate display
                preview_url = f"https://sh.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"

                return ImageryResult(
                    available=True,
                    source="sentinel2",
                    image_url=preview_url,
                    thumbnail_url=f"https://catalogue.dataspace.copernicus.eu/odata/v1/Products({product_id})/Nodes('preview')/Nodes('$value')",
                    capture_date=date,
                    cloud_cover_pct=cloud,
                    resolution="10m",
                    bbox=bbox,
                    metadata={"product_name": name, "product_id": product_id},
                )
        except Exception as e:
            logger.warning("[SatVision] Sentinel-2 fetch error: %s", e)
            return ImageryResult(available=False, error=str(e))

    async def _fetch_landsat(self, request: ImageryRequest) -> ImageryResult:
        """Fetch from USGS Landsat (free)."""
        try:
            bbox = self._compute_bbox(request.lat, request.lon, request.radius_km)

            params = {
                "contains": f"{request.lon},{request.lat}",
                "maxCloudCover": request.max_cloud_pct,
                "limit": 1,
            }

            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(self.LANDSAT_SEARCH_URL, params=params)
                if r.status_code != 200:
                    return ImageryResult(available=False, error=f"Landsat search HTTP {r.status_code}")

                data = r.json()
                scenes = data.get("features", data.get("results", []))
                if not scenes:
                    return ImageryResult(available=False, error="No Landsat imagery found")

                scene = scenes[0]
                scene_id = scene.get("id", "")
                date = scene.get("properties", {}).get("date", scene.get("properties", {}).get("acquired", ""))
                cloud = scene.get("properties", {}).get("cloud_cover", 0)

                thumbnail_url = f"https://landsatlook.usgs.gov/gen/img? CollectionIdentifier=8& LandsatSceneIdentifier={scene_id}& size=thumb"

                return ImageryResult(
                    available=True,
                    source="landsat",
                    image_url=thumbnail_url,
                    thumbnail_url=thumbnail_url,
                    capture_date=date,
                    cloud_cover_pct=float(cloud) if cloud else 0,
                    resolution="30m",
                    bbox=bbox,
                    metadata={"scene_id": scene_id},
                )
        except Exception as e:
            logger.warning("[SatVision] Landsat fetch error: %s", e)
            return ImageryResult(available=False, error=str(e))

    async def _fetch_planet(self, request: ImageryRequest) -> ImageryResult:
        """Fetch from Planet Labs (requires API key)."""
        if not self._planet_key:
            return ImageryResult(available=False, error="Planet API key not configured")

        try:
            bbox = self._compute_bbox(request.lat, request.lon, request.radius_km)

            body = {
                "item_types": ["PSScene"],
                "filter": {
                    "type": "AndFilter",
                    "config": [
                        {"type": "GeometryFilter", "field_name": "geometry", "config": bbox},
                        {"type": "RangeFilter", "field_name": "cloud_cover", "config": {"lte": request.max_cloud_pct / 100}},
                    ],
                },
                "sort": [{"field_name": "acquired", "order": "desc"}],
                "page_size": 1,
            }

            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(
                    "https://api.planet.com/data/v1/quick-search",
                    json=body,
                    auth=(self._planet_key, ""),
                )
                if r.status_code != 200:
                    return ImageryResult(available=False, error=f"Planet search HTTP {r.status_code}")

                data = r.json()
                features = data.get("features", [])
                if not features:
                    return ImageryResult(available=False, error="No Planet imagery found")

                feature = features[0]
                props = feature.get("properties", {})
                assets_url = feature.get("_links", {}).get("assets", "")
                thumb_url = props.get("thumbnail", "")

                return ImageryResult(
                    available=True,
                    source="planet",
                    image_url=assets_url,
                    thumbnail_url=thumb_url,
                    capture_date=props.get("acquired", ""),
                    cloud_cover_pct=props.get("cloud_cover", 0) * 100,
                    resolution="3m",
                    bbox=bbox,
                    metadata={"item_id": feature.get("id", "")},
                )
        except Exception as e:
            logger.warning("[SatVision] Planet fetch error: %s", e)
            return ImageryResult(available=False, error=str(e))

    # ── AI Vision Analysis ────────────────────────────────────────────────────

    async def analyse(
        self,
        imagery: ImageryResult,
        question: str,
        model: str = "gemini",
    ) -> AnalysisResult:
        """Analyse satellite imagery with a vision model to answer a question.

        Args:
            imagery: The ImageryResult from fetch_imagery().
            question: Natural language question about the imagery.
            model: Vision model to use ("gemini" or "gpt4v").

        Returns:
            AnalysisResult with the model's analysis.
        """
        if not imagery.available:
            return AnalysisResult(available=False, error="No imagery available")

        start = time.time()

        # Download the image and encode as base64
        image_data = await self._download_image(imagery.thumbnail_url or imagery.image_url)
        if not image_data:
            return AnalysisResult(available=False, error="Failed to download imagery")

        image_b64 = base64.b64encode(image_data).decode("utf-8")

        # Choose model
        if model == "gemini" and self._gemini_key:
            result = await self._analyse_gemini(image_b64, question, imagery)
        elif model == "gpt4v" and self._openai_key:
            result = await self._analyse_gpt4v(image_b64, question, imagery)
        elif self._gemini_key:
            result = await self._analyse_gemini(image_b64, question, imagery)
        elif self._openai_key:
            result = await self._analyse_gpt4v(image_b64, question, imagery)
        else:
            return AnalysisResult(
                available=False,
                error="No vision model API keys configured (set GEMINI_API_KEY or OPENAI_API_KEY)",
            )

        result.processing_time_ms = (time.time() - start) * 1000
        return result

    async def _analyse_gemini(
        self,
        image_b64: str,
        question: str,
        imagery: ImageryResult,
    ) -> AnalysisResult:
        """Analyse imagery using Gemini Pro Vision."""
        try:
            prompt = (
                f"You are an expert geospatial intelligence analyst analysing satellite imagery.\n\n"
                f"Image metadata:\n"
                f"- Source: {imagery.source}\n"
                f"- Capture date: {imagery.capture_date}\n"
                f"- Resolution: {imagery.resolution}\n"
                f"- Cloud cover: {imagery.cloud_cover_pct:.1f}%\n"
                f"- Location: {imagery.bbox}\n\n"
                f"Question: {question}\n\n"
                f"Provide a detailed analysis. If you detect objects, list them with approximate counts. "
                f"If you see anomalies or noteworthy activity, describe them specifically. "
                f"Be precise and factual — this is for intelligence purposes."
            )

            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self._gemini_key}",
                    json={
                        "contents": [{"parts": [
                            {"text": prompt},
                            {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                        ]}],
                    },
                )
                if r.status_code != 200:
                    return AnalysisResult(available=False, error=f"Gemini API error {r.status_code}")

                data = r.json()
                text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")

                return AnalysisResult(
                    available=True,
                    summary=text,
                    model_used="gemini-pro-vision",
                    raw_response=text,
                    confidence=0.85,
                )
        except Exception as e:
            logger.warning("[SatVision] Gemini analysis error: %s", e)
            return AnalysisResult(available=False, error=str(e))

    async def _analyse_gpt4v(
        self,
        image_b64: str,
        question: str,
        imagery: ImageryResult,
    ) -> AnalysisResult:
        """Analyse imagery using GPT-4V."""
        try:
            prompt = (
                f"Expert geospatial intelligence analyst. Analyse this satellite image.\n"
                f"Source: {imagery.source}, Date: {imagery.capture_date}, Resolution: {imagery.resolution}\n"
                f"Question: {question}\n"
                f"Be precise, list object counts, describe anomalies."
            )

            async with httpx.AsyncClient(timeout=60.0) as client:
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    json={
                        "model": "gpt-4o",
                        "messages": [{"role": "user", "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                        ]}],
                        "max_tokens": 2000,
                    },
                    headers={"Authorization": f"Bearer {self._openai_key}"},
                )
                if r.status_code != 200:
                    return AnalysisResult(available=False, error=f"OpenAI API error {r.status_code}")

                data = r.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                return AnalysisResult(
                    available=True,
                    summary=text,
                    model_used="gpt-4o",
                    raw_response=text,
                    confidence=0.85,
                )
        except Exception as e:
            logger.warning("[SatVision] GPT-4V analysis error: %s", e)
            return AnalysisResult(available=False, error=str(e))

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _download_image(self, url: str) -> bytes | None:
        """Download an image from a URL."""
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.get(url)
                if r.status_code == 200:
                    return r.content
        except Exception as e:
            logger.debug("[SatVision] Image download failed: %s", e)
        return None

    def _compute_bbox(self, lat: float, lon: float, radius_km: float) -> dict:
        """Compute a bounding box GeoJSON from a centre and radius."""
        import math
        dlat = radius_km / 111.0
        dlon = radius_km / (111.0 * max(0.01, math.cos(math.radians(lat))))
        return {
            "type": "Polygon",
            "coordinates": [[
                [lon - dlon, lat - dlat],
                [lon + dlon, lat - dlat],
                [lon + dlon, lat + dlat],
                [lon - dlon, lat + dlat],
                [lon - dlon, lat - dlat],
            ]],
        }

    def _extract_cloud_cover(self, product: dict) -> float:
        """Extract cloud cover from Sentinel product attributes."""
        for attr in product.get("Attributes", []):
            if attr.get("Name") == "cloudCover":
                return float(attr.get("Value", 0))
        return 0.0


# ── Singleton ─────────────────────────────────────────────────────────────────

_vision: SatelliteVision | None = None


def get_satellite_vision() -> SatelliteVision:
    global _vision
    if _vision is None:
        _vision = SatelliteVision()
    return _vision
