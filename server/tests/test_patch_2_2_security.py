"""Regression suite for Patch 2.2 (strict auth, replay protection, service HMAC).

Every credential, secret and nonce here is generated inside the test session.
The database is the isolated tmp SQLite fixture from ``conftest.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from server import main as server_main
from server.db import get_db_connection
from server.systems.security.device_auth import (
    DeviceAuthError,
    PairingRateLimited,
    authenticate_credential,
    create_pairing_code,
    issue_ws_ticket,
    reserve_pairing_attempt,
    redeem_ws_ticket,
)

OWNER = "u1"


# ── Fixtures / helpers ───────────────────────────────────────────────────────

@pytest.fixture
def strict_auth(isolated_db, monkeypatch):
    monkeypatch.setenv("AARIYA_OWNER_ID", OWNER)
    monkeypatch.setenv("REQUIRE_WS_AUTH", "1")
    monkeypatch.setenv("WS_SECRET_TOKEN", "patch-2-2-test-secret")
    yield isolated_db


@pytest.fixture
def client(strict_auth):
    return TestClient(server_main.app)


def _pair(client, role="dashboard", label="laptop", platform="macos"):
    code = create_pairing_code(role=role)
    response = client.post(
        "/api/auth/device/enroll",
        json={"pairing_code": code, "label": label, "platform": platform},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth(credential):
    return {"Authorization": f"Bearer {credential}"}


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ── 4/5: canonical owner + mode ──────────────────────────────────────────────

def test_auth_mode_reports_legacy_without_owner(isolated_db):
    client = TestClient(server_main.app)
    body = client.get("/api/auth/mode").json()
    assert body == {"mode": "legacy", "device_auth_enabled": False}
    # It must not leak owner, device or pairing information.
    assert set(body) == {"mode", "device_auth_enabled"}


def test_auth_mode_reports_device_with_owner(client):
    body = client.get("/api/auth/mode").json()
    assert body == {"mode": "device", "device_auth_enabled": True}
    assert set(body) == {"mode", "device_auth_enabled"}


def test_pairing_code_owner_override_is_rejected_by_cli():
    from server.tools.create_device_pairing_code import main

    with pytest.raises(SystemExit):
        main(["--role", "mobile", "--owner", "attacker"])


def test_pairing_code_for_different_owner_is_rejected(client):
    code = create_pairing_code(role="mobile")
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE aariya_pairing_codes SET owner_id = ?",
            ("someone-else",),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post(
        "/api/auth/device/enroll",
        json={"pairing_code": code, "label": "phone", "platform": "android"},
    )
    assert response.status_code == 400

    conn = get_db_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM aariya_personal_devices"
        ).fetchone()["n"]
    finally:
        conn.close()
    assert count == 0


def test_device_belonging_to_another_owner_is_rejected(client):
    credential = "aariya-device." + secrets.token_urlsafe(32)
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO aariya_personal_devices "
            "(device_id, owner_id, device_role, label, platform, credential_hash, "
            " created_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("other-device", "someone-else", "dashboard", "theirs", "linux",
             _sha256(credential), 0.0, 0.0),
        )
        conn.commit()
    finally:
        conn.close()

    assert client.get("/api/auth/me", headers=_auth(credential)).status_code == 401


def test_ws_ticket_endpoint_requires_a_credential(client):
    assert client.post(
        "/api/auth/ws-ticket", json={"path": "/ws/synoptics"}
    ).status_code == 401


# ── 3: SDK audit authorization + bound device id ────────────────────────────

def test_sdk_audit_rejects_missing_credential(client):
    assert client.get("/api/sdk/audit/events").status_code == 401
    assert client.get("/api/sdk/audit/replay").status_code == 401
    assert client.get("/api/sdk/audit/stats").status_code == 401
    assert client.get("/api/sdk/killswitches/state").status_code == 401
    assert client.get("/api/sdk/killswitches/audit").status_code == 401


def test_sdk_audit_rejects_mobile_device(client):
    phone = _pair(client, role="mobile", label="phone", platform="android")
    headers = _auth(phone["credential"])
    assert client.get("/api/sdk/audit/events", headers=headers).status_code == 403
    assert client.get("/api/sdk/killswitches/state", headers=headers).status_code == 403


def test_sdk_audit_allows_dashboard(client):
    laptop = _pair(client)
    headers = _auth(laptop["credential"])
    for path in (
        "/api/sdk/audit/events",
        "/api/sdk/audit/replay",
        "/api/sdk/audit/stats",
        "/api/sdk/killswitches/state",
        "/api/sdk/killswitches/audit",
    ):
        assert client.get(path, headers=headers).status_code == 200, path


def test_sdk_init_ignores_client_supplied_device_id(client):
    laptop = _pair(client)
    headers = _auth(laptop["credential"])
    response = client.post(
        "/api/sdk/init",
        json={"device_id": "attacker-controlled", "capabilities": {"voice": True}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    session_id = response.json()["session_id"]

    events = client.get(
        "/api/sdk/audit/events?event_type=session.start",
        headers=headers,
    ).json()["events"]
    matching = [e for e in events if e.get("session_id") == session_id]
    assert matching
    assert matching[-1]["user_id"] == laptop["device_id"]


def test_sdk_snapshot_requires_dashboard_authority(client):
    phone = _pair(client, role="mobile", label="phone", platform="android")
    assert client.get(
        "/api/sdk/snapshot", headers=_auth(phone["credential"])
    ).status_code == 403

    laptop = _pair(client)
    assert client.get(
        "/api/sdk/snapshot", headers=_auth(laptop["credential"])
    ).status_code == 200


# ── 6: atomic pairing reservation ───────────────────────────────────────────

def test_six_simultaneous_attempts_from_one_source_reserve_at_most_five(
    isolated_db, monkeypatch
):
    monkeypatch.setenv("AARIYA_PAIRING_RATE_KEY", "x" * 40)
    source = "192.0.2.10"

    def attempt(_):
        try:
            reserve_pairing_attempt(source)
            return True
        except PairingRateLimited:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))

    assert results.count(True) == 5
    assert results.count(False) == 1


def test_global_concurrent_reservations_stop_at_twenty(isolated_db, monkeypatch):
    monkeypatch.setenv("AARIYA_PAIRING_RATE_KEY", "y" * 40)

    def attempt(index):
        try:
            reserve_pairing_attempt(f"198.51.100.{index}")
            return True
        except PairingRateLimited:
            return False

    with ThreadPoolExecutor(max_workers=30) as pool:
        results = list(pool.map(attempt, range(30)))

    assert results.count(True) == 20
    assert results.count(False) == 10


# ── 8/9: signal trust boundaries + service HMAC replay protection ───────────

def _service_env(monkeypatch, service_id="pulse-news", secret=None):
    secret = secret or secrets.token_urlsafe(32)
    monkeypatch.setenv(
        "AARIYA_SERVICE_AUTH_KEYS",
        json.dumps({service_id: secret}),
    )
    return service_id, secret


def _sign(service_id, secret, body, *, nonce=None, timestamp=None):
    path = "/api/signals/ingest"
    ts = str(int(time.time() if timestamp is None else timestamp))
    nonce = nonce or secrets.token_urlsafe(24)
    signature = hmac.new(
        secret.encode("utf-8"),
        "\n".join(
            [
                "POST",
                path,
                ts,
                nonce,
                hashlib.sha256(body).hexdigest(),
            ]
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "content-type": "application/json",
        "x-aariya-service": service_id,
        "x-aariya-timestamp": ts,
        "x-aariya-nonce": nonce,
        "x-aariya-signature": signature,
    }


def _signal_body():
    return json.dumps(
        {"type": "system", "payload": {"title": "signed"}},
        separators=(",", ":"),
    ).encode("utf-8")


def test_internal_signal_submission_requires_a_credential(client):
    response = client.post(
        "/ingest/signal",
        json={"id": "s1", "type": "system", "payload": {}},
    )
    assert response.status_code == 401


def test_external_signal_without_hmac_is_rejected(isolated_db):
    client = TestClient(server_main.app)
    response = client.post(
        "/api/signals/ingest",
        content=_signal_body(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 401


def test_external_signal_with_altered_body_is_rejected(isolated_db, monkeypatch):
    service_id, secret = _service_env(monkeypatch)
    client = TestClient(server_main.app)
    signed_body = _signal_body()
    headers = _sign(service_id, secret, signed_body)

    tampered = json.dumps(
        {"type": "system", "payload": {"title": "tampered"}},
        separators=(",", ":"),
    ).encode("utf-8")

    response = client.post(
        "/api/signals/ingest",
        content=tampered,
        headers=headers,
    )
    assert response.status_code == 401


def test_external_signal_replay_with_same_nonce_is_rejected(isolated_db, monkeypatch):
    service_id, secret = _service_env(monkeypatch)
    client = TestClient(server_main.app)
    body = _signal_body()
    headers = _sign(service_id, secret, body, nonce="nonce-" + secrets.token_urlsafe(16))

    first = client.post("/api/signals/ingest", content=body, headers=headers)
    assert first.status_code == 200, first.text

    replay = client.post("/api/signals/ingest", content=body, headers=headers)
    assert replay.status_code == 401


def test_valid_signed_external_signal_is_accepted_once(isolated_db, monkeypatch):
    service_id, secret = _service_env(monkeypatch)
    client = TestClient(server_main.app)
    body = _signal_body()
    headers = _sign(service_id, secret, body)

    response = client.post("/api/signals/ingest", content=body, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True


# ── Patch 3: every personal REST surface resolves identity ───────────────────

PERSONAL_SURFACES = [
    "/api/prediction/status",
    "/api/self-knowledge",
    "/api/obsidian/runtime/latest",
    "/api/obsidian/search?q=anything",
    "/api/rl/status",
    "/api/web-search?q=anything",
]


@pytest.mark.parametrize("path", PERSONAL_SURFACES)
def test_personal_surfaces_require_a_credential_in_strict_mode(client, path):
    response = client.get(path)
    assert response.status_code in (401, 403), f"{path} leaked: {response.status_code}"


@pytest.mark.parametrize("path", PERSONAL_SURFACES)
def test_personal_surfaces_reject_forged_user_id(client, path):
    separator = "&" if "?" in path else "?"
    response = client.get(f"{path}{separator}user_id=someone-else")
    assert response.status_code in (401, 403)


def test_dashboard_only_surfaces_reject_a_mobile_device(client):
    mobile = _pair(client, role="mobile", label="phone", platform="ios")
    response = client.get("/api/meeting/status", headers=_auth(mobile["credential"]))
    assert response.status_code == 403

    response = client.post(
        "/api/self-knowledge/refresh",
        headers=_auth(mobile["credential"]),
    )
    assert response.status_code == 403


def test_dashboard_device_may_read_personal_surfaces(client):
    dashboard = _pair(client)
    headers = _auth(dashboard["credential"])
    for path in ("/api/meeting/status", "/api/rl/status", "/api/self-knowledge"):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, f"{path}: {response.status_code}"


def test_every_private_websocket_route_has_an_explicit_role_policy():
    from starlette.routing import WebSocketRoute

    from server.systems.security.device_auth import roles_for_path

    unmapped = []
    for route in server_main.app.routes:
        if not isinstance(route, WebSocketRoute):
            continue
        path = route.path
        if not roles_for_path(path):
            unmapped.append(path)
    assert unmapped == [], f"WebSocket paths with no device-role policy: {unmapped}"


# ── Patch 3: device identity, revocation and ticket-binding regressions ──────

def test_revoked_device_credential_is_rejected(client):
    device = _pair(client)
    revoke = client.delete(
        f"/api/auth/devices/{device['device_id']}",
        headers=_auth(device["credential"]),
    )
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True

    rejected = client.get("/api/auth/me", headers=_auth(device["credential"]))
    assert rejected.status_code == 401


def test_websocket_ticket_cannot_be_used_on_another_path(client):
    device = _pair(client)
    principal = authenticate_credential(device["credential"])
    ticket = issue_ws_ticket(principal, "/ws/synoptics")

    with pytest.raises(DeviceAuthError):
        redeem_ws_ticket(ticket, "/ws/brain")


def test_websocket_ticket_can_only_be_redeemed_once(client):
    device = _pair(client)
    principal = authenticate_credential(device["credential"])
    ticket = issue_ws_ticket(principal, "/ws/synoptics")

    redeemed = redeem_ws_ticket(ticket, "/ws/synoptics")
    assert redeemed.device_id == device["device_id"]

    with pytest.raises(DeviceAuthError):
        redeem_ws_ticket(ticket, "/ws/synoptics")


def test_mobile_device_cannot_request_dashboard_websocket_ticket(client):
    phone = _pair(client, role="mobile", label="phone", platform="android")
    response = client.post(
        "/api/auth/ws-ticket",
        json={"path": "/ws/synoptics"},
        headers=_auth(phone["credential"]),
    )
    assert response.status_code == 403


def test_dashboard_device_cannot_request_mobile_websocket_ticket(client):
    laptop = _pair(client, role="dashboard", label="laptop", platform="macos")
    response = client.post(
        "/api/auth/ws-ticket",
        json={"path": "/ws/mobile"},
        headers=_auth(laptop["credential"]),
    )
    assert response.status_code == 403


def test_revoked_device_cannot_create_new_websocket_ticket(client):
    device = _pair(client)
    revoke = client.delete(
        f"/api/auth/devices/{device['device_id']}",
        headers=_auth(device["credential"]),
    )
    assert revoke.status_code == 200

    response = client.post(
        "/api/auth/ws-ticket",
        json={"path": "/ws/synoptics"},
        headers=_auth(device["credential"]),
    )
    assert response.status_code == 401
