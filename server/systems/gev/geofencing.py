"""
geofencing.py
─────────────
Autonomous Geofencing & Spatial Trigger Engine for the GEV system.

Enables the brain to register spatial rules (geofences) that are evaluated
automatically whenever a new GEV snapshot arrives. When a trigger fires,
the agent interrupts the brain with a high-priority message.

Supported trigger types:
  - ENTER: Fires when an entity enters a defined region
  - EXIT:  Fires when an entity leaves a defined region
  - PRESENCE: Fires continuously while an entity is in a region
  - ATTRIBUTE: Fires when an entity attribute matches a condition
  - PROXIMITY: Fires when two entities come within a distance threshold
  - EMERGENCY: Fires on emergency squawk codes (7700, 7600, 7500)

Usage:
    engine = GeofenceEngine()
    engine.register(GeofenceRule(
        id="london-emergency-flights",
        name="Emergency flights near London",
        layer="flights",
        trigger_type=TriggerType.ATTRIBUTE,
        condition={"field": "squawk", "operator": "in", "value": ["7700", "7600", "7500"]},
        region=CircleRegion(lat=51.5, lon=-0.12, radius_km=500),
        action=TriggerAction(type="alert", priority="high", message="Emergency squawk near London"),
    ))
    fired = engine.evaluate(snapshot)
"""

from __future__ import annotations

import json
import logging
import math
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("aariya.geofence")


# ── Enums ─────────────────────────────────────────────────────────────────────

class TriggerType(str, Enum):
    ENTER = "enter"
    EXIT = "exit"
    PRESENCE = "presence"
    ATTRIBUTE = "attribute"
    PROXIMITY = "proximity"
    EMERGENCY = "emergency"


class TriggerPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── Geographic primitives ─────────────────────────────────────────────────────

@dataclass
class CircleRegion:
    """A circular geofence defined by centre and radius."""
    lat: float
    lon: float
    radius_km: float

    def contains(self, lat: float, lon: float) -> bool:
        """Haversine distance check."""
        return _haversine_km(self.lat, self.lon, lat, lon) <= self.radius_km


@dataclass
class PolygonRegion:
    """A polygonal geofence defined by a list of (lat, lon) vertices."""
    vertices: list[tuple[float, float]]

    def contains(self, lat: float, lon: float) -> bool:
        """Ray-casting point-in-polygon test."""
        return _point_in_polygon(lat, lon, self.vertices)


@dataclass
class BBoxRegion:
    """An axis-aligned bounding box geofence."""
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon


Region = CircleRegion | PolygonRegion | BBoxRegion


# ── Trigger action ────────────────────────────────────────────────────────────

@dataclass
class TriggerAction:
    """What happens when a geofence rule fires."""
    type: str = "alert"                  # alert | log | webhook | dispatch_agent
    priority: str = "medium"
    message: str = ""
    dispatch_agent: str | None = None    # agent to invoke (for swarm synergy)
    dispatch_task: dict | None = None    # task payload for the dispatched agent
    cooldown_seconds: float = 300.0      # minimum time between repeated firings


# ── Geofence rule ─────────────────────────────────────────────────────────────

