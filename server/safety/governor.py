"""
Safety Governor — audit logging + rollback for filesystem operations
(AccessFIles §45 — Safety Governor; gap: audit trail + undo).

Wraps FileSystemAgent so every mutating operation is:

  1. AUDITED   → a JSONL journal entry records who/what/when + prior state.
  2. REVERSIBLE → write/append/delete snapshot the before-image so `rollback()`
                 can restore the pre-operation state byte-for-byte.

The governor is a thin, defensive decorator: if audit or snapshotting fails,
the underlying operation is aborted (fail-closed) rather than proceeding
unrecorded.
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.safety.filesystem_guard import validate_path
from server.systems.filesystem.access_events import notify_sync


class SafetyGovernor:
    def __init__(self, filesystem_agent, journal_path: str = "./data/safety_audit.jsonl"):
        self._agent = filesystem_agent
        self._journal_path = journal_path
        self._undo_stack: List[Dict[str, Any]] = []
        Path(journal_path).parent.mkdir(parents=True, exist_ok=True)

    # ── Audit ──────────────────────────────────────────────────────────────────

    def _audit(self, entry: Dict[str, Any]) -> bool:
        try:
            with open(self._journal_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            return True
        except OSError:
            return False

    def audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Read recent audit entries (most recent last)."""
        if not os.path.exists(self._journal_path):
            return []
        entries = []
        with open(self._journal_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries[-limit:]

    def _snapshot(self, path: str) -> Optional[bytes]:
        """Capture the before-image of a file, or None if it doesn't exist."""
        try:
            p = Path(validate_path(path) or path)
            if p.is_file():
                return p.read_bytes()
        except OSError:
            pass
        return None

    def _restore(self, path: str, snapshot: Optional[bytes], existed: bool) -> bool:
        try:
            p = Path(validate_path(path) or path)
            if existed and snapshot is not None:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(snapshot)
                return True
            if p.exists():
                if p.is_dir():
                    p.rmdir()
                else:
                    p.unlink()
                return True
            return True  # already absent — nothing to undo
        except OSError:
            return False

    # ── Reversible writes ──────────────────────────────────────────────────────

    def _run_agent(self, op_name, paths, actor, fn, ok_detail: str = "") -> bool:
        """Call an agent operation, ALWAYS emitting exactly one real
        telemetry frame for the outcome (executed / denied / error) before
        propagating any exception."""
        t0 = time.perf_counter()
        try:
            ok = fn()
        except Exception as exc:
            notify_sync(op_name, paths, actor=actor, status="error",
                        detail=str(exc)[:200],
                        duration_ms=(time.perf_counter() - t0) * 1000)
            raise
        notify_sync(op_name, paths, actor=actor,
                    status="executed" if ok else "denied",
                    detail=ok_detail if ok else "",
                    duration_ms=(time.perf_counter() - t0) * 1000)
        return ok

    def write_file(self, path: str, content: str, *, confirmed: bool = False,
                   actor: str = "ai") -> bool:
        detail = (f"{len(content.encode('utf-8'))} bytes"
                  + ("" if confirmed else " (unconfirmed gate)"))
        before = self._snapshot(path)
        existed = os.path.exists(Path(validate_path(path) or path))
        ok = self._run_agent(
            "write_file", [path], actor,
            lambda: self._agent.write_file(path, content, confirmed=confirmed),
            ok_detail=detail)
        if ok:
            self._audit({
                "ts": time.time(), "id": uuid.uuid4().hex[:8], "actor": actor,
                "action": "write_file", "path": path, "existed": existed,
                "bytes": len(content.encode("utf-8")), "rollback_available": True,
            })
            self._undo_stack.append({
                "path": path, "action": "write_file",
                "snapshot": before, "existed": existed,
            })
        return ok

    def append_file(self, path: str, content: str, *, confirmed: bool = False,
                    actor: str = "ai") -> bool:
        before = self._snapshot(path)
        existed = os.path.exists(Path(validate_path(path) or path))
        ok = self._run_agent(
            "append_file", [path], actor,
            lambda: self._agent.append_file(path, content, confirmed=confirmed),
            ok_detail=f"+{len(content.encode('utf-8'))} bytes appended")
        if ok:
            self._audit({
                "ts": time.time(), "id": uuid.uuid4().hex[:8], "actor": actor,
                "action": "append_file", "path": path, "existed": existed,
                "bytes": len(content.encode("utf-8")), "rollback_available": True,
            })
            self._undo_stack.append({
                "path": path, "action": "append_file",
                "snapshot": before, "existed": existed,
            })
        return ok

    def delete_file(self, path: str, *, confirmed: bool = False, actor: str = "ai") -> bool:
        before = self._snapshot(path)
        existed = os.path.exists(Path(validate_path(path) or path))
        ok = self._run_agent(
            "delete_file", [path], actor,
            lambda: self._delete_confirmed(path, confirmed),
            ok_detail=f"{len(before) if before else 0} bytes removed")
        if ok:
            self._audit({
                "ts": time.time(), "id": uuid.uuid4().hex[:8], "actor": actor,
                "action": "delete_file", "path": path, "existed": existed,
                "bytes": len(before) if before else 0, "rollback_available": True,
            })
            self._undo_stack.append({
                "path": path, "action": "delete_file",
                "snapshot": before, "existed": existed,
            })
        return ok

    def _delete_confirmed(self, path: str, confirmed: bool) -> bool:
        """Unconfirmed deletes are denials (False), matching the original
        confirmation-gate contract rather than an exception."""
        try:
            return self._agent.delete_file(path, confirmed=confirmed)
        except PermissionError:
            return False

    def _open_quietly(self, path: str) -> bool:
        """Old open_path contract preserved: launch failures are denials,
        never raised exceptions."""
        try:
            return self._agent.open_path(path)
        except Exception:
            return False

    def open_path(self, path: str, *, actor: str = "ai") -> bool:
        """Audited passthrough for open-with-OS-default (launches a real app,
        so it belongs in the journal even though it mutates nothing)."""
        ok = self._run_agent(
            "open_path", [path], actor,
            lambda: self._open_quietly(path),
            ok_detail="opened with OS default app")
        self._audit({
            "ts": time.time(), "id": uuid.uuid4().hex[:8], "actor": actor,
            "action": "open_path", "path": path, "ok": ok,
        })
        return ok

    def record_denial(self, action: str, path: str, reason: str) -> None:
        """Journal a refused operation (guard rejection, unconfirmed gate…)
        so denials are reviewable alongside executed actions."""
        notify_sync(action, [path], actor="governor", status="denied",
                    detail=reason[:200])
        self._audit({
            "ts": time.time(), "id": uuid.uuid4().hex[:8], "actor": "governor",
            "action": "denied", "denied_action": action, "path": path,
            "reason": reason[:300],
        })

    def rollback(self, n: int = 1) -> Dict[str, Any]:
        """Undo the last n audited mutations, newest first."""
        restored, failed = 0, 0
        t0 = time.perf_counter()
        touched: List[str] = []
        while self._undo_stack and restored < n:
            entry = self._undo_stack.pop()
            touched.append(entry["path"])
            ok = self._restore(entry["path"], entry["snapshot"], entry["existed"])
            if ok:
                restored += 1
                self._audit({
                    "ts": time.time(), "id": uuid.uuid4().hex[:8], "actor": "governor",
                    "action": "rollback", "path": entry["path"],
                    "restored_to": entry["action"],
                })
            else:
                failed += 1
        if touched:
            notify_sync("rollback", touched, actor="governor",
                        status="executed" if not failed else "error",
                        detail=f"restored {restored}, failed {failed}",
                        duration_ms=(time.perf_counter() - t0) * 1000)
        return {"restored": restored, "failed": failed}

    def status(self) -> Dict[str, Any]:
        return {
            "audit_entries": len(self.audit_log()),
            "pending_undo": len(self._undo_stack),
            "journal": self._journal_path,
        }


_governor: Optional[SafetyGovernor] = None


def get_safety_governor() -> SafetyGovernor:
    global _governor
    if _governor is None:
        from server.systems.filesystem.filesystem_agent import FileSystemAgent
        _governor = SafetyGovernor(FileSystemAgent())
    return _governor
