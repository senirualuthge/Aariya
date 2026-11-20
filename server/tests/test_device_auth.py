"""Regression suite for personal device authentication (Patch 2/3).

These tests run with AARIYA_OWNER_ID set, which switches the server from the
legacy shared-token mode to strict device authentication. The database is the
isolated tmp SQLite fixture, so no real credential or device is touched.
"""

import asyncio
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server import main as server_main
from server.db import get_db_connection
from server.systems.security.device_auth import (
    DeviceAuthError,
    create_pairing_code,
    redeem_ws_ticket,
    revoke_device_and_disconnect,
    validate_device_auth_configuration,
)
from server.systems.security.device_connection_registry import device_connections

OWNER = "u1"


@pytest.fixture
def strict_auth(isolated_db, monkeypatch):
    monkeypatch.setenv("AARIYA_OWNER_ID", OWNER)
    monkeypatch.setenv("REQUIRE_WS_AUTH", "1")
    monkeypatch.setenv("WS_SECRET_TOKEN", "device-auth-test-secret")
    yield isolated_db


@pytest.fixture
def client(strict_auth):
    return TestClient(server_main.app)


def _pair(client, role="dashboard", label="laptop", platform="macos"):
    code = create_pairing_code(role=role, owner_id=OWNER)
    response = client.post(
        "/api/auth/device/enroll",
        json={"pairing_code": code, "label": label, "platform": platform},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth(credential):
    return {"Authorization": f"Bearer {credential}"}


def _ticket(client, credential, path):
    response = client.post(
        "/api/auth/ws-ticket", json={"path": path}, headers=_auth(credential)
    )
    assert response.status_code == 200, response.text
    return response.json()["ticket"]


# ── Pairing / enrollment ────────────────────────────────────────────────────

def test_valid_pairing_code_enrolls_device(client):
    enrolled = _pair(client)
    assert enrolled["owner_id"] == OWNER
    assert enrolled["role"] == "dashboard"
    assert enrolled["device_id"]
    assert enrolled["credential"].startswith("aariya-device.")


def test_invalid_pairing_code_is_rejected(client):
    response = client.post(
        "/api/auth/device/enroll",
        json={"pairing_code": "ZZZZ-ZZZZ", "label": "x", "platform": "test"},
    )
    assert response.status_code == 400
    assert "invalid" in response.json()["detail"].lower()


def test_expired_pairing_code_is_rejected(client):
    code = create_pairing_code(role="mobile", owner_id=OWNER)
    conn = get_db_connection()
    try:
        conn.execute(
            "UPDATE aariya_pairing_codes SET expires_at = 0 WHERE code_hash != ''"
        )
        conn.commit()
    finally:
        conn.close()

    response = client.post(
        "/api/auth/device/enroll",
        json={"pairing_code": code, "label": "phone", "platform": "android"},
    )
    assert response.status_code == 400
    assert "expired" in response.json()["detail"].lower()


def test_pairing_code_works_only_once(client):
    code = create_pairing_code(role="mobile", owner_id=OWNER)
    first = client.post(
        "/api/auth/device/enroll",
        json={"pairing_code": code, "label": "phone", "platform": "android"},
    )
    assert first.status_code == 200

    second = client.post(
        "/api/auth/device/enroll",
        json={"pairing_code": code, "label": "phone2", "platform": "android"},
    )
    assert second.status_code == 400
    assert "used" in second.json()["detail"].lower()


def test_credential_is_stored_only_as_a_hash(client):
    enrolled = _pair(client)
    credential = enrolled["credential"]

    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT credential_hash FROM aariya_personal_devices WHERE device_id = ?",
            (enrolled["device_id"],),
        ).fetchone()
        plaintext = conn.execute(
            "SELECT 1 FROM aariya_personal_devices WHERE credential_hash = ?",
            (credential,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["credential_hash"] != credential
    assert len(row["credential_hash"]) == 64
    assert plaintext is None


def test_enrollment_ignores_client_supplied_identity_fields(client):
    """A caller cannot choose owner, device id or role."""
    code = create_pairing_code(role="mobile", owner_id=OWNER)
    response = client.post(
        "/api/auth/device/enroll",
        json={
            "pairing_code": code,
            "label": "phone",
            "platform": "android",
            "owner_id": "attacker",
            "device_id": "chosen-id",
            "role": "dashboard",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["owner_id"] == OWNER
    assert body["role"] == "mobile"
    assert body["device_id"] != "chosen-id"


# ── Credentials + revocation ────────────────────────────────────────────────

def test_me_returns_device_identity(client):
    enrolled = _pair(client)
    response = client.get("/api/auth/me", headers=_auth(enrolled["credential"]))
    assert response.status_code == 200
    assert response.json()["owner_id"] == OWNER
    assert response.json()["device_id"] == enrolled["device_id"]


def test_unknown_credential_is_rejected(client):
    response = client.get("/api/auth/me", headers=_auth("aariya-device.nope"))
    assert response.status_code == 401


def test_revoked_credential_is_rejected_and_tickets_die(client):
    enrolled = _pair(client)
    credential = enrolled["credential"]
    ticket = _ticket(client, credential, "/ws/synoptics")

    revoke = client.delete(
        f"/api/auth/devices/{enrolled['device_id']}", headers=_auth(credential)
    )
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True

    assert client.get("/api/auth/me", headers=_auth(credential)).status_code == 401
    # Revocation deletes the ticket outright, so it can no longer be redeemed
    # (either "invalid" or "revoked" is a correct refusal).
    with pytest.raises(DeviceAuthError, match="invalid websocket ticket|revoked"):
        redeem_ws_ticket(ticket, "/ws/synoptics")


def test_revoking_one_device_does_not_revoke_the_other(client):
    laptop = _pair(client, label="laptop")
    phone = _pair(client, role="mobile", label="phone", platform="android")

    revoke = client.delete(
        f"/api/auth/devices/{laptop['device_id']}", headers=_auth(laptop["credential"])
    )
    assert revoke.status_code == 200

    assert client.get("/api/auth/me", headers=_auth(laptop["credential"])).status_code == 401
    assert client.get("/api/auth/me", headers=_auth(phone["credential"])).status_code == 200

    devices = client.get("/api/auth/devices", headers=_auth(phone["credential"])).json()
    by_id = {row["device_id"]: row for row in devices["devices"]}
    assert by_id[laptop["device_id"]]["revoked"] is True
    assert by_id[phone["device_id"]]["revoked"] is False


def test_device_cannot_revoke_another_owners_device(client):
    enrolled = _pair(client)
    # A device belonging to a different owner.
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO aariya_personal_devices "
            "(device_id, owner_id, device_role, label, platform, credential_hash, "
            " created_at, last_seen_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("other-device", "someone-else", "dashboard", "theirs", "linux",
             "b" * 64, 0.0, 0.0),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.delete(
        "/api/auth/devices/other-device", headers=_auth(enrolled["credential"])
    )
    assert response.status_code == 404
    assert client.get("/api/auth/devices", headers=_auth(enrolled["credential"])).json()[
        "devices"
    ][0]["revoked"] is False


def test_both_devices_resolve_to_the_same_owner(client):
    laptop = _pair(client, label="laptop")
    phone = _pair(client, role="mobile", label="phone", platform="android")

    assert laptop["owner_id"] == phone["owner_id"] == OWNER
    me_laptop = client.get("/api/auth/me", headers=_auth(laptop["credential"])).json()
    me_phone = client.get("/api/auth/me", headers=_auth(phone["credential"])).json()
    assert me_laptop["owner_id"] == me_phone["owner_id"] == OWNER
    assert me_laptop["device_id"] != me_phone["device_id"]


# ── WebSocket tickets ───────────────────────────────────────────────────────

def test_valid_ticket_opens_the_socket(client):
    enrolled = _pair(client)
    ticket = _ticket(client, enrolled["credential"], "/ws/synoptics")
    with client.websocket_connect(
        "/ws/synoptics",
        subprotocols=["aariya.v1", f"aariya-ticket.{ticket}"],
    ):
        pass


def test_ticket_is_single_use(client):
    enrolled = _pair(client)
    ticket = _ticket(client, enrolled["credential"], "/ws/synoptics")
    proto = ["aariya.v1", f"aariya-ticket.{ticket}"]

    with client.websocket_connect("/ws/synoptics", subprotocols=proto):
        pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/synoptics", subprotocols=proto):
            pass


def test_expired_ticket_is_rejected(client):
    enrolled = _pair(client)
    ticket = _ticket(client, enrolled["credential"], "/ws/synoptics")

    conn = get_db_connection()
    try:
        conn.execute("UPDATE aariya_ws_tickets SET expires_at = 0")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws/synoptics",
            subprotocols=["aariya.v1", f"aariya-ticket.{ticket}"],
        ):
            pass


def test_ticket_is_bound_to_its_route(client):
    enrolled = _pair(client)
    ticket = _ticket(client, enrolled["credential"], "/ws/synoptics")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            "/ws/brain_metrics",
            subprotocols=["aariya.v1", f"aariya-ticket.{ticket}"],
        ):
            pass


def test_mobile_role_cannot_get_dashboard_authority(client):
    phone = _pair(client, role="mobile", label="phone", platform="android")
    for path in ("/api/security/stream", "/ws/brain", "/api/agents/ws"):
        response = client.post(
            "/api/auth/ws-ticket", json={"path": path}, headers=_auth(phone["credential"])
        )
        assert response.status_code == 403, (path, response.text)


def test_dashboard_role_cannot_open_mobile_channel(client):
    laptop = _pair(client)
    response = client.post(
        "/api/auth/ws-ticket",
        json={"path": "/ws/mobile"},
        headers=_auth(laptop["credential"]),
    )
    assert response.status_code == 403


def test_simultaneous_ticket_redemption_has_exactly_one_winner(client):
    enrolled = _pair(client)
    ticket = _ticket(client, enrolled["credential"], "/ws/synoptics")

    def redeem():
        try:
            redeem_ws_ticket(ticket, "/ws/synoptics")
            return True
        except DeviceAuthError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: redeem(), range(2)))

    assert sorted(results) == [False, True]


