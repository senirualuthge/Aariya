"""
swarm_synergy.py
────────────────
Swarm Synergy Bridge — connects GEV intelligence triggers to the rest
of the agent swarm.

When GEV detects a major anomaly (earthquake, emergency squawk, vessel
in restricted zone, etc.), this module automatically dispatches other
agents to gather intelligence and brief the user.

Chain reactions:
  GEV earthquake detected →
    1. Web Search Agent finds breaking news
    2. Data Agent pulls casualty/severity estimates
    3. Aariya proactively briefs the user via voice/text

  GEV emergency squawk detected →
    1. Web Search Agent finds incident reports
    2. Aariya alerts the user with details

  GEV vessel in restricted zone →
    1. OSINT enrichment identifies the vessel
    2. Web Search Agent finds related news
    3. Aariya reports with full context
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from server.systems.gev.geofencing import (
    GeofenceEngine,
    GeofenceRule,
    TriggerType,
    TriggerAction,
    CircleRegion,
    get_geofence_engine,
)

logger = logging.getLogger("aariya.swarm_synergy")


@dataclass
class SynergyRule:
    """Defines a chain reaction triggered by a GEV event."""
    id: str
    name: str
    trigger_layer: str                        # GEV layer that triggers this
    trigger_condition: dict | None = None      # optional filter on the event
    agents_to_dispatch: list[dict] = field(default_factory=list)
    brief_user: bool = True                    # auto-brief via voice/text
    cooldown_seconds: float = 600.0
    priority: str = "high"
    enabled: bool = True
    _last_dispatched_at: float = 0.0


class SwarmSynergyBridge:
    """Connects GEV triggers to agent swarm dispatch.

    ⚡ Power-saving: only activates when specific high-priority events
    are detected by the geofencing engine.
    """

    # Pre-built synergy rules for common scenarios
    PRESET_RULES = [
        SynergyRule(
            id="earthquake_major",
            name="Major Earthquake Response",
            trigger_layer="earthquakes",
            trigger_condition={"field": "magnitude", "operator": "gte", "value": 6.0},
            agents_to_dispatch=[
                {"agent_type": "web_search", "task": "Find breaking news about earthquake", "params": {"query_template": "earthquake {place} magnitude {magnitude} damage casualties"}},
                {"agent_type": "data_analysis", "task": "Pull earthquake severity data", "params": {"source": "USGS", "event_type": "earthquake"}},
            ],
            brief_user=True,
            priority="critical",
        ),
        SynergyRule(
            id="emergency_squawk",
            name="Emergency Squawk Alert",
            trigger_layer="flights",
            trigger_condition={"field": "squawk", "operator": "in", "value": ["7700", "7600", "7500"]},
            agents_to_dispatch=[
                {"agent_type": "web_search", "task": "Find incident reports for emergency aircraft", "params": {"query_template": "aircraft emergency squawk {squawk} {callsign}"}},
            ],
            brief_user=True,
            priority="high",
        ),
        SynergyRule(
            id="major_fire",
            name="Major Wildfire Detection",
            trigger_layer="fires",
            trigger_condition={"field": "frp", "operator": "gt", "value": 100},
            agents_to_dispatch=[
                {"agent_type": "web_search", "task": "Find wildfire news and evacuation info", "params": {"query_template": "wildfire fire {lat} {lon} evacuation"}},
            ],
            brief_user=True,
            priority="high",
        ),
        SynergyRule(
            id="vessel_restricted_zone",
            name="Vessel in Restricted Zone",
            trigger_layer="vessels",
            trigger_condition={"field": "zone_type", "operator": "eq", "value": "restricted"},
            agents_to_dispatch=[
                {"agent_type": "osint_enrich", "task": "Enrich vessel identity", "params": {}},
                {"agent_type": "web_search", "task": "Find related news", "params": {"query_template": "vessel {name} restricted zone {zone_name}"}},
            ],
            brief_user=True,
            priority="high",
        ),
        SynergyRule(
            id="tsunami_warning",
            name="Tsunami Warning",
            trigger_layer="earthquakes",
            trigger_condition={"field": "magnitude", "operator": "gte", "value": 7.0},
            agents_to_dispatch=[
                {"agent_type": "web_search", "task": "Find tsunami warning details", "params": {"query_template": "tsunami warning earthquake magnitude {magnitude}"}},
                {"agent_type": "data_analysis", "task": "Pull tsunami forecast data", "params": {"source": "PTWC"}},
            ],
            brief_user=True,
            priority="critical",
        ),
        SynergyRule(
            id="space_weather_severe",
            name="Severe Space Weather",
            trigger_layer="space_weather",
            trigger_condition={"field": "kp", "operator": "gte", "value": 7},
            agents_to_dispatch=[
                {"agent_type": "web_search", "task": "Find geomagnetic storm impacts", "params": {"query_template": "geomagnetic storm Kp {kp} power grid satellite impact"}},
            ],
            brief_user=True,
            priority="medium",
        ),
    ]

    def __init__(self, geofence_engine: GeofenceEngine | None = None):
        self._engine = geofence_engine or get_geofence_engine()
        self._synergy_rules: dict[str, SynergyRule] = {}
        self._dispatch_log: list[dict] = []
        self._max_log = 200
        self._dispatch_callbacks: list[Callable[[dict], Any]] = []

        # Load preset rules
        for rule in self.PRESET_RULES:
            self._synergy_rules[rule.id] = rule

        # Register with geofence engine
        self._engine.on_trigger(self._on_geofence_trigger)

    # ── Rule management ───────────────────────────────────────────────────────

    def add_rule(self, rule: SynergyRule) -> None:
        self._synergy_rules[rule.id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        return self._synergy_rules.pop(rule_id, None) is not None

    def list_rules(self) -> list[dict]:
        return [
            {
                "id": r.id,
                "name": r.name,
                "trigger_layer": r.trigger_layer,
                "enabled": r.enabled,
                "agents_to_dispatch": len(r.agents_to_dispatch),
                "brief_user": r.brief_user,
                "priority": r.priority,
                "_last_dispatched_at": r._last_dispatched_at,
            }
            for r in self._synergy_rules.values()
        ]

    # ── Dispatch system ───────────────────────────────────────────────────────

    def on_dispatch(self, callback: Callable[[dict], Any]) -> None:
        """Register a callback for when agents are dispatched.

        The callback receives a dispatch request dict. The orchestrator
        should actually invoke the agents.
        """
        self._dispatch_callbacks.append(callback)

    def dispatch_agent(self, agent_type: str, task: str, params: dict | None = None) -> dict:
        """Create and return a dispatch request (doesn't execute).

        The orchestrator or brain calls this to get the dispatch spec,
        then actually invokes the target agent.
        """
        request = {
            "agent_type": agent_type,
            "task": task,
            "params": params or {},
            "timestamp": time.time(),
        }
        return request

    async def execute_dispatch(self, dispatch_request: dict) -> dict:
        """Execute a single agent dispatch.

        This is called by the orchestrator when it receives a dispatch request.
        Returns the result from the dispatched agent.
        """
        agent_type = dispatch_request.get("agent_type", "")
        task = dispatch_request.get("task", "")
        params = dispatch_request.get("params", {})

        logger.info("[SwarmSynergy] Dispatching %s: %s", agent_type, task)

        # For now, return the dispatch request as a pending action
        # The actual agent invocation happens through the brain/orchestrator
        return {
            "status": "dispatched",
            "agent_type": agent_type,
            "task": task,
            "params": params,
            "dispatched_at": time.time(),
        }

    # ── Trigger handling ──────────────────────────────────────────────────────

    def _on_geofence_trigger(self, event: dict) -> None:
        """Handle a geofence trigger event by evaluating synergy rules."""
        layer = event.get("layer", "")
        now = time.time()

        for rule in self._synergy_rules.values():
            if not rule.enabled:
                continue

            # Cooldown check
            if (now - rule._last_dispatched_at) < rule.cooldown_seconds:
                continue

            # Layer match
            if rule.trigger_layer != layer:
                continue

            # Condition check (on the first triggered entity)
            if rule.trigger_condition:
                entities = event.get("entities", [])
                if entities:
                    entity_data = entities[0].get("data", {})
                    from server.systems.gev.geofencing import _check_attribute_condition
                    if not _check_attribute_condition(entity_data, rule.trigger_condition):
                        continue

            # Trigger matched — dispatch agents
            rule._last_dispatched_at = now
            dispatch_requests = []

            for agent_spec in rule.agents_to_dispatch:
                # Fill template params from the event
                filled_params = self._fill_template(
                    agent_spec.get("params", {}),
                    event,
                )
                request = self.dispatch_agent(
                    agent_type=agent_spec["agent_type"],
                    task=agent_spec["task"],
                    params=filled_params,
                )
                dispatch_requests.append(request)

            # Create synergy event
            synergy_event = {
                "synergy_rule": rule.id,
                "trigger_event": event,
                "dispatch_requests": dispatch_requests,
                "brief_user": rule.brief_user,
                "priority": rule.priority,
                "timestamp": now,
            }

            self._dispatch_log.append(synergy_event)
            if len(self._dispatch_log) > self._max_log:
                self._dispatch_log = self._dispatch_log[-self._max_log:]

            # Notify callbacks
            for cb in self._dispatch_callbacks:
                try:
                    cb(synergy_event)
                except Exception as e:
                    logger.warning("[SwarmSynergy] Callback error: %s", e)

            logger.info(
                "[SwarmSynergy] Rule '%s' triggered: dispatching %d agent(s)",
                rule.name, len(dispatch_requests),
            )

    def _fill_template(self, params: dict, event: dict) -> dict:
        """Fill template variables in dispatch params from event data."""
        filled = {}
        entities = event.get("entities", [])
        first_entity = entities[0].get("data", {}) if entities else {}

        for key, value in params.items():
            if isinstance(value, str):
                # Simple template replacement
                value = value.replace("{layer}", event.get("layer", ""))
                value = value.replace("{rule_name}", event.get("rule_name", ""))
                value = value.replace("{squawk}", str(first_entity.get("squawk", "")))
                value = value.replace("{callsign}", str(first_entity.get("callsign", "")))
                value = value.replace("{name}", str(first_entity.get("name", "")))
                value = value.replace("{lat}", str(first_entity.get("lat", "")))
                value = value.replace("{lon}", str(first_entity.get("lon", "")))
                value = value.replace("{magnitude}", str(first_entity.get("magnitude", "")))
                value = value.replace("{place}", str(first_entity.get("place", "")))
                value = value.replace("{kp}", str(first_entity.get("kp", "")))
            filled[key] = value
        return filled

    # ── Log access ────────────────────────────────────────────────────────────

    def get_dispatch_log(self, limit: int = 50) -> list[dict]:
        return self._dispatch_log[-limit:]

    def get_stats(self) -> dict:
        enabled = sum(1 for r in self._synergy_rules.values() if r.enabled)
        dispatched = sum(1 for r in self._synergy_rules.values() if r._last_dispatched_at > 0)
        return {
            "total_rules": len(self._synergy_rules),
            "enabled_rules": enabled,
            "total_dispatches": len(self._dispatch_log),
            "rules_dispatched": dispatched,
        }

    # ── Serialisation ─────────────────────────────────────────────────────────

    def export_rules(self) -> list[dict]:
        return [
            {
                "id": r.id,
                "name": r.name,
                "trigger_layer": r.trigger_layer,
                "trigger_condition": r.trigger_condition,
                "agents_to_dispatch": r.agents_to_dispatch,
                "brief_user": r.brief_user,
                "cooldown_seconds": r.cooldown_seconds,
                "priority": r.priority,
                "enabled": r.enabled,
            }
            for r in self._synergy_rules.values()
        ]

    def import_rules(self, rules: list[dict]) -> int:
        count = 0
        for r in rules:
            try:
                rule = SynergyRule(
                    id=r["id"],
                    name=r.get("name", ""),
                    trigger_layer=r["trigger_layer"],
                    trigger_condition=r.get("trigger_condition"),
                    agents_to_dispatch=r.get("agents_to_dispatch", []),
                    brief_user=r.get("brief_user", True),
                    cooldown_seconds=r.get("cooldown_seconds", 600),
                    priority=r.get("priority", "high"),
                    enabled=r.get("enabled", True),
                )
                self._synergy_rules[rule.id] = rule
                count += 1
            except Exception as e:
                logger.warning("[SwarmSynergy] Failed to import rule: %s", e)
        return count


# ── Singleton ─────────────────────────────────────────────────────────────────

_bridge: SwarmSynergyBridge | None = None


def get_swarm_synergy_bridge() -> SwarmSynergyBridge:
    global _bridge
    if _bridge is None:
        _bridge = SwarmSynergyBridge()
    return _bridge
