"""
Filesystem Agent — sandboxed local file access for Aariya.

Wraps the safety guard (server/safety/filesystem_guard.py) around every
read/write/append/list/search/open operation. Nothing touches disk without
`validate_path()` first. Destructive operations additionally require the
caller to pass `confirmed=True` (the confirmation gate lives in the caller /
swarm agent — this layer refuses unconfirmed destructive work outright).
"""

import os
import subprocess
import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional

from server.safety.filesystem_guard import (
    validate_path,
    is_dangerous,
    allowed_roots,
)

logger = logging.getLogger("aariya.filesystem_agent")

# Extensions we can index/extract text from.
TEXT_EXTENSIONS = {".txt", ".md", ".py", ".json", ".csv", ".html", ".xml", ".log", ".yaml", ".yml"}
# Binary/rich formats handled by the OCR/indexer pipeline.
RICH_EXTENSIONS = {".pdf", ".docx", ".png", ".jpg", ".jpeg"}


class FileSystemAgent:
    def __init__(self):
        self.roots = allowed_roots()
        logger.info(f"FileSystemAgent roots: {self.roots}")

    # ── Path safety helper ────────────────────────────────────────────────────
    def _resolve(self, path: str, *, require_exists: bool = False) -> str:
        resolved = validate_path(path, require_exists=require_exists)
        if resolved is None:
            raise PermissionError(f"Path not allowed by filesystem guard: {path!r}")
        return resolved

    # ── LIST FILES ────────────────────────────────────────────────────────────
    def list_directory(self, path: str) -> List[Dict]:
        try:
            p = Path(self._resolve(path, require_exists=True))
        except PermissionError:
            return []
        if not p.is_dir():
            return []

        results = []
        for item in sorted(p.iterdir(), key=lambda x: x.name.lower()):
            try:
                results.append({
                    "name": item.name,
                    "path": str(item),
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else 0,
                })
            except OSError:
                continue
        return results

    # ── READ FILE ────────────────────────────────────────────────────────────
    def read_file(self, path: str) -> str:
        try:
            p = Path(self._resolve(path, require_exists=True))
        except PermissionError:
            return "File not accessible."
        if p.is_dir():
            return "Cannot read directory."
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except OSError as e:
            return f"Error reading file: {e}"

    def read_binary(self, path: str) -> Optional[bytes]:
        try:
            p = Path(self._resolve(path, require_exists=True))
        except PermissionError:
            return None
        try:
            return p.read_bytes()
        except OSError:
            return None

    # ── WRITE FILE ────────────────────────────────────────────────────────────
    def write_file(self, path: str, content: str, *, confirmed: bool = False) -> bool:
        try:
            p = Path(self._resolve(path))
        except PermissionError:
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            p.write_text(content, encoding="utf-8")
            logger.info(f"[FS] wrote {p}")
            return True
        except OSError as e:
            logger.warning(f"[FS] write failed {p}: {e}")
            return False

    def append_file(self, path: str, content: str, *, confirmed: bool = False) -> bool:
        try:
            p = Path(self._resolve(path))
        except PermissionError:
            return False
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(content)
            return True
        except OSError as e:
            logger.warning(f"[FS] append failed {p}: {e}")
            return False

    def delete_file(self, path: str, *, confirmed: bool = False) -> bool:
        """Destructive — requires `confirmed=True` (confirmation gate)."""
        if not confirmed:
            raise PermissionError("delete requires user confirmation")
        try:
            p = Path(self._resolve(path, require_exists=True))
        except PermissionError:
            return False
        try:
            if p.is_dir():
                p.rmdir()
            else:
                p.unlink()
            logger.warning(f"[FS] deleted {p}")
            return True
        except OSError as e:
            logger.warning(f"[FS] delete failed {p}: {e}")
            return False

    # ── OPEN FILE / APP ───────────────────────────────────────────────────────
    def open_path(self, path: str) -> bool:
        """Open a file or folder with the OS default application."""
        try:
            p = Path(self._resolve(path, require_exists=True))
        except PermissionError:
            return False
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(p)])
            elif sys.platform == "win32":
                os.startfile(str(p))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(p)])
            return True
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning(f"[FS] open failed {p}: {e}")
            return False

    # ── SEARCH FILES ──────────────────────────────────────────────────────────
    def search_files(self, root: str, query: str, *, max_results: int = 50) -> List[str]:
        """Filename substring search within an allowed root (bounded walk)."""
        try:
            base = Path(self._resolve(root, require_exists=True))
        except PermissionError:
            return []
        if not base.is_dir():
            return []
        matches = []
        q = query.lower()
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fname in filenames:
                if q in fname.lower():
                    matches.append(os.path.join(dirpath, fname))
                    if len(matches) >= max_results:
                        return matches
        return matches

    # ── CAPABILITIES ──────────────────────────────────────────────────────────
    def capabilities(self) -> dict:
        return {
            "list_directory": True,
            "read_file": True,
            "write_file": True,
            "append_file": True,
            "delete_file": True,
            "open_path": True,
            "search_files": True,
            "roots": self.roots,
        }
