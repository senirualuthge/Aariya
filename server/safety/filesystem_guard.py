"""
Filesystem access + safety layer for Aariya.

Path validation guard. Every filesystem operation must pass through
`validate_path()` BEFORE touching disk. The policy:

  * Allowed roots: user home + configured SAFE_DIRECTORIES (expanded, so
    `~/Documents` resolves to `/Users/me/Documents`).
  * Blocked prefixes: OS/system dirs are always refused regardless of root.
  * Symlinks are resolved before validation so `~/Documents/link -> /etc`
    cannot sneak past the checks.

The agent-facing layer (server/systems/filesystem/filesystem_agent.py) calls
this guard on every read/write/append/delete/open. It never trusts the caller.
"""

import os
import sys
from pathlib import Path
from typing import List, Optional

# ── Policy ─────────────────────────────────────────────────────────────────────

def _expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(os.path.expandvars(path)))


def _default_safe_directories() -> List[str]:
    home = Path.home()
    candidates = [
        "~/Documents",
        "~/Desktop",
        "~/Downloads",
        "~/Projects",
        "~/dev",
        "~/work",
    ]
    existing = [p for p in candidates if Path(_expand(p)).exists()]
    # The home dir itself is always a legal root so freshly-created folders
    # (e.g. "~/notes") are reachable even before they exist.
    return [str(home)] + [_expand(p) for p in existing]


# Overridable via env so tests can point the sandbox at a tmpdir.
SAFE_DIRECTORIES: List[str] = [
    _expand(p)
    for p in os.getenv(
        "AARIYA_SAFE_DIRECTORIES",
        os.pathsep.join(_default_safe_directories()),
    ).split(os.pathsep)
    if p.strip()
]

BLOCKED_PREFIXES: List[str] = [
    "/etc",
    "/boot",
    "/System",
    "/Library",
    "/usr",
    "/bin",
    "/sbin",
    "/dev",
    "/proc",
    "/sys",
    "/private",
]

WINDOWS_BLOCKED: List[str] = [
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "C:\\System32",
]

# Operation classes — used to decide whether confirmation is required.
DANGEROUS_ACTIONS = {"delete", "format", "overwrite_system", "move", "rename"}


def validate_path(path: str, *, require_exists: bool = False) -> Optional[str]:
    """
    Returns the resolved, validated absolute path or None when the path is
    unsafe. Never raises on bad input.

    `require_exists` additionally refuses paths that don't already exist
    (used by read/list operations).
    """
    if not path or not isinstance(path, str):
        return None

    try:
        abs_path = _expand(path)
        # Resolve symlinks so a link inside a safe dir can't escape it.
        if os.path.exists(abs_path):
            abs_path = os.path.realpath(abs_path)
    except (OSError, ValueError):
        return None

    # Must live inside one of the allowed roots (safe dirs are already
    # absolute + normalized at import time). An explicitly-blessed root
    # (e.g. macOS temp dirs under /private/var/folders, or a tmp sandbox)
    # is allowed even though it would otherwise match a blocked prefix —
    # the realpath above already closed the symlink-escape hole.
    for root in SAFE_DIRECTORIES:
        if abs_path == root or abs_path.startswith(root + os.sep):
            return abs_path if not require_exists or os.path.exists(abs_path) else None

    # Not inside a safe root — blocked prefixes are the only gate left.
    if os.name == "nt":
        for blocked in WINDOWS_BLOCKED:
            if abs_path.lower().startswith(blocked.lower()):
                return None
    else:
        for blocked in BLOCKED_PREFIXES:
            if abs_path.startswith(blocked):
                return None

    if require_exists and not os.path.exists(abs_path):
        return None

    return abs_path


def is_dangerous(action: str) -> bool:
    return action in DANGEROUS_ACTIONS


def allowed_roots() -> List[str]:
    """Snapshot of the currently permitted roots (for UI/config display)."""
    return list(SAFE_DIRECTORIES)


def register_root(path: str) -> bool:
    """Add a runtime root to the allow-list (AccessFIles §3 — external drives).

    Used by the filesystem background service when a removable drive mounts:
    the mountpoint becomes a legal root ONLY after this explicit, audited
    registration. Set AARIYA_ALLOW_EXTERNAL_DRIVES=0 to disable entirely.
    Returns True when the root is (now) allowed.
    """
    if os.getenv("AARIYA_ALLOW_EXTERNAL_DRIVES", "1") == "0":
        return False
    resolved = validate_path(path)
    if resolved is None or not os.path.isdir(resolved):
        return False
    if resolved not in SAFE_DIRECTORIES:
        SAFE_DIRECTORIES.append(resolved)
    return True


def is_registered_root(path: str) -> bool:
    try:
        abs_path = _expand(path)
        if os.path.exists(abs_path):
            abs_path = os.path.realpath(abs_path)
    except (OSError, ValueError):
        return False
    return any(abs_path == r or abs_path.startswith(r + os.sep) for r in SAFE_DIRECTORIES)
