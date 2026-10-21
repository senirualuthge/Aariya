"""GET /health — cheap liveness probe.

A monitor was polling the conventional root path and got 404 because the server
only exposed the heavy snapshot at /api/system/health. The probe is now a
first-class route, and it must stay cheap: no psutil walk, no subsystem probes.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from server import main as server_main


def test_health_returns_ok_without_building_the_full_snapshot():
    # No context manager: this route must answer without the app lifespan
    # (i.e. it cannot depend on subsystems having started).
    client = TestClient(server_main.app)

    res = client.get("/health")

    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["service"] == "aariya-brain"
    assert isinstance(body["ts"], (int, float))
    # The full snapshot has these; the probe must not pay for them.
    assert "server" not in body
    assert "checks" not in body


def test_full_snapshot_route_still_exists():
    """The probe is an addition, not a replacement."""
    paths = {route.path for route in server_main.app.routes}
    assert "/health" in paths
    assert "/api/system/health" in paths
