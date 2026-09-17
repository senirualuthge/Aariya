"""
CVE Agent — queries OSV.dev for known vulnerabilities in project dependencies.
Safe, read-only. Caches results per session to avoid hammering the API.
Uses stdlib urllib so no extra dependency is required.

BUG FIX: OSV's query API only filters advisories by the installed VERSION.
Previously the agent posted a package query with no version, so OSV returned
EVERY advisory ever published for a package — e.g. GHSA-8h2j-cgx8-6xv7
(FastAPI CSRF, fixed in 0.65.2) was reported on FastAPI 0.141.1 forever.
The installed version is now resolved (importlib.metadata) and included in
the query, so only genuinely-affecting advisories are reported.
"""
import asyncio
import importlib.metadata
import json
import logging
import urllib.request
from typing import Dict, Any, List

from server.systems.security.agents.base import SecurityAgent

logger = logging.getLogger("aariya.security.cve")

# Project dependencies to scan on each run (installed version is resolved at
# query time; callers may override with an explicit "version" key).
WATCHED_PACKAGES = [
    {"name": "fastapi",   "ecosystem": "PyPI"},
    {"name": "uvicorn",   "ecosystem": "PyPI"},
    {"name": "pydantic",  "ecosystem": "PyPI"},
    {"name": "psutil",    "ecosystem": "PyPI"},
    {"name": "aiohttp",   "ecosystem": "PyPI"},
]

OSV_API_URL = "https://api.osv.dev/v1/query"
_CVE_CACHE: Dict[str, List[Dict]] = {}   # simple in-process cache


def _installed_version(name: str) -> str:
    """Resolve the installed version of a distribution; '' when unknown."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _osv_query_payload(name: str, ecosystem: str, version: str) -> Dict[str, Any]:
    """Build the OSV query body for one package.

    The version is REQUIRED for OSV to return only advisories that affect the
    installed version — a versionless query returns every historical advisory
    (the source of the GHSA-8h2j-cgx8-6xv7 false positive on FastAPI 0.141.1).
    NOTE: OSV expects ``version`` as a TOP-LEVEL sibling of ``package`` (the
    package object takes only name+ecosystem) — putting it inside ``package``
    silently disables filtering.
    """
    query: Dict[str, Any] = {
        "package": {"name": name, "ecosystem": ecosystem},
    }
    if version:
        query["version"] = version
    return query


def _issue_severity(vuln: Dict[str, Any]) -> str:
    """Best-effort severity from OSV metadata; conservative HIGH fallback."""
    db_sev = (vuln.get("database_specific") or {}).get("severity")
    if db_sev:
        return str(db_sev).upper()
    return "HIGH"


class CVEAgent(SecurityAgent):
    name = "cve"

    async def run(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []

        # Merge caller-supplied deps with the built-in watchlist
        extra = data.get("dependencies", [])
        packages: List[Dict[str, Any]] = list(WATCHED_PACKAGES)  # type: ignore[assignment]
        for dep in extra:
            if isinstance(dep, dict):
                if not dep.get("name"):
                    continue  # junk entry — never query OSV with an empty name
                packages.append({  # type: ignore[arg-type]
                    "name": dep["name"],
                    "ecosystem": dep.get("ecosystem", "PyPI"),
                    "version": dep.get("version"),
                })
            elif isinstance(dep, str):
                packages.append({"name": dep, "ecosystem": "PyPI"})

        # Run CVE checks concurrently
        tasks = [self._check_package(pkg) for pkg in packages]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, list):
                issues.extend(res)

        return issues

    async def _check_package(self, pkg: Dict[str, str]) -> List[Dict[str, Any]]:
        name = pkg["name"]
        ecosystem = pkg.get("ecosystem", "PyPI")
        # Explicit caller version wins; otherwise resolve what's installed so
        # OSV filters advisories to the version actually in use.
        version = str(pkg.get("version") or "") or _installed_version(name)

        # A versionless OSV query returns EVERY historical advisory for the
        # package (the GHSA-8h2j-cgx8-6xv7 false positive). If the version can't
        # be resolved the package isn't meaningfully part of the runtime, so
        # skip it rather than re-entering that broken mode.
        if not version:
            logger.debug(f"CVEAgent: skipping {name} — no installed version found")
            return []

        cache_key = f"{ecosystem}:{name}:{version}"

        if cache_key in _CVE_CACHE:
            return _CVE_CACHE[cache_key]

        payload = _osv_query_payload(name, ecosystem, version)

        try:
            body = json.dumps(payload).encode("utf-8")
            req  = urllib.request.Request(
                OSV_API_URL,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            loop = asyncio.get_event_loop()
            # Run blocking urllib call off the event loop thread
            def _fetch():
                with urllib.request.urlopen(req, timeout=5) as resp:
                    return json.loads(resp.read())

            resp_data = await asyncio.wait_for(
                loop.run_in_executor(None, _fetch), timeout=6.0
            )
        except Exception as exc:
            logger.debug(f"CVEAgent: OSV query failed for {name}: {exc}")
            return []

        findings: List[Dict[str, Any]] = []
        for vuln in resp_data.get("vulns", []):
            vuln_id = vuln.get("id", "UNKNOWN")
            summary = vuln.get("summary", "No summary available.")
            findings.append(
                self.format_issue(
                    issue=f"{name} {version} has known vulnerability: {vuln_id}",
                    severity=_issue_severity(vuln),
                    fix=f"Update {name} to a patched version. See https://osv.dev/vulnerability/{vuln_id}",
                    reason=summary,
                )
            )

        _CVE_CACHE[cache_key] = findings
        return findings
