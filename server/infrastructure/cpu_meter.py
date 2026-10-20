"""One consistent system-wide CPU reading for the whole process.

Why this exists
---------------
``psutil.cpu_percent(interval=None)`` reports the CPU usage *since the last call
to it anywhere in the process* — the baseline lives in psutil's module state.
Every caller therefore consumes and resets every other caller's measurement
window. Aariya has several consumers sampling on timers:

  * ``/ws/mobile/analytics``        — 1 Hz per connected phone
  * ``system_health`` broadcaster   — 2 s heartbeat
  * the autonomy daemon's health source
  * the cognitive shard handler
  * the energy manager snapshot
  * the RAG runtime telemetry

With two phones connected, each 1 Hz frame measured whatever sliver of time was
left since another consumer's read. The observable result was the same machine
reported as ``100.0`` to one client and ``0.0`` to another in the same second —
so the mobile app's PROCESSOR card appeared to lag or stick.

How it works
------------
``psutil.cpu_times()`` returns *cumulative* counters. Percentages are derived
from the delta between two snapshots, so no caller can clobber another's
baseline. The result is cached briefly ([_CACHE_TTL]) so consumers sampling at
the same moment share one computation and report the same number.

Usage::

    from server.infrastructure.cpu_meter import cpu_percent, cpu_percent_per_core

    value = cpu_percent()            # float, 0..100
    cores = cpu_percent_per_core()   # list[float], one per logical core

The first call in a process returns 0.0 (there is no previous snapshot to
subtract); every call after it is a real measurement.
"""

from __future__ import annotations

import threading
import time
from typing import List, Optional, Tuple

import psutil

# Reuse a computed value for this long. Slightly under the fastest consumer
# cadence (1 Hz analytics), so a 1 s stream still gets a fresh number each
# frame while simultaneous readers agree.
_CACHE_TTL = 0.9

_lock = threading.Lock()

# (monotonic timestamp, total ticks, idle ticks)
_prev: Optional[Tuple[float, float, float]] = None
_cache: Optional[Tuple[float, float]] = None  # (monotonic ts, rounded percent)

_prev_core: Optional[Tuple[float, List[Tuple[float, float]]]] = None
_cache_core: Optional[Tuple[float, List[float]]] = None


def _split(times) -> Tuple[float, float]:
    """(total, idle) ticks from a ``psutil.cpu_times()`` entry.

    ``guest``/``guest_nice`` are excluded: on Linux they are already accounted
    for inside ``user``, so adding them would double-count busy time.
    ``iowait`` counts as idle, standard Linux accounting.
    """
    fields = times._asdict()
    idle = float(fields.get("idle", 0.0)) + float(fields.get("iowait", 0.0))
    total = sum(
        float(v) for k, v in fields.items() if k not in ("guest", "guest_nice")
    )
    return total, idle


def _percent(prev_total: float, prev_idle: float, total: float, idle: float) -> float:
    d_total = total - prev_total
    d_idle = idle - prev_idle
    if d_total <= 0:
        return 0.0
    value = 100.0 * (1.0 - d_idle / d_total)
    return max(0.0, min(100.0, value))


def cpu_percent() -> float:
    """System-wide CPU usage as a percentage (0..100), one decimal place."""
    global _prev, _cache

    now = time.monotonic()
    with _lock:
        if _cache is not None and now - _cache[0] < _CACHE_TTL:
            return _cache[1]

        total, idle = _split(psutil.cpu_times())

        if _prev is None:
            value = 0.0  # no previous snapshot yet
        else:
            value = _percent(_prev[1], _prev[2], total, idle)

        _prev = (now, total, idle)
        rounded = round(value, 1)
        _cache = (now, rounded)
        return rounded


def cpu_percent_per_core() -> List[float]:
    """Per-logical-core CPU usage (0..100 each). Empty if unsupported."""
    global _prev_core, _cache_core

    now = time.monotonic()
    with _lock:
        if _cache_core is not None and now - _cache_core[0] < _CACHE_TTL:
            return list(_cache_core[1])

        try:
            snapshots = [_split(t) for t in psutil.cpu_times(percpu=True)]
        except Exception:
            return []

        if _prev_core is None or len(_prev_core[1]) != len(snapshots):
            values = [0.0 for _ in snapshots]
        else:
            values = [
                round(_percent(prev[0], prev[1], cur[0], cur[1]), 1)
                for prev, cur in zip(_prev_core[1], snapshots)
            ]

        _prev_core = (now, snapshots)
        _cache_core = (now, values)
        return list(values)


def reset() -> None:
    """Drop the cached snapshots. Test seam only."""
    global _prev, _cache, _prev_core, _cache_core
    with _lock:
        _prev = None
        _cache = None
        _prev_core = None
        _cache_core = None