# ── Owner binding / spoofing ────────────────────────────────────────────────

def test_forged_user_id_query_cannot_change_owner(client):
    laptop = _pair(client)
    ticket = _ticket(client, laptop["credential"], "/ws/synoptics")

    # The forged query is irrelevant: the ticket resolves owner u1.
    with client.websocket_connect(
        "/ws/synoptics?user_id=attacker",
        subprotocols=["aariya.v1", f"aariya-ticket.{ticket}"],
    ):
        pass

    me = client.get(
        "/api/auth/me?user_id=attacker", headers=_auth(laptop["credential"])
    ).json()
    assert me["owner_id"] == OWNER


def test_forged_ingest_device_identity_is_ignored(client):
    laptop = _pair(client)
    response = client.post(
        "/ingest/device",
        json={
            "device_id": "victim-device",
            "user_id": "victim-owner",
            "platform": "linux",
            "model": "spoof",
        },
        headers=_auth(laptop["credential"]),
    )
    assert response.status_code == 200

    conn = get_db_connection()
    try:
        own = conn.execute(
            "SELECT user_id FROM devices WHERE device_id = ?",
            (laptop["device_id"],),
        ).fetchone()
        victim = conn.execute(
            "SELECT 1 FROM devices WHERE device_id = 'victim-device'"
        ).fetchone()
    finally:
        conn.close()

    assert own is not None and own["user_id"] == OWNER
    assert victim is None


