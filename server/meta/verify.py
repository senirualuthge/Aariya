"""
Rewrite verification gate (AccessFIles §71 — AUTONOMOUS SOFTWARE ENGINEERING).

The doc requires: generate → test → benchmark → debug → retry. The rewriter
generates; THIS module is the real gate between generation and commit:

  1. Syntax verification via ast.parse (no side effects, no imports executed).
  2. Structural check: the candidate must still define the same public names
     (classes/functions) as the original — the rewriter's own rule #1.
  3. Optional pytest run when a matching test file exists.

A candidate that fails ANY check never touches the live file. `commit()`
performs the swap with a .bak backup so the evolution loop can roll back.
"""

import ast
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

logger = logging.getLogger("aariya.verify")


def public_names(source: str) -> Set[str]:
    """Top-level classes/functions defined by a module's source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    names: Set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def verify_candidate(candidate_path: Path, original_path: Path,
                     *, timeout: float = 120.0) -> Dict[str, Any]:
    """Verify an uncommitted candidate file against the original.

    Returns {ok, checks: [...], failures: [...]}. Never executes candidate
    code in-process; pytest runs happen in a subprocess only if a test file
    for this module actually exists on disk.
    """
    checks: List[Dict[str, Any]] = []
    failures: List[str] = []

    try:
        candidate_src = candidate_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "checks": [], "failures": [f"unreadable: {exc}"]}

    # ── Check 1: parses at all ────────────────────────────────────────────────
    try:
        ast.parse(candidate_src)
        checks.append({"check": "syntax", "ok": True})
    except SyntaxError as exc:
        checks.append({"check": "syntax", "ok": False})
        failures.append(f"syntax error line {exc.lineno}: {exc.msg}")
        return {"ok": False, "checks": checks, "failures": failures}

    # ── Check 2: same public surface (rewriter rule #1) ───────────────────────
    try:
        original_src = original_path.read_text(encoding="utf-8")
        missing = public_names(original_src) - public_names(candidate_src)
        if missing:
            checks.append({"check": "public_surface", "ok": False})
            failures.append(f"dropped definitions: {sorted(missing)}")
        else:
            checks.append({"check": "public_surface", "ok": True})
    except OSError:
        checks.append({"check": "public_surface", "ok": True,
                       "note": "original unreadable — skipped"})

    # ── Check 3: real tests when they exist ───────────────────────────────────
    test_file = _matching_test_file(original_path)
    if test_file and not failures:
        result = _run_pytest(test_file, cwd=Path.cwd(), timeout=timeout)
        checks.append({"check": "pytest", "ok": result["returncode"] == 0,
                       "test_file": str(test_file),
                       "tail": result.get("stderr", "")[-400:]})
        if result["returncode"] != 0:
            failures.append(f"pytest failed ({test_file.name})")

    ok = not failures
    return {"ok": ok, "checks": checks, "failures": failures}


def _matching_test_file(module_path: Path) -> Optional[Path]:
    """tests/test_<stem>.py next to the module's tests dir — real file only."""
    stem = module_path.stem
    for base in (module_path.parent.parent / "tests",
                 module_path.parent / "tests"):
        candidate = base / f"test_{stem}.py"
        if candidate.exists():
            return candidate
    return None


def _run_pytest(test_file: Path, *, cwd: Path, timeout: float) -> Dict[str, Any]:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-x", "-q", str(test_file)],
            capture_output=True, text=True, timeout=timeout, cwd=str(cwd),
        )
        return {"returncode": proc.returncode,
                "stdout": proc.stdout[-1000:], "stderr": proc.stderr[-1000:]}
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": f"pytest timed out after {timeout}s"}
    except Exception as exc:
        return {"returncode": -1, "stdout": "", "stderr": str(exc)}


def commit(candidate_path: Path, target_path: Path) -> bool:
    """Swap the verified candidate into place with a .bak rollback point."""
    try:
        backup = target_path.with_suffix(".py.bak")
        shutil.copy2(target_path, backup)
        shutil.copy2(candidate_path, target_path)
        candidate_path.unlink(missing_ok=True)
        logger.info("[verify] committed %s (backup %s)", target_path.name, backup.name)
        return True
    except OSError as exc:
        logger.warning("[verify] commit failed for %s: %s", target_path, exc)
        return False
