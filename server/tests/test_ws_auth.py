"""Tests for the WebSocket auth layer (server/systems/security/auth.py).

Two behaviours matter and neither was covered before:

1. `verify_ws_token` was never called by ANY handler — it existed, was
   documented, and was bypassed everywhere. These tests pin the contract it
   now relies on: it rejects (close 1008) an unauthenticated socket when
   auth is required, and short-circuits to a pass in soft mode.

2. `verify_message_signature` failed OPEN whenever WS_SECRET_TOKEN was unset,
   so a production deployment that flipped REQUIRE_WS_AUTH=1 without also
   setting a secret accepted every unsigned high-trust frame. It must now fail
   closed in exactly that configuration.

The module reads env vars at import time, so each test reloads it with a
patched environment rather than mutating globals.
"""

import asyncio
import hashlib
import hmac
import importlib

from server.systems.security import auth as auth_module


class _FakeWebSocket:
    """Minimal WebSocket stand-in capturing the close code FastAPI would see."""

    def __init__(self, token=None, authorization=None):
        self.query_params = {}
        if token is not None:
            self.query_params["token"] = token
        self.headers = {}
        if authorization is not None:
            self.headers["authorization"] = authorization
        self.closed = None

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)


def _reload(monkeypatch, **env):
    for key, value in env.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    return importlib.reload(auth_module)


# ── verify_ws_token ───────────────────────────────────────────────────────────

def test_soft_mode_accepts_anonymous_socket(monkeypatch):
    """No REQUIRE_WS_AUTH → dev keeps working with no token at all."""
    mod = _reload(monkeypatch, REQUIRE_WS_AUTH="0", WS_SECRET_TOKEN=None)
    ws = _FakeWebSocket()
    assert asyncio.run(mod.verify_ws_token(ws)) is True
    assert ws.closed is None


def test_required_auth_rejects_missing_token(monkeypatch):
    mod = _reload(monkeypatch, REQUIRE_WS_AUTH="1", WS_SECRET_TOKEN="s3cret")
    ws = _FakeWebSocket()
    assert asyncio.run(mod.verify_ws_token(ws)) is False
    assert ws.closed[0] == 1008


def test_required_auth_rejects_wrong_token(monkeypatch):
    mod = _reload(monkeypatch, REQUIRE_WS_AUTH="1", WS_SECRET_TOKEN="s3cret")
    ws = _FakeWebSocket(token="not-the-secret")
    assert asyncio.run(mod.verify_ws_token(ws)) is False
    assert ws.closed[0] == 1008


def test_query_param_token_is_accepted(monkeypatch):
    mod = _reload(monkeypatch, REQUIRE_WS_AUTH="1", WS_SECRET_TOKEN="s3cret")
    ws = _FakeWebSocket(token="s3cret")
    assert asyncio.run(mod.verify_ws_token(ws)) is True
    assert ws.closed is None


def test_bearer_header_token_is_accepted(monkeypatch):
    mod = _reload(monkeypatch, REQUIRE_WS_AUTH="1", WS_SECRET_TOKEN="s3cret")
    ws = _FakeWebSocket(authorization="Bearer s3cret")
    assert asyncio.run(mod.verify_ws_token(ws)) is True
    assert ws.closed is None


def test_bearer_header_is_case_insensitive(monkeypatch):
    mod = _reload(monkeypatch, REQUIRE_WS_AUTH="1", WS_SECRET_TOKEN="s3cret")
    ws = _FakeWebSocket(authorization="bearer s3cret")
    assert asyncio.run(mod.verify_ws_token(ws)) is True


# ── verify_message_signature ──────────────────────────────────────────────────

def _sign(secret, message):
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def test_valid_signature_accepted(monkeypatch):
    mod = _reload(monkeypatch, REQUIRE_WS_AUTH="1", WS_SECRET_TOKEN="s3cret")
    assert mod.verify_message_signature("wipe", _sign("s3cret", "wipe")) is True


def test_tampered_message_rejected(monkeypatch):
    mod = _reload(monkeypatch, REQUIRE_WS_AUTH="1", WS_SECRET_TOKEN="s3cret")
    assert mod.verify_message_signature("wipe", _sign("s3cret", "wipe --all")) is False


def test_missing_secret_fails_closed_when_auth_required(monkeypatch):
    """REQUIRE_WS_AUTH=1 with no secret must reject, not wave everything through."""
    mod = _reload(monkeypatch, REQUIRE_WS_AUTH="1", WS_SECRET_TOKEN=None)
    assert mod.verify_message_signature("wipe", "anything") is False
    assert mod.verify_message_signature("wipe", "") is False


def test_missing_secret_still_permissive_in_soft_mode(monkeypatch):
    mod = _reload(monkeypatch, REQUIRE_WS_AUTH="0", WS_SECRET_TOKEN=None)
    assert mod.verify_message_signature("wipe", "anything") is True