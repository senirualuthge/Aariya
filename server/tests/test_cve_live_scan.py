"""Live dependency-scan test for the CVE agent — hits the real OSV.dev API.

Gated behind RUN_LIVE_TESTS=1 exactly like test_agent_v2.py, so the default
`./run_backend_tests.sh` stays hermetic while CI can opt in with:
    RUN_LIVE_TESTS=1 ./run_backend_tests.sh test_cve_live_scan.py

This is the regression guard for the version-aware OSV query fix: fastapi is
installed and patched (0.141.1, the GHSA-8h2j-cgx8-6xv7 CSRF advisory only
affects < 0.65.2), so it MUST report zero advisories. If the version
filtering ever regresses, fastapi floods with historical advisories and this
test fails. Remaining genuine findings (e.g. chromadb's unfixed
PYSEC-2026-311) are surfaced in the log — the hard gate for NEW
vulnerabilities is pip-audit in scripts/scan_deps.sh.
"""

import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_TESTS") != "1",
    reason="requires the OSV API — set RUN_LIVE_TESTS=1 to run",
)

from server.systems.security.agents.cve_agent import CVEAgent  # noqa: E402


def test_cve_agent_live_scan_has_no_fastapi_false_positives():
    issues = asyncio.run(CVEAgent().run({"dependencies": []}))

    # Surface the current dependency posture in the CI log.
    print(f"[depscan] {len(issues)} total findings from watched packages")
    for issue in sorted(issues, key=lambda i: i["severity"]):
        print(f"[depscan] {issue['issue']} | {issue['severity']}")

    fastapi_issues = [i for i in issues if "fastapi" in i["issue"]]
    assert fastapi_issues == [], (
        "fastapi must report ZERO advisories — the version-aware OSV query "
        f"regressed? got: {fastapi_issues}"
    )
