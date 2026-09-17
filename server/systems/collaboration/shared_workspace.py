"""
Real-Time Collaboration (AccessFIles §75 — gap fill).

Aariya as a collaborative partner needs SHARED WORKSPACE MEMORY: workspaces
with participants, presence, shared notes and tasks that stay consistent
across the dashboard, mobile peers, and other devices.

Everything is real persisted state (data/workspaces/<slug>.json):
  * participants join/leave; presence is a live heartbeat timestamp;
  * notes and tasks are stamped author + device + updated_at;
  * conflicts merge by LAST-WRITE-WINS on updated_at (same rule as §61
    memory sync), and export_workspaces()/import_envelope() plug into the
    peer-sync envelope so collaboration state roams between machines.

An empty workspace honestly contains nothing — nothing here is seeded.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.collab")

_DATA_DIR = os.path.join("data", "workspaces")
_WRITE_LOCK = threading.Lock()


def device_id() -> str:
    from server.systems.memory.sync import device_id as _dev

    return _dev()


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(name or "").strip().lower()).strip("-")
    return slug[:64]


def _path_for(slug: str) -> str:
    return os.path.join(_DATA_DIR, f"{slug}.json")


def _now() -> float:
    return time.time()


class SharedWorkspaceStore:
    """CRUD over real workspace files + LWW merge for peer envelopes."""

    # ── file helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _load(slug: str) -> Optional[Dict[str, Any]]:
        path = _path_for(slug)
        if not os.path.exists(path):
            return None
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("[collab] workspace %s unreadable: %s", slug, exc)
            return None

    @staticmethod
    def _save(slug: str, data: Dict[str, Any]) -> None:
        os.makedirs(_DATA_DIR, exist_ok=True)
        tmp = f"{_path_for(slug)}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, _path_for(slug))

    # ── lifecycle ─────────────────────────────────────────────────────────

    def create(self, name: str, owner: str) -> Dict[str, Any]:
        slug = _slug(name)
        if not slug:
            raise ValueError("workspace name required")
        with _WRITE_LOCK:
            existing = self._load(slug)
            if existing is not None:
                return existing  # idempotent create
            ws = {
                "name": name,
                "slug": slug,
                "owner": owner,
                "created_at": _now(),
                "participants": {},
                "notes": [],
                "tasks": [],
            }
            self._save(slug, ws)
            return ws

    def get(self, name_or_slug: str) -> Optional[Dict[str, Any]]:
        return self._load(_slug(name_or_slug))

    def list(self) -> List[Dict[str, Any]]:
        if not os.path.isdir(_DATA_DIR):
            return []
        out = []
        for fn in sorted(os.listdir(_DATA_DIR)):
            if not fn.endswith(".json"):
                continue
            ws = self._load(fn[:-5])
            if ws:
                out.append(self.summary(ws))
        return out

    @staticmethod
    def summary(ws: Dict[str, Any]) -> Dict[str, Any]:
        online = [p for p, hb in (ws.get("participants") or {}).items()
                  if _now() - float(hb.get("last_seen", 0)) < 120]
        return {
            "name": ws.get("name"),
            "slug": ws.get("slug"),
            "owner": ws.get("owner"),
            "participants": sorted((ws.get("participants") or {}).keys()),
            "online": sorted(online),
            "note_count": len(ws.get("notes") or []),
            "open_tasks": sum(1 for t in ws.get("tasks") or []
                              if t.get("status") == "open"),
        }

    # ── participation / presence ──────────────────────────────────────────

    def join(self, name: str, participant: str) -> Optional[Dict[str, Any]]:
        slug = _slug(name)
        with _WRITE_LOCK:
            ws = self._load(slug)
            if ws is None:
                return None
            parts = ws.setdefault("participants", {})
            prev = parts.get(participant)
            parts[participant] = {
                "device": device_id(),
                "joined_at": float(prev.get("joined_at", 0)) if prev else _now(),
                "last_seen": _now(),
            }
            self._save(slug, ws)
            return {"ok": True, "event": "join", "workspace": ws["name"],
                    "participant": participant}

    def heartbeat(self, name: str, participant: str) -> bool:
        slug = _slug(name)
        with _WRITE_LOCK:
            ws = self._load(slug)
            if ws is None or participant not in (ws.get("participants") or {}):
                return False
            ws["participants"][participant]["last_seen"] = _now()
            self._save(slug, ws)
            return True

    def leave(self, name: str, participant: str) -> bool:
        slug = _slug(name)
        with _WRITE_LOCK:
            ws = self._load(slug)
            if ws is None or participant not in (ws.get("participants") or {}):
                return False
            del ws["participants"][participant]
            self._save(slug, ws)
            return True

    # ── shared content ────────────────────────────────────────────────────

    def post_note(self, name: str, author: str, text: str) -> Optional[Dict[str, Any]]:
        body = str(text or "").strip()
        if not body:
            return None
        slug = _slug(name)
        with _WRITE_LOCK:
            ws = self._load(slug)
            if ws is None:
                return None
            note = {
                "id": uuid.uuid4().hex[:12],
                "author": author,
                "text": body[:2000],
                "updated_at": _now(),
                "updated_by": device_id(),
            }
            ws.setdefault("notes", []).append(note)
            self._save(slug, ws)
            return note

    def add_task(self, name: str, author: str, text: str) -> Optional[Dict[str, Any]]:
        body = str(text or "").strip()
        if not body:
            return None
        slug = _slug(name)
        with _WRITE_LOCK:
            ws = self._load(slug)
            if ws is None:
                return None
            task = {
                "id": uuid.uuid4().hex[:12],
                "author": author,
                "text": body[:500],
                "status": "open",
                "updated_at": _now(),
                "updated_by": device_id(),
            }
            ws.setdefault("tasks", []).append(task)
            self._save(slug, ws)
            return task

    def update_task(self, name: str, task_id: str, *, status: Optional[str] = None,
                    by: str = "") -> Optional[Dict[str, Any]]:
        if status is not None and status not in ("open", "done"):
            return None
        slug = _slug(name)
        with _WRITE_LOCK:
            ws = self._load(slug)
            if ws is None:
                return None
            for task in ws.get("tasks") or []:
                if task.get("id") == task_id:
                    if status is not None:
                        task["status"] = status
                    task["updated_at"] = _now()
                    task["updated_by"] = device_id() or by
                    self._save(slug, ws)
                    return task
        return None

    # ── cross-device roaming (§61-compatible envelope) ─────────────────────

    def export_all(self) -> List[Dict[str, Any]]:
        out = []
        for entry in self.list():
            ws = self.get(entry["slug"])
            if ws:
                out.append(ws)
        return out

    def import_envelope(self, workspaces: List[Dict[str, Any]]) -> Dict[str, int]:
        """Merge a peer's workspaces LWW on item updated_at."""
        merged, skipped = 0, 0
        for peer_ws in workspaces or []:
            slug = _slug(str(peer_ws.get("slug") or peer_ws.get("name") or ""))
            if not slug:
                skipped += 1
                continue
            with _WRITE_LOCK:
                mine = self._load(slug)
                if mine is None:
                    self._save(slug, peer_ws)
                    merged += 1
                    continue
                changed = False
                changed |= self._lww_list(mine, peer_ws, "notes")
                changed |= self._lww_list(mine, peer_ws, "tasks")
                for participant, hb in (peer_ws.get("participants") or {}).items():
                    cur = mine.setdefault("participants", {}).get(participant)
                    if cur is None or float(hb.get("last_seen", 0)) > float(cur.get("last_seen", 0)):
                        mine["participants"][participant] = hb
                        changed = True
                if changed:
                    self._save(slug, mine)
                    merged += 1
                else:
                    skipped += 1
        return {"workspaces_merged": merged, "skipped": skipped}

    @staticmethod
    def _lww_list(mine: Dict[str, Any], peer_ws: Dict[str, Any], key: str) -> bool:
        changed = False
        local_items = {i.get("id"): i for i in mine.get(key) or []}
        for item in peer_ws.get(key) or []:
            iid = item.get("id")
            if not iid:
                continue
            cur = local_items.get(iid)
            if cur is None or float(item.get("updated_at", 0)) > float(cur.get("updated_at", 0)):
                local_items[iid] = item
                changed = True
        if changed:
            mine[key] = list(local_items.values())
        return changed


_store: Optional[SharedWorkspaceStore] = None


def get_workspace_store() -> SharedWorkspaceStore:
    global _store
    if _store is None:
        _store = SharedWorkspaceStore()
    return _store
