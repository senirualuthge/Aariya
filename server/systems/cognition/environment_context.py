"""
Environmental Intelligence (*AccessFIles.txt* §88).

Not just filesystem awareness — one honest snapshot of the machine's whole
context: time, schedule/meeting state, hardware, power, thermal, desktop
focus. Everything comes from REAL probes (psutil via EnergyManager /
device_registry, the desktop twin's actual observations, the live meeting
mode). Channels that cannot be measured on this machine (e.g. geo location)
are reported as unavailable — never fabricated.

`signals_for_autonomy()` distills the snapshot into the booleans the
conscious loop and proactive engine reason about.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger("aariya.environment_context")

_LOW_BATTERY_PCT = 20.0
_HOT_THERMAL_C = 85.0
_IDLE_CPU_PCT = 12.0


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


class EnvironmentContext:
    def __init__(self):
        self._lock = threading.Lock()
        self._last: Dict[str, Any] = {}

    def snapshot(self) -> Dict[str, Any]:
        """Aggregate every real source available right now."""
        now = datetime.now()
        snap: Dict[str, Any] = {
            "ts": now.timestamp(),
            "time": {
                "iso": now.isoformat(timespec="seconds"),
                "weekday": now.strftime("%A"),
                "hour": now.hour,
                "part_of_day": _part_of_day(now.hour),
            },
        }

        # Machine power/thermal/load — real psutil readings.
        try:
            from server.systems.resources.energy_manager import get_energy_manager
            energy = get_energy_manager().evaluate()
            snap["machine"] = {
                "mode": energy.get("mode"),
                "pressure": energy.get("pressure"),
                "cpu_percent": energy.get("reading", {}).get("cpu_percent"),
                "memory_percent": energy.get("reading", {}).get("memory_percent"),
                "battery": energy.get("reading", {}).get("battery"),
                "thermal": energy.get("reading", {}).get("thermal"),
            }
        except Exception as exc:
            snap["machine"] = {"error": f"unavailable: {exc}"}

        # Attached hardware capabilities — real probes only.
        try:
            from server.systems.embodiment.device_registry import probe_devices
            snap["devices"] = probe_devices()
        except Exception as exc:
            snap["devices"] = {"error": f"unavailable: {exc}"}

        # What the user is actually doing on the desktop (real observations).
        try:
            from server.systems.desktop_twin import get_desktop_twin
            snap["desktop"] = get_desktop_twin().context()
        except Exception as exc:
            snap["desktop"] = {"error": f"unavailable: {exc}"}

        # Meeting / conversation ambience (live audio state).
        try:
            from server.systems.meeting_mode import get_meeting_mode
            status = get_meeting_mode().get_status()
            snap["meeting"] = status
        except Exception as exc:
            snap["meeting"] = {"error": f"unavailable: {exc}"}

        # Geo location: no sensor on this machine → say so, never invent.
        snap["location"] = {"available": False,
                            "reason": "no location source probed on this machine"}

        with self._lock:
            self._last = snap
        return snap

    def signals_for_autonomy(self) -> Dict[str, Any]:
        """Booleans derived ONLY from fields actually present in the snapshot.

        A signal stays None when its source reading is missing — callers must
        treat None as 'unknown', not false.
        """
        snap = self.snapshot() if not self._last else self._last
        machine = snap.get("machine") or {}
        battery = (machine.get("battery") or {}) if isinstance(machine.get("battery"), dict) else {}

        signals: Dict[str, Any] = {
            "meeting_active": None,
            "low_power": None,
            "thermal_hot": None,
            "idle_machine": None,
            "external_display": None,
            "camera_present": None,
        }

        meeting = snap.get("meeting") or {}
        if isinstance(meeting.get("active"), bool):
            signals["meeting_active"] = meeting["active"]

        if battery.get("available") and isinstance(battery.get("percent"), (int, float)):
            signals["low_power"] = (
                battery.get("percent", 100) < _LOW_BATTERY_PCT
                and not battery.get("plugged", True))

        thermal = machine.get("thermal") or []
        if isinstance(thermal, list) and thermal:
            temps = [z.get("temp_c") for z in thermal
                     if isinstance(z, dict) and isinstance(z.get("temp_c"), (int, float))]
            if temps:
                signals["thermal_hot"] = max(temps) >= _HOT_THERMAL_C  # type: ignore[arg-type]

        cpu = machine.get("cpu_percent")
        if isinstance(cpu, (int, float)):
            signals["idle_machine"] = cpu < _IDLE_CPU_PCT

        devices = ((snap.get("devices") or {}).get("devices")) or {}
        display = devices.get("display")
        if isinstance(display, dict):
            signals["external_display"] = display.get("monitors", 1) > 1
        cameras = devices.get("cameras")
        if isinstance(cameras, list):
            signals["camera_present"] = len(cameras) > 0

        return {"ts": snap.get("ts"), "signals": signals}


_inst: Optional[EnvironmentContext] = None
_inst_lock = threading.Lock()


def get_environment_context() -> EnvironmentContext:
    global _inst
    with _inst_lock:
        if _inst is None:
            _inst = EnvironmentContext()
        return _inst
