"""Endpoint-level tests for the mobile zero-interference authority gate.

Resolves the `*Mobile Achi v2.txt` contradiction: the blueprint's Phase 4
hands mobile `wipe_memory` / `set_personality` / `force_mode`, while its
security rule forbids exactly those ("mobile = control layer, laptop =
authority layer"). We enforce the security rule server-side: the mobile
control channel rejects authority-only actions with a `command_denied`
frame, while control-layer traffic (ping / interrupt) still flows.

These tests drive the real FastAPI app through the TestClient with the
brain + lifespan singletons swapped for deterministic doubles — hermetic,
no network, no dev database.
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

from server import main as server_main
from server.protocol import BrainState, MultimodalOutput
from server.systems.security import mobile_authority


class _FakeBrain:
    """Canned brain — the authority tests never reach it, but the fixture
    needs a valid BrainV2 stand-in for the app to import cleanly."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.state = BrainState(valence=0.0, arousal=0.3, emotion="neutral")

    async def process(self, input_model, on_token=None):
        return MultimodalOutput(text="ok", expression="neutral", gestures=[], thought=None)

    def get_state(self) -> BrainState:
        return self.state


class _NoopDaemon:
    def start(self):  # pragma: no cover — never called in these tests
        pass

    async def stop(self):  # pragma: no cover
        pass

    def on_user_message(self, *args, **kwargs):
        pass

    def record_snapshot(self, *args, **kwargs):
        pass


class _NoopWatcher:
    def start(self, loop):
        pass

    def stop(self):
        pass


@pytest.fixture(autouse=True)
def _hermetic_backend(monkeypatch, isolated_db):
    monkeypatch.setattr(server_main, "BrainV2", _FakeBrain)
    monkeypatch.setattr(server_main, "get_daemon", lambda *a, **k: _NoopDaemon())
    monkeypatch.setattr(server_main, "get_watcher", lambda *a, **k: _NoopWatcher())


def _control_roundtrip(client, payload, expected_frames=1):
    """Send one JSON message on /ws/mobile/control, collect reply frames.

    The handler answers synchronously then loops back to `receive_text`, so a
    blocking read in the test thread would hang forever. Frames are drained in
    a DAEMON thread through a queue until `expected_frames` arrive; the main
    thread waits with a real deadline. A reply frame can also be a WebSocket
    close, which surfaces as an exception in the drain thread.
    """
    import queue
    import threading

    result: "queue.Queue" = queue.Queue()

    def _drain(ws):
        seen = []
        try:
            while len(seen) < expected_frames:
                seen.append(json.loads(ws.receive_text()))
        except Exception as exc:  # noqa: BLE001 — connection closed early
            result.put(("err", exc))
            return
        result.put(("ok", seen))

    with client.websocket_connect("/ws/mobile/control") as ws:
        thread = threading.Thread(target=_drain, args=(ws,), daemon=True)
        thread.start()
        ws.send_text(json.dumps(payload))
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            try:
                kind, payload_out = result.get(timeout=0.5)
                if kind == "err":
                    pytest.fail(f"drain failed: {payload_out}")
                return payload_out
            except queue.Empty:
                continue
        pytest.fail(f"only partial/no reply frames for {payload} within 3s")
    return []


@pytest.mark.parametrize("action", sorted(mobile_authority.MOBILE_AUTHORITY_ONLY_ACTIONS))
def test_authority_only_commands_are_denied(action):
    """Every authority-only action is rejected on the mobile control channel."""
    with TestClient(server_main.app) as client:
        replies = _control_roundtrip(client, {
            "type": "command",
            "action": action,
            "id": "m_auth_1",
        }, expected_frames=2)

    denied = [r for r in replies if r.get("type") == "command_denied"]
    assert denied, f"expected command_denied for {action!r}, got {replies}"
    assert denied[-1]["action"] == action
    assert denied[-1]["reason"] == mobile_authority.DENIED_REASON
    # The reliable-message ack still fires so the client outbox clears.
    assert any(r.get("type") == "ack" and r.get("id") == "m_auth_1" for r in replies)


def test_mobile_authority_policy_is_complete():
    """The gate covers exactly the destructive/identity-mutating family the
    blueprint's security rule names."""
    assert mobile_authority.MOBILE_AUTHORITY_ONLY_ACTIONS == {
        "wipe_memory",
        "set_personality",
        "override_mode",
        "force_mode",
    }
    # And the utility helpers agree with each other.
    for action in mobile_authority.MOBILE_AUTHORITY_ONLY_ACTIONS:
        assert not mobile_authority.is_mobile_allowed(action)
    assert mobile_authority.is_mobile_allowed("ping")
    assert mobile_authority.is_mobile_allowed("remote_input")


def test_mobile_control_layer_traffic_is_allowed():
    """Ping still gets a pong; the gate must not break heartbeats."""
    with TestClient(server_main.app) as client:
        replies = _control_roundtrip(client, {"type": "ping"})
    assert any(r.get("type") == "pong" for r in replies)
