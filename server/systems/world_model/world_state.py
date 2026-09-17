"""
world_state.py — World State Snapshot, the single source of truth.
───────────────────────────────────────────────────────────────────
(NEWPredictionPRT2 §"4. Single Source of Truth (World State Snapshot)" +
§"1. World State Engine".)

At any moment:

    world_state = {
        "user": {}, "system": {}, "agents": {}, "tasks": {},
        "resources": {}, "environment": {}, "confidence": {}
    }

Everything reads from here; nothing bypasses it. The brain, the 24/7 autonomy
daemon, and the API routers all read/write one canonical persisted store so
they never hold disjoint state.

The financial categories in the source doc ("climate"/"economy") are
DEPRECATED and OUT OF SCOPE — the store keeps the general cognitive/runtime
categories instead.
"""

import json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("aariya.world_state")

# The canonical top-level categories (order is the doc's snapshot shape).
CATEGORIES = (
    "user", "system", "agents", "tasks", "resources", "environment", "confidence",
)


class WorldState:
    """Thread-safe, JSON-persisted canonical world state.

    `update(category, key, value)` is the ONLY write path; `get`/`snapshot`
    are the only read paths. Unknown categories are refused so a typo can't
    silently create a parallel namespace.
    """

    def __init__(self, persist_path: Optional[str] = None):
        self._lock = threading.RLock()
        self._persist_path = persist_path
        self._state: Dict[str, Dict[str, Any]] = {c: {} for c in CATEGORIES}
        self._meta: Dict[str, Any] = {
            "version": 1,
            "created_at": time.time(),
            "updated_at": time.time(),
            "writes": 0,
        }
        if persist_path:
            self._load()

    # ── Write ────────────────────────────────────────────────────────────────

    def update(self, category: str, key: str, value: Any) -> None:
        """Set one key in a category. Refuses unknown categories."""
        if category not in CATEGORIES:
            logger.warning("[WorldState] refused unknown category '%s'", category)
            return
        with self._lock:
            self._state[category][key] = value
            self._meta["updated_at"] = time.time()
            self._meta["writes"] += 1
            self._save()

    def update_many(self, category: str, mapping: Dict[str, Any]) -> None:
        """Bulk-set a category from a dict — atomic, single persist."""
        if category not in CATEGORIES:
            logger.warning("[WorldState] refused unknown category '%s'", category)
            return
        with self._lock:
            self._state[category].update(mapping or {})
            self._meta["updated_at"] = time.time()
            self._meta["writes"] += 1
            self._save()

    def touch(self) -> None:
        """Bump the freshness marker without changing state (heartbeats)."""
        with self._lock:
            self._meta["updated_at"] = time.time()
            self._save()

    # ── Read ─────────────────────────────────────────────────────────────────

    def get(self, category: str, key: str, default: Any = None) -> Any:
        if category not in CATEGORIES:
            return default
        with self._lock:
            return self._state[category].get(key, default)

    def get_category(self, category: str) -> Dict[str, Any]:
        if category not in CATEGORIES:
            return {}
        with self._lock:
            return dict(self._state[category])

    def snapshot(self) -> Dict[str, Any]:
        """The full canonical state — the single source of truth for any reader."""
        with self._lock:
            return {
                "state": {c: dict(self._state[c]) for c in CATEGORIES},
                "meta": dict(self._meta),
            }

    # ── Persistence ──────────────────────────────────────────────────────────

    def _save(self) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path) or ".", exist_ok=True)
            with open(self._persist_path, "w") as fh:
                json.dump(
                    {"state": self._state, "meta": self._meta},
                    fh, indent=2, default=str,
                )
        except Exception as exc:
            logger.warning("[WorldState] persist failed: %s", exc)

    def _load(self) -> None:
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path) as fh:
                data = json.load(fh)
            loaded = data.get("state") or {}
            for c in CATEGORIES:
                if isinstance(loaded.get(c), dict):
                    self._state[c] = dict(loaded[c])
            if isinstance(data.get("meta"), dict):
                self._meta.update({k: v for k, v in data["meta"].items()})
        except Exception as exc:
            logger.warning("[WorldState] load failed (fresh start): %s", exc)


# ── Shared singleton ───────────────────────────────────────────────────────────

_singleton: Optional[WorldState] = None


def get_world_state(persist_path: str = "data/world_state.json") -> WorldState:
    """Shared WorldState so the router, brain, and daemon all read/write ONE
    canonical store instead of each holding a disjoint in-memory copy."""
    global _singleton
    if _singleton is None:
        _singleton = WorldState(persist_path=persist_path)
    return _singleton