@dataclass
class GeofenceRule:
    """A single spatial trigger rule."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    layer: str = "flights"               # which GEV layer this rule monitors
    trigger_type: TriggerType = TriggerType.PRESENCE
    region: Region | None = None
    condition: dict | None = None        # attribute-based conditions
    action: TriggerAction = field(default_factory=TriggerAction)
    enabled: bool = True
    created_at: float = field(default_factory=time.time)

    # Runtime state
    _last_fired_at: float = 0.0
    _previous_state: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.trigger_type, str):
            self.trigger_type = TriggerType(self.trigger_type)


# ── Geofence engine ───────────────────────────────────────────────────────────

class GeofenceEngine:
    """Evaluates geofence rules against GEV snapshots.

    ⚡ Power-saving: this engine only runs when evaluate() is called,
    which happens inside the GEV agent's refresh cycle.
    """

    def __init__(self):
        self._rules: dict[str, GeofenceRule] = {}
        self._fired_log: list[dict] = []
        self._max_log = 1000
        self._callbacks: list[Callable[[dict], None]] = []

    # ── Rule management ───────────────────────────────────────────────────────

    def register(self, rule: GeofenceRule) -> str:
        """Register a geofence rule. Returns the rule id."""
        self._rules[rule.id] = rule
        logger.info("[Geofence] Registered rule '%s' (%s) on layer '%s'",
                     rule.name, rule.id, rule.layer)
        return rule.id

    def unregister(self, rule_id: str) -> bool:
        """Remove a geofence rule. Returns True if found."""
        removed = self._rules.pop(rule_id, None)
        if removed:
            logger.info("[Geofence] Unregistered rule '%s'", rule_id)
        return removed is not None

    def enable(self, rule_id: str) -> bool:
        rule = self._rules.get(rule_id)
        if rule:
            rule.enabled = True
            return True
        return False

    def disable(self, rule_id: str) -> bool:
        rule = self._rules.get(rule_id)
        if rule:
            rule.enabled = False
            return True
        return False

    def get_rule(self, rule_id: str) -> GeofenceRule | None:
        return self._rules.get(rule_id)

    def list_rules(self) -> list[dict]:
        """Return all registered rules as serialisable dicts."""
        return [
            {
                "id": r.id,
                "name": r.name,
                "layer": r.layer,
                "trigger_type": r.trigger_type.value,
                "enabled": r.enabled,
                "region_type": type(r.region).__name__ if r.region else None,
                "action": asdict(r.action),
                "created_at": r.created_at,
                "_last_fired_at": r._last_fired_at,
            }
            for r in self._rules.values()
        ]

    # ── Callback system ───────────────────────────────────────────────────────

    def on_trigger(self, callback: Callable[[dict], None]) -> None:
        """Register a callback that fires when any rule triggers.

        The callback receives a dict with rule info and triggered entities.
        Used by the swarm synergy bridge to dispatch other agents.
        """
        self._callbacks.append(callback)

    # ── Evaluation ────────────────────────────────────────────────────────────

    def evaluate(self, snapshot: dict[str, Any]) -> list[dict]:
        """Evaluate all enabled rules against a GEV snapshot.

        Args:
            snapshot: The GEV snapshot dict keyed by layer name.

        Returns:
            List of fired trigger events.
        """
        now = time.time()
        fired_events: list[dict] = []

        for rule in self._rules.values():
            if not rule.enabled:
                continue

            # Cooldown check
            if (now - rule._last_fired_at) < rule.action.cooldown_seconds:
                continue

            layer_data = snapshot.get(rule.layer)
            if not layer_data or (isinstance(layer_data, dict) and layer_data.get("available") is False):
                continue

            entities = _extract_entities(layer_data)
            if not entities:
                continue

            event = self._evaluate_rule(rule, entities, now)
            if event:
                fired_events.append(event)
                rule._last_fired_at = now
                self._fired_log.append(event)
                if len(self._fired_log) > self._max_log:
                    self._fired_log = self._fired_log[-self._max_log:]

                # Notify callbacks
                for cb in self._callbacks:
                    try:
                        cb(event)
                    except Exception as e:
                        logger.warning("[Geofence] Callback error: %s", e)

        if fired_events:
            logger.info("[Geofence] %d rule(s) fired", len(fired_events))

        return fired_events

    def _evaluate_rule(
        self,
        rule: GeofenceRule,
        entities: list[dict],
        now: float,
    ) -> dict | None:
        """Evaluate a single rule against a list of entities."""
        triggered_entities: list[dict] = []

        for entity in entities:
            lat = _entity_lat(entity)
            lon = _entity_lon(entity)
            if lat is None or lon is None:
                continue

            fired = False

            if rule.trigger_type == TriggerType.ENTER:
                in_region = rule.region.contains(lat, lon) if rule.region else True
                was_in = rule._previous_state.get(_entity_id(entity), False)
                if in_region and not was_in:
                    fired = True
                rule._previous_state[_entity_id(entity)] = in_region

            elif rule.trigger_type == TriggerType.EXIT:
                in_region = rule.region.contains(lat, lon) if rule.region else True
                was_in = rule._previous_state.get(_entity_id(entity), False)
                if not in_region and was_in:
                    fired = True
                rule._previous_state[_entity_id(entity)] = in_region

            elif rule.trigger_type == TriggerType.PRESENCE:
                if rule.region and rule.region.contains(lat, lon):
                    fired = True

            elif rule.trigger_type == TriggerType.ATTRIBUTE:
                if _check_attribute_condition(entity, rule.condition):
                    # If there's also a region, both must match
                    if rule.region:
                        fired = rule.region.contains(lat, lon)
                    else:
                        fired = True

            elif rule.trigger_type == TriggerType.PROXIMITY:
                # Proximity is checked against the first entity's neighbours
                # (handled separately below)
                pass

            elif rule.trigger_type == TriggerType.EMERGENCY:
                if _is_emergency(entity):
                    fired = True

            if fired:
                triggered_entities.append({
                    "id": _entity_id(entity),
                    "lat": lat,
                    "lon": lon,
                    "data": {k: v for k, v in entity.items() if k in (
                        "callsign", "name", "squawk", "icao24", "mmsi",
                        "type", "status", "speed", "heading", "altitude",
                    )},
                })

        # Proximity triggers: check all entity pairs
        if rule.trigger_type == TriggerType.PROXIMITY and not triggered_entities:
            threshold_km = rule.condition.get("distance_km", 10) if rule.condition else 10
            for i, a in enumerate(entities):
                a_lat, a_lon = _entity_lat(a), _entity_lon(a)
                if a_lat is None:
                    continue
                for b in entities[i + 1:]:
                    b_lat, b_lon = _entity_lat(b), _entity_lon(b)
                    if b_lat is None:
                        continue
                    dist = _haversine_km(a_lat, a_lon, b_lat, b_lon)
                    if dist <= threshold_km:
                        triggered_entities.append({
                            "id": f"{_entity_id(a)}-near-{_entity_id(b)}",
                            "lat": a_lat,
                            "lon": a_lon,
                            "distance_km": dist,
                            "data": {
                                "entity_a": _entity_id(a),
                                "entity_b": _entity_id(b),
                            },
                        })
                        break  # One proximity event per entity pair

        if not triggered_entities:
            return None

        event = {
            "event_id": str(uuid.uuid4())[:8],
            "rule_id": rule.id,
            "rule_name": rule.name,
            "trigger_type": rule.trigger_type.value,
            "layer": rule.layer,
            "priority": rule.action.priority,
            "message": rule.action.message or f"{rule.name} triggered",
            "timestamp": now,
            "entities": triggered_entities,
            "entity_count": len(triggered_entities),
            "action": asdict(rule.action),
        }

        logger.info("[Geofence] Rule '%s' fired: %d entities",
                     rule.name, len(triggered_entities))

        return event

    # ── Log access ────────────────────────────────────────────────────────────

    def get_fired_log(self, limit: int = 100) -> list[dict]:
        """Return recent trigger events."""
        return self._fired_log[-limit:]

    def get_stats(self) -> dict:
        """Return engine statistics."""
        enabled = sum(1 for r in self._rules.values() if r.enabled)
        total_fired = sum(
            1 for r in self._rules.values() if r._last_fired_at > 0
        )
        return {
            "total_rules": len(self._rules),
            "enabled_rules": enabled,
            "total_fired": len(self._fired_log),
            "rules_with_fires": total_fired,
        }

    # ── Serialisation ─────────────────────────────────────────────────────────

    def export_rules(self) -> list[dict]:
        """Export all rules as JSON-safe dicts."""
        return [
            {
                "id": r.id,
                "name": r.name,
                "layer": r.layer,
                "trigger_type": r.trigger_type.value,
                "region": _serialize_region(r.region),
                "condition": r.condition,
                "action": asdict(r.action),
                "enabled": r.enabled,
            }
            for r in self._rules.values()
        ]

    def import_rules(self, rules: list[dict]) -> int:
        """Import rules from JSON-safe dicts. Returns count imported."""
        count = 0
        for r in rules:
            try:
                rule = GeofenceRule(
                    id=r.get("id", str(uuid.uuid4())[:8]),
                    name=r.get("name", ""),
                    layer=r.get("layer", "flights"),
                    trigger_type=TriggerType(r.get("trigger_type", "presence")),
                    region=_deserialize_region(r.get("region")),
                    condition=r.get("condition"),
                    action=TriggerAction(**r.get("action", {})),
                    enabled=r.get("enabled", True),
                )
                self._rules[rule.id] = rule
                count += 1
            except Exception as e:
                logger.warning("[Geofence] Failed to import rule: %s", e)
        return count


# ── Helpers ───────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_in_polygon(lat: float, lon: float, vertices: list[tuple[float, float]]) -> bool:
    """Ray-casting algorithm for point-in-polygon test."""
    n = len(vertices)
    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = vertices[i]
        yj, xj = vertices[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _entity_id(entity: dict) -> str:
    """Extract a stable identifier from an entity."""
    for key in ("id", "icao24", "mmsi", "callsign", "name", "number", "norad_id"):
        if key in entity and entity[key] is not None:
            return str(entity[key])
    return f"unknown-{id(entity)}"


def _entity_lat(entity: dict) -> float | None:
    for key in ("lat", "latitude"):
        if key in entity:
            v = entity[key]
            if isinstance(v, (int, float)) and math.isfinite(v):
                return v
    pos = entity.get("position") or entity.get("geometry")
    if isinstance(pos, dict):
        return pos.get("lat") or pos.get("latitude")
    if isinstance(pos, list) and len(pos) >= 2:
        return pos[1]  # GeoJSON [lon, lat] convention
    return None


def _entity_lon(entity: dict) -> float | None:
    for key in ("lon", "longitude"):
        if key in entity:
            v = entity[key]
            if isinstance(v, (int, float)) and math.isfinite(v):
                return v
    pos = entity.get("position") or entity.get("geometry")
    if isinstance(pos, dict):
        return pos.get("lon") or pos.get("longitude")
    if isinstance(pos, list) and len(pos) >= 2:
        return pos[0]
    return None


def _extract_entities(layer_data: Any) -> list[dict]:
    """Extract a list of entity dicts from a layer response."""
    if isinstance(layer_data, list):
        return layer_data
    if isinstance(layer_data, dict):
        for key in ("features", "entities", "items", "data", "results", "aircraft", "vessels"):
            if key in layer_data and isinstance(layer_data[key], list):
                return layer_data[key]
    return []


def _check_attribute_condition(entity: dict, condition: dict | None) -> bool:
    """Check if an entity matches an attribute condition."""
    if not condition:
        return True

    field_name = condition.get("field", "")
    operator = condition.get("operator", "eq")
    value = condition.get("value")
    entity_value = entity.get(field_name)

    if entity_value is None:
        return False

    if operator == "eq":
        return entity_value == value
    elif operator == "ne":
        return entity_value != value
    elif operator == "in":
        return entity_value in (value or [])
    elif operator == "not_in":
        return entity_value not in (value or [])
    elif operator == "gt":
        return float(entity_value) > float(value)
    elif operator == "lt":
        return float(entity_value) < float(value)
    elif operator == "gte":
        return float(entity_value) >= float(value)
    elif operator == "lte":
        return float(entity_value) <= float(value)
    elif operator == "contains":
        return str(value).lower() in str(entity_value).lower()
    elif operator == "regex":
        import re
        return bool(re.search(str(value), str(entity_value)))
    elif operator == "between":
        lo, hi = value[0], value[1]
        return lo <= float(entity_value) <= hi

    return False


def _is_emergency(entity: dict) -> bool:
    """Check if an entity is squawking an emergency code."""
    squawk = str(entity.get("squawk", "")).strip()
    return squawk in ("7700", "7600", "7500", "7600")


def _serialize_region(region: Region | None) -> dict | None:
    if region is None:
        return None
    if isinstance(region, CircleRegion):
        return {"type": "circle", "lat": region.lat, "lon": region.lon, "radius_km": region.radius_km}
    if isinstance(region, PolygonRegion):
        return {"type": "polygon", "vertices": region.vertices}
    if isinstance(region, BBoxRegion):
        return {"type": "bbox", "min_lat": region.min_lat, "max_lat": region.max_lat, "min_lon": region.min_lon, "max_lon": region.max_lon}
    return None


def _deserialize_region(data: dict | None) -> Region | None:
    if data is None:
        return None
    t = data.get("type", "")
    if t == "circle":
        return CircleRegion(lat=data["lat"], lon=data["lon"], radius_km=data["radius_km"])
    if t == "polygon":
        return PolygonRegion(vertices=[tuple(v) for v in data["vertices"]])
    if t == "bbox":
        return BBoxRegion(min_lat=data["min_lat"], max_lat=data["max_lat"], min_lon=data["min_lon"], max_lon=data["max_lon"])
    return None


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: GeofenceEngine | None = None


def get_geofence_engine() -> GeofenceEngine:
    global _engine
    if _engine is None:
        _engine = GeofenceEngine()
    return _engine
