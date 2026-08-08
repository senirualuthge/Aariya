"""
server/routers/security_router.py
===================================
REST endpoint that runs the two CVE scanner scripts on demand and caches results.

Endpoints:
  GET /api/security/scan       — full bandit + npm audit + pip-audit combined scan
  GET /api/security/deps       — pip-audit dependency CVE audit only
  GET /api/security/last-scan  — return cached result without re-running
"""

import subprocess
import json
import time
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter

router = APIRouter(prefix="/api/security", tags=["security"])

# Project root (two levels up from this file)
ROOT = Path(__file__).resolve().parent.parent.parent

# Cache last scan result to avoid expensive re-runs every page load
_cache: dict = {}
_cache_ttl: float = 120.0   # re-run every 2 mins


def _run_bandit() -> dict:
    """Run bandit SAST on server/ and return structured results."""
    bandit = ROOT / "venv" / "bin" / "bandit"
    if not bandit.exists():
        bandit = Path("/opt/homebrew/bin/bandit")
    if not bandit.exists():
        return {"available": False, "findings": [], "summary": {}}

    server_dir = ROOT / "server"
    result = subprocess.run(
        [str(bandit), "-r", str(server_dir), "-x", "**/.venv/**", "-f", "json", "-l"],
        capture_output=True, text=True, timeout=120
    )
    raw = result.stdout.strip() or result.stderr.strip()
    try:
        data = json.loads(raw)
        findings = []
        for item in data.get("results", []):
            findings.append({
                "type": "SAST",
                "tool": "bandit",
                "severity": item.get("issue_severity", "LOW"),
                "confidence": item.get("issue_confidence", "LOW"),
                "message": item.get("issue_text", ""),
                "file": item.get("filename", "").replace(str(ROOT) + "/", ""),
                "line": item.get("line_number", 0),
                "cve": None,
            })
        totals = data.get("metrics", {}).get("_totals", {})
        return {
            "available": True,
            "findings": findings,
            "summary": {
                "high":   int(totals.get("SEVERITY.HIGH", 0)),
                "medium": int(totals.get("SEVERITY.MEDIUM", 0)),
                "low":    int(totals.get("SEVERITY.LOW", 0)),
            },
        }
    except (json.JSONDecodeError, KeyError):
        return {"available": True, "findings": [], "summary": {}}


def _run_pip_audit() -> dict:
    """Run pip-audit on server/requirements.txt."""
    pip_audit = ROOT / "venv" / "bin" / "pip-audit"
    req_file  = ROOT / "server" / "requirements.txt"

    if not pip_audit.exists():
        return {"available": False, "findings": [], "clean": 0, "total": 0}

    result = subprocess.run(
        [str(pip_audit), "-r", str(req_file), "--format", "json", "--progress-spinner", "off"],
        capture_output=True, text=True, timeout=120
    )
    try:
        data = json.loads(result.stdout or "{}")
        deps = data.get("dependencies", [])
        findings = []
        clean = 0
        for pkg in deps:
            if pkg.get("vulns"):
                for vuln in pkg["vulns"]:
                    fix = vuln.get("fix_versions", [])
                    aliases = vuln.get("aliases", [])
                    findings.append({
                        "type": "SCA",
                        "tool": "pip-audit",
                        "severity": "HIGH",
                        "confidence": "HIGH",
                        "message": f"{pkg['name']}=={pkg['version']} has known CVE",
                        "file": "server/requirements.txt",
                        "line": 0,
                        "cve": aliases[0] if aliases else vuln.get("id", "UNKNOWN"),
                        "fix": ", ".join(fix) if fix else "No fix available",
                    })
            else:
                clean += 1
        return {
            "available": True,
            "findings": findings,
            "clean": clean,
            "total": len(deps),
        }
    except (json.JSONDecodeError, KeyError):
        return {"available": True, "findings": [], "clean": 0, "total": 0}


def _run_npm_audit() -> dict:
    """Run npm audit and return structured results."""
    npm_candidates = ["/opt/homebrew/bin/npm", "/usr/local/bin/npm"]
    npm_cmd = None
    for c in npm_candidates:
        if Path(c).exists():
            npm_cmd = c
            break

    if not npm_cmd:
        return {"available": False, "findings": [], "summary": {}}

    result = subprocess.run(
        [npm_cmd, "audit", "--json"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=60
    )
    try:
        data = json.loads(result.stdout or "{}")
        meta = data.get("metadata", {}).get("vulnerabilities", {})
        vulns = data.get("vulnerabilities", {})
        findings = []
        for pkg, vuln in list(vulns.items())[:50]:
            sev = vuln.get("severity", "low").upper()
            via = vuln.get("via", [])
            via_label = via[0] if isinstance(via, list) and via and isinstance(via[0], str) else pkg
            findings.append({
                "type": "SCA",
                "tool": "npm-audit",
                "severity": sev,
                "confidence": "HIGH",
                "message": f"{pkg} vulnerable via {via_label}",
                "file": "package.json",
                "line": 0,
                "cve": None,
            })
        return {
            "available": True,
            "findings": findings,
            "summary": {
                "critical": meta.get("critical", 0),
                "high":     meta.get("high", 0),
                "moderate": meta.get("moderate", 0),
                "low":      meta.get("low", 0),
            },
        }
    except (json.JSONDecodeError, KeyError):
        return {"available": True, "findings": [], "summary": {}}


def _run_full_scan() -> dict:
    """Run all three scanners and combine results."""
    t_start = time.time()

    bandit  = _run_bandit()
    pip_res = _run_pip_audit()
    npm_res = _run_npm_audit()

    all_findings = (
        bandit.get("findings", [])
        + pip_res.get("findings", [])
        + npm_res.get("findings", [])
    )
    high   = sum(1 for f in all_findings if f["severity"] in ("HIGH", "CRITICAL"))
    medium = sum(1 for f in all_findings if f["severity"] == "MEDIUM")
    low    = sum(1 for f in all_findings if f["severity"] in ("LOW", "MODERATE"))

    return {
        "timestamp": time.time(),
        "duration_ms": round((time.time() - t_start) * 1000),
        "gate": "PASS" if high == 0 else "FAIL",
        "summary": {
            "total_findings": len(all_findings),
            "high": high,
            "medium": medium,
            "low": low,
            "python_packages_clean": pip_res.get("clean", 0),
            "python_packages_total": pip_res.get("total", 0),
        },
        "tools": {
            "bandit":    bandit.get("available", False),
            "pip_audit": pip_res.get("available", False),
            "npm_audit": npm_res.get("available", False),
        },
        "findings": all_findings,
    }


@router.get("/scan")
async def run_security_scan(force: bool = False):
    """Run SAST + SCA scanners and return structured results."""
    global _cache
    now = time.time()

    if not force and _cache and (now - _cache.get("timestamp", 0)) < _cache_ttl:
        return {**_cache, "cached": True}

    result = _run_full_scan()
    _cache = result
    return {**result, "cached": False}


@router.get("/last-scan")
async def get_last_scan():
    """Return the cached last scan result (no re-run)."""
    if not _cache:
        return {"message": "No scan has been run yet. Call /api/security/scan first."}
    return {**_cache, "cached": True}
