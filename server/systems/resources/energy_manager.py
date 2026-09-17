"""
Energy / Resource Optimization (AccessFIles §94 — gap fill).

Persistent cognition is computationally expensive, so background work must
yield to REAL machine pressure. This module reads only psutil-truth:

  * CPU utilisation, memory pressure, load average, own process RSS;
  * battery state when the machine actually reports one (None → honest
    "unavailable", never an invented percentage);
  * thermal zones where the OS exposes them.

From those signals it derives a pressure score (0..1), a mode
(full / conservation / sleep) with hysteresis so the system can't flap, and a
gate the autonomy daemon consults before running maintenance passes
(memory consolidation, graph ingestion, indexing).

Thresholds are env-tunable (AARIYA_ENERGY_*); defaults are conservative and
documented. No synthetic readings anywhere.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("aariya.energy_manager")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


# Mode thresholds (pressure 0..1). Hysteresis: entering sleep needs HIGH,
# leaving it needs below SLEEP_EXIT — prevents oscillation.
_CONSERVATION_ENTER = _env_float("AARIYA_ENERGY_CONSERVATION_AT", 0.55)
_SLEEP_ENTER = _env_float("AARIYA_ENERGY_SLEEP_AT", 0.85)
_SLEEP_EXIT = _env_float("AARIYA_ENERGY_SLEEP_EXIT", 0.60)
_MIN_DWELL_S = _env_float("AARIYA_ENERGY_MIN_DWELL_S", 30.0)

# Battery deficit weight: unplugged & low battery raises pressure even at
# idle CPU (the doc's "sleep states" trigger on power, not just load).
_BATTERY_LOW_PCT = _env_float("AARIYA_ENERGY_BATTERY_LOW_PCT", 25.0)


def snapshot() -> Dict[str, Any]:
    """One honest psutil reading of everything this module reasons about."""
    import psutil

    data: Dict[str, Any] = {
        "ts": time.time(),
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
        "loadavg": [round(x, 2) for x in (psutil.getloadavg() if hasattr(psutil, "getloadavg") else ())],
    }
    try:
        proc = psutil.Process()
        data["process_rss_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
    except Exception:
        data["process_rss_mb"] = None

    # Battery: None on desktops / unsupported platforms — reported as such.
    battery: Dict[str, Any] = {"available": False}
    try:
        bat = psutil.sensors_battery()
        if bat is not None:
            battery = {
                "available": True,
                "percent": round(float(bat.percent), 1),
                "plugged": bool(bat.power_plugged),
            }
    except (AttributeError, NotImplementedError, OSError) as exc:
        logger.debug("[EnergyManager] battery sensor unavailable: %s", exc)
    data["battery"] = battery

    # Thermal: real zones where exposed; empty list is the honest answer.
    thermal: list = []
    try:
        sensor_fn = getattr(psutil, "sensors_temperatures", None)
        if callable(sensor_fn):
            for zone, entries in (sensor_fn() or {}).items():  # type: ignore[union-attr]
                for e in entries or []:
                    if getattr(e, "current", None):
                        thermal.append({"zone": f"{zone}/{e.label or ''}".strip("/"),
                                        "temp_c": round(float(e.current), 1)})
    except (AttributeError, NotImplementedError, OSError) as exc:
        logger.debug("[EnergyManager] thermal sensor unavailable: %s", exc)
    data["thermal"] = thermal
    return data


def compute_pressure(reading: Optional[Dict[str, Any]] = None) -> float:
    """Combine real signals into one 0..1 pressure score.

    Weights: cpu (0..1) 40%, memory 20%, battery deficit up to 25% when
    unplugged-and-low, thermal headroom up to 15% (hottest zone vs 90°C).
    """
    r = reading or snapshot()
    cpu = min(max(float(r.get("cpu_percent") or 0.0), 0.0), 100.0) / 100.0
    mem = min(max(float(r.get("memory_percent") or 0.0), 0.0), 100.0) / 100.0
    pressure = 0.4 * cpu + 0.2 * mem

    battery = r.get("battery") or {}
    if battery.get("available") and not battery.get("plugged"):
        pct = max(0.0, min(100.0, float(battery.get("percent") or 0.0)))
        deficit = max(0.0, (_BATTERY_LOW_PCT * 2 - pct)) / (_BATTERY_LOW_PCT * 2)
        pressure += 0.25 * min(1.0, deficit)

    hottest = max((float(z.get("temp_c") or 0.0) for z in r.get("thermal") or []),
                  default=0.0)
    if hottest >= 50.0:
        pressure += 0.15 * min(1.0, (hottest - 50.0) / 40.0)

    return round(min(1.0, pressure), 3)


class EnergyManager:
    """Hysteresis state machine over live pressure readings."""

    def __init__(self):
        self.mode: str = "full"
        self._last_switch = 0.0
        self._lock = threading.Lock()
        # Instance copies of the module defaults so operators can tune a
        # manager without mutating global config.
        self.conservation_at = _CONSERVATION_ENTER
        self.sleep_at = _SLEEP_ENTER
        self.sleep_exit = _SLEEP_EXIT
        self.min_dwell_s = _MIN_DWELL_S

    def evaluate(self, reading: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Update + return current mode from a fresh (or given) reading."""
        with self._lock:
            r = reading or snapshot()
            pressure = compute_pressure(r)
            now = time.time()
            prev = self.mode

            if prev == "sleep":
                # Leaving sleep requires dropping below the exit threshold.
                new = "conservation" if pressure < self.sleep_exit else "sleep"
            elif prev == "conservation":
                if pressure <= self.conservation_at:
                    new = "full"
                elif pressure >= self.sleep_at:
                    new = "sleep"
                else:
                    new = prev
            else:  # full
                if pressure >= self.sleep_at:
                    new = "sleep"
                elif pressure >= self.conservation_at:
                    new = "conservation"
                else:
                    new = "full"

            # Hysteresis: no bouncing back to full inside the dwell window.
            dwell_protected = (
                prev != "full" and new == "full"
                and now - self._last_switch < self.min_dwell_s
            )
            if dwell_protected:
                new = prev
            if new != prev:
                self.mode = new
                self._last_switch = now
                logger.info("[energy] mode %s → %s (pressure=%.2f)", prev, new, pressure)

            return {
                "mode": self.mode,
                "pressure": pressure,
                "previous_mode": prev,
                "reading": {
                    k: r[k] for k in ("cpu_percent", "memory_percent",
                                      "battery", "thermal") if k in r
                },
            }

    def allow_background_work(self) -> bool:
        """Gate for daemon maintenance ticks: sleep blocks heavy work,
        conservation allows light passes, full allows everything."""
        return self.evaluate()["mode"] != "sleep"

    def status(self) -> Dict[str, Any]:
        return self.evaluate()


_instance: Optional[EnergyManager] = None
_instance_lock = threading.Lock()


def get_energy_manager() -> EnergyManager:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = EnergyManager()
        return _instance
