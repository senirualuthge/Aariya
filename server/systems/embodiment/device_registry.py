"""
Embodiment / environmental sensor registry (AccessFIles §76).

The doc says: "If connected to hardware" — robotics, IoT, sensors. This
module is the honest foundation for that: it probes what hardware is
ACTUALLY attached to this machine right now (battery, thermal zones, cameras,
displays, storage volumes) and reports exactly that. A missing sensor is
reported as absent, never simulated.

Actuation stays out of here by design: anything that moves the physical
world must go through the pending-action confirmation gate first.
"""

import logging
import os
import sys
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.embodiment")


def probe_devices() -> Dict[str, Any]:
    """Snapshot of every hardware capability we can really detect."""
    devices: Dict[str, Any] = {
        "battery": _probe_battery(),
        "thermal": _probe_thermal(),
        "cameras": _probe_cameras(),
        "display": _probe_display(),
        "volumes": _probe_volumes(),
    }
    available = [
        name for name, val in devices.items()
        if val not in (None, [], False)
    ]
    return {"available": available, "devices": devices,
            "count": len(available)}


def needs_attention(probe: Dict[str, Any]) -> bool:
    """True when a REAL reading crosses an attention threshold (low battery,
    hot thermal zone). Drives the conscious loop's embodiment source."""
    battery = probe.get("devices", {}).get("battery") or {}
    if isinstance(battery, dict):
        pct = battery.get("percent")
        plugged = battery.get("plugged")
        if isinstance(pct, (int, float)) and pct < 15 and not plugged:
            return True
    for zone in (probe.get("devices", {}).get("thermal") or []):
        if isinstance(zone, dict) and zone.get("temp_c", 0) >= 90:
            return True
    return False


# ── Probes ────────────────────────────────────────────────────────────────────

def _probe_battery() -> Optional[Dict[str, Any]]:
    try:
        import psutil
        battery_fn = getattr(psutil, "sensors_battery", None)
        bat: Any = battery_fn() if callable(battery_fn) else None
    except (ImportError, AttributeError, OSError):
        return None
    if bat is None:
        return None
    return {
        "percent": round(bat.percent, 1),
        "plugged": bool(bat.power_plugged),
        "secs_left": bat.secsleft if isinstance(bat.secsleft, int) else None,
    }


def _probe_thermal() -> List[Dict[str, Any]]:
    try:
        import psutil
        temps_fn = getattr(psutil, "sensors_temperatures", None)
        temps: Any = temps_fn() if callable(temps_fn) else {}
    except (ImportError, AttributeError, OSError, NotImplementedError):
        return []
    zones: List[Dict[str, Any]] = []
    for chip, entries in temps.items():
        for entry in entries:
            label = getattr(entry, "label", "") or chip
            current = getattr(entry, "current", None)
            if current is None:
                continue
            zones.append({"zone": label, "temp_c": round(float(current), 1)})
    return zones[:12]


def _probe_cameras() -> List[int]:
    """Real camera probe: indices that open AND yield a frame via OpenCV.
    Probed lazily/cached — opening devices on every tick would be rude.

    Privacy: the CAMERA kill switch (system-wide privacy switch, ToDo §5)
    gates the capture device itself, so when it is OFF this probe never opens
    the lens — not even to count it. Indices are probed in order from 0 and
    stop at the first missing one (cameras enumerate contiguously), which
    avoids pointlessly opening nonexistent devices. OpenCV's native layer
    prints "out device of bound" / "camera failed to properly initialize!"
    straight to fd 2 (invisible to Python try/except), so the probe runs with
    fd 2 muted."""
    global _CAMERA_CACHE, _CAMERA_TS
    import time
    now = time.time()
    if _CAMERA_CACHE is not None and now - _CAMERA_TS < 300:
        return list(_CAMERA_CACHE)
    found: List[int] = []
    try:
        from server.systems.kill_switches import FeatureFlag, get_kill_switches
        camera_on = get_kill_switches().is_enabled(FeatureFlag.CAMERA)
    except Exception:  # kill-switch subsystem unavailable: fall back to probing
        camera_on = True
    if not camera_on:
        _CAMERA_CACHE, _CAMERA_TS = found, now
        return found
    try:
        import cv2
    except ImportError:
        _CAMERA_CACHE, _CAMERA_TS = found, now
        return found
    with _muted_stderr():
        for idx in range(3):  # realistic desktop range; more is speculative
            cap = None
            try:
                cap = cv2.VideoCapture(idx)
                if not cap.isOpened():
                    break  # no camera at this index → none at higher indices
                ok, frame = cap.read()
                if not (ok and frame is not None):
                    break  # opens but yields nothing → not a usable camera
                found.append(idx)
            except Exception:
                break
            finally:
                if cap is not None:
                    cap.release()
    _CAMERA_CACHE, _CAMERA_TS = found, now
    return found


@contextmanager
def _muted_stderr():
    """Temporarily redirect fd 2 to /dev/null (POSIX). OpenCV emits device
    errors from C++ directly on the fd, so silencing them at the Python
    logging level does not work."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        saved = os.dup(2)
    except OSError:
        yield
        return
    try:
        sys.stderr.flush()
        os.dup2(devnull, 2)
        yield
    finally:
        try:
            sys.stderr.flush()
            os.dup2(saved, 2)
            os.close(saved)
        except OSError:
            pass
        os.close(devnull)


_CAMERA_CACHE = None
_CAMERA_TS = 0.0


def _probe_display() -> Optional[Dict[str, int]]:
    try:
        import pyautogui
        size = pyautogui.size()
        return {"width": int(size.width), "height": int(size.height)}
    except Exception:
        pass
    # Fallback without pyautogui: AppKit on macOS reports the main display.
    try:
        from AppKit import NSScreen  # type: ignore
        frame = NSScreen.mainScreen().frame()
        return {"width": int(frame.size.width), "height": int(frame.size.height)}
    except Exception:
        return None


def _probe_volumes() -> List[str]:
    """Mounted readable volumes (real removable media candidates)."""
    try:
        import psutil
        parts = psutil.disk_partitions(all=False)
    except ImportError:
        return []
    out = []
    for p in parts:
        if p.fstype in ("squashfs", "tmpfs", "devtmpfs", "proc", "sysfs"):
            continue
        opts = (p.opts or "").split(",")
        if "ro" in opts:
            continue
        if os.path.isdir(p.mountpoint):
            out.append(p.mountpoint)
    return out
