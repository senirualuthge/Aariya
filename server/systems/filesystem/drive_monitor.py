"""
External drive detection via psutil (graceful no-op when psutil is absent).

Used by the filesystem agent to enumerate USB drives / mounted volumes so
Aariya can index portable media without guessing mount points.
"""

import logging
from typing import List, Dict

logger = logging.getLogger("aariya.drive_monitor")

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.info("psutil not installed — drive detection disabled")


def detect_external_drives() -> List[Dict]:
    """List mounted volumes, marking removable/network mounts when possible."""
    if not PSUTIL_AVAILABLE:
        return []
    drives = []
    try:
        for part in psutil.disk_partitions(all=True):
            is_removable = "removable" in (part.opts or "").lower()
            drives.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "opts": part.opts,
                "removable": is_removable,
            })
    except Exception as e:
        logger.warning(f"[drive_monitor] detection failed: {e}")
    return drives


def removable_drives() -> List[Dict]:
    return [d for d in detect_external_drives() if d.get("removable")]
