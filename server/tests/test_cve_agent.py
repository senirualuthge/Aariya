"""Tests for the CVE agent's version-aware OSV query (server/systems/security/agents/cve_agent.py).

Regression guard for the false-positive bug: the agent used to query OSV with
no version, so OSV returned EVERY historical advisory for a package — e.g.
GHSA-8h2j-cgx8-6xv7 (FastAPI CSRF, fixed in 0.65.2) was flagged on FastAPI
0.141.1 forever. The installed version is now resolved and included in the
query. All HTTP is mocked — nothing leaves the machine.
"""

import asyncio
import json

import pytest

from server.systems.security.agents import cve_agent as mod
from server.systems.security.agents.cve_agent import (
    CVEAgent,
    _installed_version,
    _issue_severity,
    _osv_query_payload,
)


@pytest.fixture(autouse=True)
def _clear_cve_cache():
    mod._CVE_CACHE.clear()
    yield
    mod._CVE_CACHE.clear()


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._data


def test_query_payload_includes_version_when_known():
    # OSV requires `version` at the TOP LEVEL (sibling of `package`) — nesting
    # it inside the package object silently disables filtering (live-verified:
    # top-level "0.141.1" → 0 advisories; nested → all 3 historical ones).
    assert _osv_query_payload("fastapi", "PyPI", "0.141.1") == {
        "package": {"name": "fastapi", "ecosystem": "PyPI"},
        "version": "0.141.1",
    }
    # No version → no version key (caller still gets a valid, explicit query).
    assert _osv_query_payload("fastapi", "PyPI", "") == {
        "package": {"name": "fastapi", "ecosystem": "PyPI"}
    }


def test_installed_version_resolves_for_watched_packages():
    assert _installed_version("fastapi")  # the venv actually has it installed


def test_fastapi_query_carries_installed_version(monkeypatch):
    """The HTTP request to OSV must include the installed version."""
    captured = []

    def fake_urlopen(req, timeout=5):
        captured.append(json.loads(req.data))
        return _FakeResp(b'{"vulns": []}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    issues = asyncio.run(CVEAgent().run({"dependencies": []}))
    assert issues == []  # clean venv versions → no advisories

    fastapi_q = next(q for q in captured if q["package"]["name"] == "fastapi")
    # version must be a top-level OSV query field (sibling of `package`).
    assert fastapi_q["version"] == _installed_version("fastapi")


def test_issue_uses_real_severity_not_hardcoded(monkeypatch):
    """A genuine advisory surfaces with OSV's severity, and its id is reported.

    Only the fastapi request gets the canned advisory — every other package
    gets an empty response, so the test also exercises the clean path.
    """
    canned = [{
        "id": "GHSA-8h2j-cgx8-6xv7",
        "summary": "CSRF in FastAPI (only relevant for versions < 0.65.2).",
        "database_specific": {"severity": "MODERATE"},
    }]

    def fake_urlopen(req, timeout=5):
        pkg_name = json.loads(req.data)["package"]["name"]
        vulns = canned if pkg_name == "fastapi" else []
        return _FakeResp(json.dumps({"vulns": vulns}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    issues = asyncio.run(CVEAgent().run({"dependencies": []}))
    fastapi_issues = [i for i in issues if "fastapi" in i["issue"]]
    assert len(fastapi_issues) == 1  # only fastapi had a canned advisory
    assert "GHSA-8h2j-cgx8-6xv7" in fastapi_issues[0]["issue"]
    assert fastapi_issues[0]["severity"] == "MODERATE"
    assert "osv.dev/vulnerability/GHSA-8h2j-cgx8-6xv7" in fastapi_issues[0]["fix"]
    assert "GHSA-8h2j-cgx8-6xv7" not in [i["issue"] for i in issues if "fastapi" not in i["issue"]]


def test_unresolvable_version_is_skipped_not_flooded(monkeypatch):
    """A package whose version can't be resolved is SKIPPED — never queried
    versionless (which would return every historical advisory)."""
    called = []

    def fake_urlopen(req, timeout=5):
        called.append(json.loads(req.data))
        return _FakeResp(b'{"vulns": []}')

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(mod, "_installed_version", lambda name: "")

    issues = asyncio.run(CVEAgent().run({"dependencies": []}))
    assert issues == []
    assert called == []  # no versionless queries were ever sent


def test_severity_falls_back_to_high():
    assert _issue_severity({"database_specific": {"severity": "low"}}) == "LOW"
    assert _issue_severity({"database_specific": {"severity": "critical"}}) == "CRITICAL"
    assert _issue_severity({}) == "HIGH"
