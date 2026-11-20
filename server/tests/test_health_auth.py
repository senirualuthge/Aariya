"""Auth guard for the System Health REST routes.

The health payload exposes per-user session/lock state, so `/api/system/*`
must not be anonymously readable from another machine:

  * soft mode (dev): loopback may read without a token; remote may not.
  * REQUIRE_WS_AUTH=1: every request needs a valid token, loopback included.
"""

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from server.routers.system_health_router import router
from server.systems.security import auth


def _request(headers=None, query=b"", client=("127.0.0.1", 1234)):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/system/health",
        "headers": raw,
        "query_string": query,
        "client": client,
    })


@pytest.fixture()
def app():
    app = FastAPI()
    app.include_router(router)
    return app


# ── Dependency behaviour ─────────────────────────────────────────────────────

def test_soft_mode_allows_loopback_without_token(monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", False)
    auth.require_health_auth(_request(client=("127.0.0.1", 4242)))
    auth.require_health_auth(_request(client=("::1", 4242)))


def test_soft_mode_rejects_remote_without_token(monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", False)
    with pytest.raises(HTTPException) as excinfo:
        auth.require_health_auth(_request(client=("203.0.113.5", 5555)))
    assert excinfo.value.status_code == 401


def test_soft_mode_allows_remote_with_bearer_token(monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", False)
    monkeypatch.setattr(auth, "SECRET_TOKEN", "s3cret")
    auth.require_health_auth(_request(
        headers={"Authorization": "Bearer s3cret"},
        client=("203.0.113.5", 5555),
    ))


def test_soft_mode_allows_remote_with_query_token(monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", False)
    monkeypatch.setattr(auth, "SECRET_TOKEN", "s3cret")
    auth.require_health_auth(_request(
        query=b"token=s3cret", client=("203.0.113.5", 5555),
    ))


def test_forwarded_header_ignored_from_untrusted_peer(monkeypatch):
    """A remote client cannot claim to be loopback via X-Forwarded-For."""
    monkeypatch.setattr(auth, "REQUIRE_AUTH", False)
    monkeypatch.delenv("AARIYA_TRUSTED_PROXIES", raising=False)
    with pytest.raises(HTTPException):
        auth.require_health_auth(_request(
            headers={"X-Forwarded-For": "127.0.0.1"},
            client=("203.0.113.5", 5555),
        ))


def test_trusted_proxy_forwarded_remote_client_is_remote(monkeypatch):
    """Through a trusted proxy, the forwarded remote client still needs a token."""
    monkeypatch.setattr(auth, "REQUIRE_AUTH", False)
    monkeypatch.setenv("AARIYA_TRUSTED_PROXIES", "127.0.0.1")
    with pytest.raises(HTTPException):
        auth.require_health_auth(_request(
            headers={"X-Forwarded-For": "203.0.113.9"},
            client=("127.0.0.1", 5555),
        ))


def test_trusted_proxy_forwarded_loopback_client_is_local(monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", False)
    monkeypatch.setenv("AARIYA_TRUSTED_PROXIES", "127.0.0.1")
    auth.require_health_auth(_request(
        headers={"X-Forwarded-For": "127.0.0.1"},
        client=("127.0.0.1", 5555),
    ))


def test_forwarded_chain_skips_trusted_proxy_hops(monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", False)
    monkeypatch.setenv("AARIYA_TRUSTED_PROXIES", "127.0.0.1,10.0.0.0/8")
    with pytest.raises(HTTPException):
        auth.require_health_auth(_request(
            headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.5"},
            client=("127.0.0.1", 5555),
        ))


# ── Strict mode ───────────────────────────────────────────────

def test_strict_mode_requires_token_even_locally(monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", True)
    monkeypatch.setattr(auth, "SECRET_TOKEN", "s3cret")

    with pytest.raises(HTTPException) as excinfo:
        auth.require_health_auth(_request(client=("127.0.0.1", 4242)))
    assert excinfo.value.status_code == 401

    auth.require_health_auth(_request(headers={"Authorization": "Bearer s3cret"}))


def test_strict_mode_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", True)
    monkeypatch.setattr(auth, "SECRET_TOKEN", "s3cret")
    with pytest.raises(HTTPException):
        auth.require_health_auth(_request(headers={"Authorization": "Bearer nope"}))


# ── Router wiring ────────────────────────────────────────────────────────────

def test_health_routes_are_protected_in_strict_mode(monkeypatch, app):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", True)
    monkeypatch.setattr(auth, "SECRET_TOKEN", "s3cret")
    client = TestClient(app)

    assert client.get("/api/system/health").status_code == 401
    assert client.get("/api/system/health/checks").status_code == 401

    ok = client.get(
        "/api/system/health", headers={"Authorization": "Bearer s3cret"}
    )
    assert ok.status_code == 200
    assert "cognitive_sessions" in ok.json()


def test_health_routes_reachable_locally_in_soft_mode(monkeypatch, app):
    monkeypatch.setattr(auth, "REQUIRE_AUTH", False)
    client = TestClient(app)
    resp = client.get("/api/system/health/checks")
    assert resp.status_code == 200
