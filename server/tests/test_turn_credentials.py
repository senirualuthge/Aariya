"""Tests for short-lived TURN credentials endpoint (server/realtime/turn_credentials.py)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

import pytest
from fastapi.testclient import TestClient

from server import main as server_main
from server.realtime import turn_credentials
from server.systems.security.device_auth import create_pairing_code

OWNER = "u1"


def generate_expected_credential(
    username: str,
    secret: str,
) -> str:
    digest = hmac.new(
        secret.encode(),
        username.encode(),
        hashlib.sha1,
    ).digest()
    return base64.b64encode(digest).decode()


def test_turn_credential_generation():
    secret = "test-only-secret"
    username = f"{int(time.time()) + 3600}:device-test"
    credential = generate_expected_credential(
        username,
        secret,
    )
    assert credential
    assert credential != secret


def test_turn_credentials_are_expiring():
    expiry = int(time.time()) + 3600
    username = f"{expiry}:aariya"
    assert int(username.split(":")[0]) == expiry


def test_turn_credential_matches_coturn_hmac(monkeypatch):
    secret = "test-turn-secret-key"
    monkeypatch.setenv("TURN_SHARED_SECRET", secret)
    monkeypatch.setenv("TURN_URLS", "turn:turn.example.com:3478")
    result = turn_credentials.generate_turn_credentials(
        lifetime_seconds=120
    )
    expected = base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            result["username"].encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")
    assert result["credential"] == expected
    assert result["credential"] != secret
    expiry = int(result["username"].split(":")[0])
    assert expiry > int(time.time())
    assert expiry <= int(time.time()) + 120


@pytest.fixture
def strict_auth(isolated_db, monkeypatch):
    monkeypatch.setenv("AARIYA_OWNER_ID", OWNER)
    monkeypatch.setenv("TURN_SHARED_SECRET", "test-turn-secret-key")
    monkeypatch.setenv("TURN_URLS", "turn:turn.example.com:3478,turns:turn.example.com:5349")
    yield isolated_db


@pytest.fixture
def client(strict_auth):
    return TestClient(server_main.app)


def _pair(client, role="mobile", label="phone", platform="ios"):
    code = create_pairing_code(role=role)
    response = client.post(
        "/api/auth/device/enroll",
        json={"pairing_code": code, "label": label, "platform": platform},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth(credential):
    return {"Authorization": f"Bearer {credential}"}


def test_turn_credentials_without_token_rejected(client):
    response = client.get("/api/webrtc/turn-credentials")
    assert response.status_code == 401


def test_turn_credentials_for_dashboard_role_rejected(client):
    dashboard = _pair(client, role="dashboard", label="laptop", platform="macos")
    response = client.get(
        "/api/webrtc/turn-credentials",
        headers=_auth(dashboard["credential"]),
    )
    assert response.status_code == 403


def test_turn_credentials_success(client):
    device = _pair(client)
    response = client.get(
        "/api/webrtc/turn-credentials",
        headers=_auth(device["credential"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "urls" in data
    assert "turn:turn.example.com:3478" in data["urls"]
    assert "username" in data
    assert data["username"].endswith(":aariya")
    expiry = int(data["username"].split(":")[0])
    assert expiry > int(time.time())
    assert "credential" in data
    assert len(data["credential"]) > 10
    assert data["ttl"] == 3600


def test_turn_credentials_missing_secret_returns_503(client, monkeypatch):
    monkeypatch.delenv("TURN_SHARED_SECRET", raising=False)
    device = _pair(client)
    response = client.get(
        "/api/webrtc/turn-credentials",
        headers=_auth(device["credential"]),
    )
    assert response.status_code == 503
    assert "TURN_SHARED_SECRET" in response.json()["detail"]


def test_turn_credentials_missing_urls_returns_503(client, monkeypatch):
    monkeypatch.delenv("TURN_URLS", raising=False)
    device = _pair(client)
    response = client.get(
        "/api/webrtc/turn-credentials",
        headers=_auth(device["credential"]),
    )
    assert response.status_code == 503
    assert "TURN_URLS" in response.json()["detail"]


def test_generate_turn_credentials_lifetime_bounds(monkeypatch):
    monkeypatch.setenv("TURN_SHARED_SECRET", "secret")
    monkeypatch.setenv("TURN_URLS", "turn:example.com:3478")

    with pytest.raises(ValueError):
        turn_credentials.generate_turn_credentials(lifetime_seconds=50)

    with pytest.raises(ValueError):
        turn_credentials.generate_turn_credentials(lifetime_seconds=100000)

    creds = turn_credentials.generate_turn_credentials(lifetime_seconds=120)
    assert creds["ttl"] == 120