def test_ingest_device_requires_a_credential_in_strict_mode(client):
    response = client.post(
        "/ingest/device",
        json={"device_id": "x", "user_id": "y", "platform": "linux"},
    )
    assert response.status_code == 401


def test_ticket_endpoint_requires_a_device_credential(client):
    response = client.post("/api/auth/ws-ticket", json={"path": "/ws/synoptics"})
    assert response.status_code == 401


def test_personal_analytics_uses_the_authenticated_owner(client):
    """Editing ?user_id= must not select another person's memories."""
    laptop = _pair(client)
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO memories (id, user_id, text, valence, trust, significance, created_at) "
            "VALUES (?, ?, ?, 0, 0.5, 1, 0)",
            ("m-owner", OWNER, "mine"),
        )
        conn.execute(
            "INSERT INTO memories (id, user_id, text, valence, trust, significance, created_at) "
            "VALUES (?, ?, ?, 0, 0.5, 1, 0)",
            ("m-victim", "victim", "theirs"),
        )
        conn.commit()
    finally:
        conn.close()

    response = client.get(
        "/api/analytics/memories?user_id=victim",
        headers=_auth(laptop["credential"]),
    )
    assert response.status_code == 200
    texts = [row["content"] for row in response.json()]
    assert texts == ["mine"]


def test_personal_analytics_requires_a_credential_in_strict_mode(client):
    response = client.get("/api/analytics/memories?user_id=u1")
    assert response.status_code == 401


def test_emotion_predictor_requires_a_credential_in_strict_mode(client):
    response = client.get("/api/emotion/predictor?user_id=u1")
    assert response.status_code == 401


def test_tools_and_knowledge_require_a_credential_in_strict_mode(client):
    assert client.get("/api/tools").status_code == 401
    assert client.post("/api/tools/call", json={"name": "shell"}).status_code == 401
    assert client.post("/api/knowledge/ingest", json={"user_id": OWNER}).status_code == 401
    assert client.get("/api/knowledge/symbol?symbol=os").status_code == 401


