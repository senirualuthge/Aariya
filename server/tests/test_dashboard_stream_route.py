"""Regression tests for the /ws/dashboard/stream WebSocket route.

History: the path was registered TWICE — once by server.routers.dashboard_ws
(a 10 Hz swarm-snapshot handler that only SENT dashboard.update frames and
never read incoming messages) and once by server.main's
websocket_dashboard_stream (the full cognitive loop). Starlette matches routes
in registration order, so the router's handler won and the cognitive loop
behind the path was shadowed: the web chat (which sends {type:'input'} over
this socket) got no replies and its inputs were silently dropped.

The duplicate mount is gone. These tests lock in the intended contract:
  1. /ws/dashboard/stream is registered exactly once, pointing at the
     cognitive loop in server.main (NOT the swarm-snapshot router).
  2. The path actually SERVES the cognitive loop: a control command receives
     an autonomy.ack reply, and no dashboard.update frame is emitted (the old
     swarm handler replied to nothing and spammed dashboard.update at 10 Hz).
"""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from server import main as server_main
from server.protocol import BrainState, MultimodalOutput


class _FakeBrain:
    """Canned brain — the control-command path never reaches it, but the
    handler constructs a BrainV2 on connect, so a stand-in keeps the test
    hermetic (no RAG / chromadb / dev-DB writes)."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.state = BrainState(valence=0.0, arousal=0.3, emotion="neutral")

    async def process(self, input_model, on_token=None):
        return MultimodalOutput(text="ok", expression="neutral", gestures=[], thought=None)

    def get_state(self) -> BrainState:
        return self.state


class _NoopDaemon:
    """Control-command daemon stand-in: autonomy_enabled just toggles a flag."""

    def set_enabled(self, enabled: bool) -> dict:
        return {"ok": True, "enabled": bool(enabled)}


@pytest.fixture(autouse=True)
def _hermetic_backend(monkeypatch, isolated_db):
    """No real brain / daemon — the test never touches RAG, chromadb, or dev
    data, and nothing else in the app's lifespan starts."""
    monkeypatch.setattr(server_main, "BrainV2", _FakeBrain)
    monkeypatch.setattr(server_main, "get_daemon", lambda *a, **k: _NoopDaemon())


def _dashboard_roundtrip(payload, listen_ms=1500):
    """Send one command over /ws/dashboard/stream and collect reply frames.

    Drains in a daemon thread so a handler that never answers (the regression
    case: the old swarm-snapshot handler ignored all input) fails fast via the
    deadline instead of hanging pytest forever. Note: the app is used WITHOUT
    the lifespan context manager — the WS handlers don't need it, and it keeps
    the obsidian vault sync (chromadb) from starting during the test.
    """
    client = TestClient(server_main.app)
    with client.websocket_connect("/ws/dashboard/stream") as ws:
        frames = []

        def _drain():
            deadline = time.monotonic() + (listen_ms / 1000)
            while time.monotonic() < deadline:
                try:
                    raw = ws.receive_text()
                except Exception:  # connection closed
                    return
                try:
                    frames.append(json.loads(raw))
                except ValueError:
                    continue
                if frames and str(frames[-1].get("type", "")).endswith(".ack"):
                    # Got our reply — keep draining briefly to catch any
                    # dashboard.update spam from the old handler.
                    remaining = time.monotonic() + 0.6
                    while time.monotonic() < remaining:
                        try:
                            raw = ws.receive_text()
                        except Exception:
                            return
                        try:
                            frames.append(json.loads(raw))
                        except ValueError:
                            continue
                    return

        thread = threading.Thread(target=_drain, daemon=True)
        thread.start()
        time.sleep(0.3)  # let the handler accept and enter its receive loop
        ws.send_text(json.dumps(payload))
        thread.join(timeout=(listen_ms + 2000) / 1000)
    return frames


def test_dashboard_stream_registered_once():
    """Exactly one /ws/dashboard/stream route, owned by the cognitive loop."""
    matches = [
        r for r in server_main.app.routes
        if getattr(r, "path", None) == "/ws/dashboard/stream"
    ]
    assert len(matches) == 1, (
        f"expected exactly one /ws/dashboard/stream route, got {len(matches)}"
    )
    ep = matches[0].endpoint  # type: ignore
    assert ep.__module__ == "server.main"
    assert ep.__name__ == "websocket_dashboard_stream"


def test_dashboard_stream_serves_cognitive_loop():
    """A control command is answered — the cognitive loop's command handler
    replies; the old 10 Hz swarm-snapshot handler never read input and would
    only have emitted dashboard.update frames."""
    frames = _dashboard_roundtrip({
        "type": "command",
        "action": "autonomy_enabled",
        "enabled": True,
    })
    types = [f.get("type") for f in frames]
    assert "autonomy.ack" in types, f"expected autonomy.ack, got {types}"
    assert "dashboard.update" not in types, f"old swarm handler still serving: {types}"
