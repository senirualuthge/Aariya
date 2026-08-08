"""Endpoint-level integration tests for the cross-surface broadcast switch.

Drives the real FastAPI app through the TestClient and asserts that a turn
on ONE surface delivers ``state.update`` / ``inner_thought`` frames to
EVERY connected surface — the property introduced when /ws/mobile switched
from sending those frames inline to its own connection over to
``session_manager.broadcast_state`` / ``session_manager.broadcast``:

  * phone → phone: a /ws/mobile turn reaches a second, silent /ws/mobile
  * dashboard → phone: a /ws/brain turn reaches a connected /ws/mobile

The BrainV2 class is swapped for a deterministic double (no LLM / swarm /
network), and the lifespan's daemon + watcher singletons are no-opped, so
the tests exercise the real app routing, session-manager registries, WS
protocol mapping, and broadcast — hermetic and fast.
"""

import json
import queue
import threading

import pytest
from fastapi.testclient import TestClient

from server import main as server_main
from server.protocol import BrainState, MultimodalOutput


class _FakeBrain:
    """Canned brain — fixed reply + state so the broadcasts are deterministic."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.state = BrainState(valence=0.4, arousal=0.7, emotion="calm")

    async def process(self, input_model, on_token=None):
        return MultimodalOutput(
            text="Hello from the fake brain.",
            expression="smile",
            gestures=[],
            thought="a quiet thought",
            state_update=self.state,
        )

    def get_state(self) -> BrainState:
        return self.state


class _NoopDaemon:
    """Stand-in so the mobile handler's daemon calls are side-effect free."""

    def start(self):
        pass

    async def stop(self):
        pass

    def on_user_message(self, *args, **kwargs):
        pass

    def record_snapshot(self, *args, **kwargs):
        pass


class _NoopWatcher:
    """Stand-in so lifespan startup skips the heavyweight file-watch observer."""

    def start(self, loop):
        pass

    def stop(self):
        pass


@pytest.fixture(autouse=True)
def _hermetic_backend(monkeypatch, isolated_db):
    """Swap the brain for a deterministic double and no-op the lifespan
    singletons (daemon + watcher) so the integration test never touches the
    network, the dev database, or the file watcher."""
    monkeypatch.setattr(server_main, "BrainV2", _FakeBrain)
    monkeypatch.setattr(server_main, "get_daemon", lambda *a, **k: _NoopDaemon())
    monkeypatch.setattr(server_main, "get_watcher", lambda *a, **k: _NoopWatcher())


def _read_until(ws, label, want, timeout=15.0):
    """Drain frames until one message of every type in ``want`` arrives.

    Returns {frame_type: message}. ``receive_text`` blocks indefinitely
    (inside the TestClient portal) when a broadcast never comes, so draining
    runs in a DAEMON thread that pushes the result through a queue; the main
    thread waits with a real deadline. A regression (missing frame) fails the
    test cleanly — the lingering daemon thread cannot block interpreter exit.
    """
    result: "queue.Queue" = queue.Queue()

    def _drain():
        seen: dict = {}
        try:
            while True:
                msg = json.loads(ws.receive_text())
                ftype = msg.get("type")
                if ftype in want and ftype not in seen:
                    seen[ftype] = msg
                    if set(seen) >= set(want):
                        result.put(("ok", seen))
                        return
        except Exception as exc:  # noqa: BLE001 — report any receive failure
            result.put(("err", exc))

    threading.Thread(target=_drain, daemon=True, name=f"drain-{label}").start()

    try:
        kind, payload = result.get(timeout=timeout)
    except queue.Empty:
        pytest.fail(
            f"{label}: no {sorted(want)} frame within {timeout}s — broadcast broken?"
        )
    if kind == "err":
        pytest.fail(f"{label}: receive failed: {payload}")
    return payload


def test_mobile_state_and_thought_frames_arrive_on_second_socket():
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/mobile") as phone_a, \
             client.websocket_connect("/ws/mobile") as phone_b:

            # Only phone_a speaks.
            phone_a.send_json({
                "type": "input.multimodal",
                "content": "hi",
                "mode": "voice",
            })

            # The requesting socket gets its own frames...
            frames_a = _read_until(phone_a, "phone-a", {"state.update", "inner_thought"})
            # ...and the silent socket — which never sent anything — must too.
            frames_b = _read_until(phone_b, "phone-b", {"state.update", "inner_thought"})

            # state.update: same brain state broadcast to every surface.
            assert frames_a["state.update"]["state"]["emotion"] == "calm"
            assert frames_a["state.update"]["state"]["valence"] == 0.4
            assert frames_a["state.update"]["state"]["arousal"] == 0.7
            assert frames_b["state.update"]["state"] == frames_a["state.update"]["state"]

            # inner_thought: the private thought is broadcast too.
            assert frames_a["inner_thought"]["thought"] == "a quiet thought"
            assert frames_b["inner_thought"]["thought"] == "a quiet thought"


def test_dashboard_turn_state_frame_arrives_on_phone():
    """A /ws/brain (dashboard) turn must reach a connected phone.

    The shared cognitive loop already broadcasts state and inner_thought via
    broadcast_state / broadcast; this pins down the "from any surface" half
    of the contract so a regression in the shared loop (inline-only send) is
    caught in BOTH directions.
    """
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/mobile") as phone, \
             client.websocket_connect("/ws/brain") as dashboard:

            # Only the dashboard speaks.
            dashboard.send_json({"text": "hi"})

            # The dashboard (requester) gets its own frames...
            frames_d = _read_until(dashboard, "dashboard", {"state.update", "inner_thought"})
            # ...and the connected phone gets the dashboard-produced frames.
            frames_p = _read_until(phone, "phone", {"state.update", "inner_thought"})

            # state.update: same brain state broadcast to every surface.
            assert frames_p["state.update"]["state"]["emotion"] == "calm"
            assert frames_p["state.update"]["state"]["valence"] == 0.4
            assert frames_d["state.update"]["state"] == frames_p["state.update"]["state"]

            # inner_thought: the dashboard turn's private thought reaches the phone.
            assert frames_p["inner_thought"]["thought"] == "a quiet thought"
            assert frames_d["inner_thought"]["thought"] == "a quiet thought"