def test_pairing_codes_use_100_bits_and_four_groups(client):
    code = create_pairing_code(role="mobile", owner_id=OWNER)
    assert re.fullmatch(r"(?:[A-Z2-9]{5}-){3}[A-Z2-9]{5}", code)


def test_pairing_attempts_are_rate_limited(client):
    for _ in range(5):
        response = client.post(
            "/api/auth/device/enroll",
            json={"pairing_code": "ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ", "label": "x", "platform": "t"},
        )
        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower()

    blocked = client.post(
        "/api/auth/device/enroll",
        json={"pairing_code": "ZZZZZ-ZZZZZ-ZZZZZ-ZZZZZ", "label": "x", "platform": "t"},
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_required_device_auth_refuses_startup_without_owner(monkeypatch):
    monkeypatch.setenv("AARIYA_DEVICE_AUTH_REQUIRED", "1")
    monkeypatch.delenv("AARIYA_OWNER_ID", raising=False)
    with pytest.raises(RuntimeError, match="AARIYA_OWNER_ID"):
        validate_device_auth_configuration()


def test_mobile_cannot_use_dashboard_rest_authority(client):
    phone = _pair(client, role="mobile", label="phone", platform="android")
    headers = _auth(phone["credential"])

    assert client.get("/api/system/health", headers=headers).status_code == 403
    assert client.get("/api/fs/roots", headers=headers).status_code == 403
    assert client.get("/api/security/last-scan", headers=headers).status_code == 403
    assert client.post("/api/autonomy/enable", json={"enabled": True}, headers=headers).status_code == 403
    assert client.post(
        "/api/compliance/consent", json={"user_id": OWNER, "consent": {}}, headers=headers
    ).status_code == 403
    assert client.post(
        "/api/memory/import", json={"envelope": {}}, headers=headers
    ).status_code == 403
    assert client.post(
        "/api/tools/call", json={"name": "shell"}, headers=headers
    ).status_code == 403
    assert client.delete(
        f"/api/auth/devices/{phone['device_id']}", headers=headers
    ).status_code == 403


def test_mobile_can_read_personal_state(client):
    phone = _pair(client, role="mobile", label="phone", platform="android")
    headers = _auth(phone["credential"])

    assert client.get("/api/autonomy/state", headers=headers).status_code == 200
    assert client.get("/api/events/latest", headers=headers).status_code == 200
    assert client.get("/api/memory/ledger", headers=headers).status_code == 200
    assert client.get("/api/compliance/consent-status", headers=headers).status_code == 200


def test_dashboard_health_requires_a_device_in_strict_mode(client):
    assert client.get("/api/system/health").status_code == 401
    laptop = _pair(client)
    response = client.get(
        "/api/system/health", headers=_auth(laptop["credential"])
    )
    assert response.status_code == 200


class _FakeSocket:
    def __init__(self):
        self.sent = []
        self.closed = None

    async def send_text(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


def test_revocation_closes_live_socket_and_rejects_late_registration(client):
    laptop = _pair(client)
    socket = _FakeSocket()

    async def scenario():
        device_connections.clear()
        assert await device_connections.register(laptop["device_id"], socket)
        assert await revoke_device_and_disconnect(laptop["device_id"], OWNER)
        # A socket whose ticket was redeemed just before revocation must not be
        # able to register after the device was marked revoked.
        late = _FakeSocket()
        assert not await device_connections.register(laptop["device_id"], late)
        return late

    late = asyncio.run(scenario())
    assert any('"device.revoked"' in frame for frame in socket.sent)
    assert socket.closed and socket.closed[0] == 4001
    assert late.sent == [] and late.closed is None
    device_connections.clear()


def test_collab_rest_requires_a_credential_and_stamps_device(
    client, tmp_path, monkeypatch
):
    from server.systems.collaboration import shared_workspace as workspace_store

    monkeypatch.setattr(
        workspace_store, "_path_for", lambda slug: str(tmp_path / f"{slug}.json")
    )

    denied = client.post(
        "/api/collab/desk/notes", json={"author": "attacker", "text": "hi"}
    )
    assert denied.status_code == 401
    assert client.get("/api/collab/workspaces").status_code == 401

    laptop = _pair(client)
    headers = _auth(laptop["credential"])
    created = client.post(
        "/api/collab/desk", json={"participant": "attacker"}, headers=headers
    )
    assert created.status_code == 200, created.text

    note = client.post(
        "/api/collab/desk/notes",
        json={"author": "attacker", "text": "hi"},
        headers=headers,
    )
    assert note.status_code == 200, note.text
    assert note.json()["note"]["author"] == "laptop"
