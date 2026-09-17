"""
Internal Thought Stream (AccessFIles §52 — gap fill).

Instead of reacting only to prompts, Aariya maintains a PERSISTED journal of
her inner life between interactions:

  * hypotheses        — "user may need X tomorrow"
  * notes             — observations worth keeping
  * unresolved_tasks  — things noticed but not yet handled
  * active_goals      — currently pursued intentions

Every thought lives in a real JSONL journal (data/thought_stream_<user>.jsonl)
with an open → resolved | dismissed state machine, so cognition survives
restarts. The conscious loop's REAL insights flow in via capture_from_tick();
with no insights there is nothing to record — never seeded filler.
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

logger = logging.getLogger("aariya.thought_stream")

_DATA_DIR = os.path.join("data")
_KINDS = ("hypothesis", "note", "unresolved_task", "active_goal")
_OPEN = "open"

_LOCK = threading.Lock()
_instances: Dict[str, "ThoughtStream"] = {}


def _slug(user_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", user_id or "default").strip("_") or "default"


class ThoughtStream:
    """Append-only thought journal with resolve/dismiss transitions."""

    def __init__(self, user_id: str = "default", path: Optional[str] = None):
        self.user_id = user_id
        self.path = path or os.path.join(_DATA_DIR, f"thought_stream_{_slug(user_id)}.jsonl")

    # ── persistence helpers ───────────────────────────────────────────────

    def _read_all(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        entries: List[Dict[str, Any]] = []
        try:
            with open(self.path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.debug("[thoughts] skipping corrupt journal line")
        except OSError as exc:
            logger.warning("[thoughts] journal read failed: %s", exc)
        return entries

    def _append(self, entry: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def _rewrite(self, entries: List[Dict[str, Any]]) -> None:
        tmp = f"{self.path}.tmp"
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        os.replace(tmp, self.path)

    # ── public API ────────────────────────────────────────────────────────

    def add(self, kind: str, text: str, *, meta: Optional[Dict[str, Any]] = None,
            source: str = "self") -> Optional[Dict[str, Any]]:
        """Record a new thought. Unknown kinds and empty text are refused."""
        kind = str(kind or "").strip()
        body = str(text or "").strip()
        if kind not in _KINDS or not body:
            return None
        entry = {
            "id": uuid.uuid4().hex[:12],
            "kind": kind,
            "text": body[:500],
            "status": _OPEN,
            "source": source,
            "meta": meta or {},
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        with _LOCK:
            self._append(entry)
        return entry

    def _transition(self, thought_id: str, status: str, note: str = "") -> Optional[Dict[str, Any]]:
        with _LOCK:
            entries = self._read_all()
            for e in entries:
                if e.get("id") == thought_id and e.get("status") == _OPEN:
                    e["status"] = status
                    e["updated_at"] = time.time()
                    if note:
                        e["resolution"] = note[:300]
                    self._rewrite(entries)
                    return e
        return None  # unknown id or already closed — honest no-op

    def resolve(self, thought_id: str, note: str = "") -> Optional[Dict[str, Any]]:
        return self._transition(thought_id, "resolved", note)

    def dismiss(self, thought_id: str, note: str = "") -> Optional[Dict[str, Any]]:
        return self._transition(thought_id, "dismissed", note)

    def open_thoughts(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = [e for e in self._read_all() if e.get("status") == _OPEN]
        rows.sort(key=lambda e: float(e.get("created_at", 0)), reverse=True)
        return rows[: max(0, limit)]

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = sorted(self._read_all(),
                      key=lambda e: float(e.get("created_at", 0)), reverse=True)
        return rows[: max(0, limit)]

    def stats(self) -> Dict[str, Any]:
        entries = self._read_all()
        by_status: Dict[str, int] = {}
        by_kind: Dict[str, int] = {}
        for e in entries:
            by_status[e.get("status", "?")] = by_status.get(e.get("status", "?"), 0) + 1
            by_kind[e.get("kind", "?")] = by_kind.get(e.get("kind", "?"), 0) + 1
        return {"total": len(entries), "by_status": by_status, "by_kind": by_kind}

    def capture_from_tick(self, tick_result: Dict[str, Any],
                          source: str = "conscious_loop") -> List[Dict[str, Any]]:
        """Fold a conscious-loop tick's REAL insights into the journal.

        Sources flagged needs_attention become unresolved tasks; the summary
        becomes a note when it is not the all-clear."""
        recorded: List[Dict[str, Any]] = []
        for insight in (tick_result or {}).get("insights") or []:
            detail = ""
            src = "unknown"
            if isinstance(insight, dict):
                detail = str(insight.get("detail") or insight.get("source") or "").strip()
                src = str(insight.get("source") or src)
            else:
                detail = str(insight).strip()
            if not detail:
                continue
            entry = self.add("unresolved_task",
                             f"{src}: {detail}" if src != "unknown" else detail,
                             source=source, meta={"insight_source": src})
            if entry:
                recorded.append(entry)

        summary = str((tick_result or {}).get("summary") or "").strip()
        if summary and summary.lower() != "all clear":
            entry = self.add("note", summary, source=source)
            if entry:
                recorded.append(entry)
        return recorded


def get_thought_stream(user_id: str = "default") -> ThoughtStream:
    key = _slug(user_id)
    with _LOCK:
        inst = _instances.get(key)
        if inst is None:
            inst = ThoughtStream(user_id)
            _instances[key] = inst
        return inst
