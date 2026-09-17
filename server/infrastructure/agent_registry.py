"""
agent_registry.py
─────────────────
Persistent JSON registry that tracks agents across scans.

Each agent entry carries:
  status    : "new" | "existing" | "removed"
  first_seen: ISO timestamp of first discovery
  last_seen : ISO timestamp of most recent scan where it was present

The diff is returned from every update_from_scan() call — callers
(watcher, startup, CLI) can broadcast it to the React frontend.
"""

from __future__ import annotations
import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

DEFAULT_REGISTRY_PATH = Path(__file__).parent / "agent_registry.json"

# How many scans an agent can be absent before being permanently removed
REMOVAL_GRACE_SCANS = 2


class AgentRegistry:
    """
    Thread-safe persistent agent registry.

    Usage:
        registry = AgentRegistry()
        diff = registry.update_from_scan(scanner.scan())
        # diff = {"new": [...], "updated": [...], "removed": [...]}
    """

    def __init__(self, path: Union[str, Path] = DEFAULT_REGISTRY_PATH):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = self._load()

    # ── Public ───────────────────────────────────────────────────────────────

    def update_from_scan(self, scan_results: list[dict]) -> dict:
        """
        Merge a fresh scan into the registry.
        Returns a diff object describing what changed.
        """
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            scanned_ids = {r["id"] for r in scan_results}
            existing_ids = set(self._data["agents"].keys())

            diff = {"new": [], "updated": [], "removed": []}

            # Process current scan results
            for record in scan_results:
                aid = record["id"]
                if aid not in self._data["agents"]:
                    # Genuinely new agent
                    entry = self._make_entry(record, status="new", first_seen=now)
                    self._data["agents"][aid] = entry
                    diff["new"].append(entry)
                else:
                    prev = self._data["agents"][aid]
                    changed = prev["file_hash"] != record["file_hash"]
                    entry = self._make_entry(
                        record,
                        status="new" if prev["status"] == "new" else "existing",
                        first_seen=prev["first_seen"],
                    )
                    entry["last_seen"] = now
                    entry["absent_scans"] = 0
                    self._data["agents"][aid] = entry
                    if changed:
                        diff["updated"].append(entry)

            # Handle agents no longer present in scan
            for aid in existing_ids - scanned_ids:
                entry = self._data["agents"][aid]
                entry["absent_scans"] = entry.get("absent_scans", 0) + 1
                if entry["absent_scans"] >= REMOVAL_GRACE_SCANS:
                    entry["status"] = "removed"
                    diff["removed"].append(entry)

            self._data["last_scan"] = now
            self._data["total_agents"] = len(
                [a for a in self._data["agents"].values() if a["status"] != "removed"]
            )
            self._save()
            return diff

    def register_static_agent(self, record: dict) -> dict:
        """
        Register a single static agent without treating missing agents as absent.
        Returns a diff object describing what changed.
        """
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            aid = record["id"]
            
            diff = {"new": [], "updated": [], "removed": []}
            
            if aid not in self._data["agents"]:
                entry = self._make_entry(record, status="new", first_seen=now)
                self._data["agents"][aid] = entry
                diff["new"].append(entry)
            else:
                prev = self._data["agents"][aid]
                changed = prev["file_hash"] != record["file_hash"]
                entry = self._make_entry(
                    record,
                    status="new" if prev["status"] == "new" else "existing",
                    first_seen=prev["first_seen"],
                )
                entry["last_seen"] = now
                entry["absent_scans"] = 0
                self._data["agents"][aid] = entry
                if changed:
                    diff["updated"].append(entry)
                    
            self._data["total_agents"] = len(
                [a for a in self._data["agents"].values() if a["status"] != "removed"]
            )
            self._save()
            return diff

    def get_all(self) -> dict:
        """Return full registry snapshot."""
        with self._lock:
            return deepcopy(self._data)

    def get_active_agents(self) -> list[dict]:
        """Return only non-removed agents."""
        with self._lock:
            return [
                deepcopy(a)
                for a in self._data["agents"].values()
                if a["status"] != "removed"
            ]

    def acknowledge_new(self, agent_id: str) -> bool:
        """Mark a 'new' agent as 'existing' (called after UI acknowledges it)."""
        with self._lock:
            if agent_id in self._data["agents"]:
                self._data["agents"][agent_id]["status"] = "existing"
                self._save()
                return True
            return False

    def acknowledge_all_new(self):
        """Mark all 'new' agents as 'existing'."""
        with self._lock:
            for entry in self._data["agents"].values():
                if entry["status"] == "new":
                    entry["status"] = "existing"
            self._save()

    def stats(self) -> dict:
        """Quick summary stats for the dashboard."""
        with self._lock:
            agents = list(self._data["agents"].values())
            return {
                "total": len([a for a in agents if a["status"] != "removed"]),
                "new": len([a for a in agents if a["status"] == "new"]),
                "removed": len([a for a in agents if a["status"] == "removed"]),
                "by_detection": self._count_by_key(agents, "detection"),
                "by_kind": self._count_by_key(agents, "kind"),
                "last_scan": self._data.get("last_scan"),
            }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _make_entry(self, record: dict, status: str, first_seen: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return {
            **record,
            "status": status,
            "first_seen": first_seen,
            "last_seen": now,
            "absent_scans": 0,
        }

    def _count_by_key(self, agents: list[dict], key: str) -> dict:
        counts = {}
        for a in agents:
            if a["status"] == "removed":
                continue
            val = a.get(key, "unknown")
            if isinstance(val, list):
                for v in val:
                    counts[v] = counts.get(v, 0) + 1
            else:
                counts[str(val)] = counts.get(str(val), 0) + 1
        return counts

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"last_scan": None, "total_agents": 0, "agents": {}}

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)  # atomic write


# ── Singleton accessor ────────────────────────────────────────────────────────

_registry: Optional[AgentRegistry] = None

def get_registry(path: Union[str, Path] = DEFAULT_REGISTRY_PATH) -> AgentRegistry:
    global _registry
    if _registry is None:
        _registry = AgentRegistry(path)
    return _registry
