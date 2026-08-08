"""Endpoint-level tests for the laptop dashboard's AUTHORITY layer.

Mirror of test_mobile_authority.py. The resolved Zero-Interference contract
(`*Mobile Achi v2.txt`) says: mobile = control layer (authority-only commands
DENIED — see mobile_authority.py), laptop dashboard = authority layer
(commands EXECUTED on /ws/brain_metrics). These tests drive the real FastAPI
app through the TestClient and assert that:

  * set_personality persists the persona preset AND broadcasts override_mode
    to every connected dashboard surface
  * wipe_memory clears the session memory and broadcasts memory_wiped
  * override_mode / force_mode broadcast the behaviour override
  * unknown actions / unknown presets are rejected with ok:false acks
  * the dashboard's authority action set mirrors the mobile denied set

BrainV2 + lifespan singletons are swapped for deterministic doubles — hermetic,
no network, no dev database.
"""

import json
import queue
import threading

import pytest
from fastapi.testclient import TestClient

from server import main as server_main
from server.protocol import BrainState, MultimodalOutput
from server.systems.personality import PersonalitySystem
from server.systems.security import dashboard_authority, mobile_authority


class _FakeBrain:
    """Canned brain — authority tests never reach it, but the fixture needs a
    valid BrainV2 stand-in for the app to import cleanly."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.state = BrainState(valence=0.0, arousal=0.3, emotion="neutral")

    async def process(self, input_model, on_token=None):
        return MultimodalOutput(text="ok", expression="neutral", gestures=[], thought=None)

    def get_state(self) -> BrainState:
        return self.state


class _NoopDaemon:
    def start(self):
        pass

    async def stop(self):
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


class _StubMemoryHierarchy:
    """Records wipe calls instead of touching postgres/sqlite memory stores."""

    def __init__(self):
        self.cleared: list = []

    def clear_session_memory(self, session_id: str):
        self.cleared.append(session_id)


@pytest.fixture(autouse=True)
def _hermetic_backend(monkeypatch, isolated_db):
    monkeypatch.setattr(server_main, "BrainV2", _FakeBrain)
    monkeypatch.setattr(server_main, "get_daemon", lambda *a, **k: _NoopDaemon())
    monkeypatch.setattr(server_main, "get_watcher", lambda *a, **k: _NoopWatcher())
    monkeypatch.setattr(
        "server.systems.memory_hierarchy.get_memory_hierarchy",
        lambda: _StubMemoryHierarchy(),
    )


def _read_until(ws, label, want, timeout=15.0):
    """Drain frames until one message of every type in ``want`` arrives.

    Returns {frame_type: message}. ``receive_text`` blocks indefinitely inside
    the TestClient portal when a frame never comes, so draining runs in a
    DAEMON thread that pushes the result through a queue; the main thread waits
    with a real deadline. Startup `signal` frames and extra broadcasts are
    ignored — only the wanted types are collected.
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
            f"{label}: no {sorted(want)} frame within {timeout}s — authority broken?"
        )
    if kind == "err":
        pytest.fail(f"{label}: receive failed: {payload}")
    return payload


def test_set_personality_executes_and_broadcasts_to_other_dashboards():
    """The laptop's authority layer persists a persona preset and broadcasts
    override_mode so a SECOND dashboard surface syncs to the new mode."""
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/brain_metrics") as dash_a, \
             client.websocket_connect("/ws/brain_metrics") as dash_b:

            dash_a.send_json({
                "type": "command",
                "action": "set_personality",
                "preset": "warm",
            })

            frames_a = _read_until(dash_a, "dash-a", {"authority.ack", "override_mode"})
            frames_b = _read_until(dash_b, "dash-b", {"override_mode"})

            # Requester gets an ok ack + its own broadcast...
            assert frames_a["authority.ack"]["ok"] is True
            assert frames_a["authority.ack"]["action"] == "set_personality"
            assert frames_a["authority.ack"]["preset"] == "warm"
            assert frames_a["override_mode"]["mode"] == "warm"
            # ...and the silent second dashboard receives the override too.
            assert frames_b["override_mode"]["mode"] == "warm"

            # The persona was actually persisted server-side.
            persisted = PersonalitySystem("user_default").get_current_personality()
            assert persisted["emotional.warmth"] > 0.8
            assert persisted["social.formality"] < 0.3


def test_set_personality_unknown_preset_is_rejected():
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/brain_metrics") as dash:
            dash.send_json({
                "type": "command",
                "action": "set_personality",
                "preset": "no_such_persona",
            })
            frames = _read_until(dash, "dash", {"authority.ack"})

    assert frames["authority.ack"]["ok"] is False
    assert "unknown preset" in frames["authority.ack"]["error"]


def test_wipe_memory_executes_and_broadcasts_memory_wiped(monkeypatch):
    stub = _StubMemoryHierarchy()
    monkeypatch.setattr(
        "server.systems.memory_hierarchy.get_memory_hierarchy",
        lambda: stub,
    )

    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/brain_metrics") as dash:
            dash.send_json({"type": "command", "action": "wipe_memory"})
            frames = _read_until(dash, "dash", {"authority.ack", "memory_wiped"})

    assert frames["authority.ack"]["ok"] is True
    assert frames["authority.ack"]["action"] == "wipe_memory"
    assert frames["memory_wiped"]["by"] == "dashboard"
    assert stub.cleared == ["user_default"]


@pytest.mark.parametrize("action", ["override_mode", "force_mode"])
def test_mode_override_broadcasts_behaviour_override(action):
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/brain_metrics") as dash:
            dash.send_json({"type": "command", "action": action, "mode": "focus"})
            frames = _read_until(dash, "dash", {"authority.ack", "override_mode"})

    assert frames["authority.ack"]["ok"] is True
    assert frames["authority.ack"]["mode"] == "focus"
    assert frames["override_mode"]["mode"] == "focus"


def test_mode_override_missing_mode_is_rejected():
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/brain_metrics") as dash:
            dash.send_json({"type": "command", "action": "force_mode"})
            frames = _read_until(dash, "dash", {"authority.ack"})

    assert frames["authority.ack"]["ok"] is False
    assert "mode" in frames["authority.ack"]["error"]


@pytest.mark.parametrize("action", ["override_mode", "force_mode"])
def test_mode_override_unknown_mode_is_rejected(action):
    """Behaviour-mode validation: only known modes pass, so a stray/typo'd
    mode can't silently masquerade as an override."""
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/brain_metrics") as dash:
            dash.send_json({"type": "command", "action": action, "mode": "mode_99"})
            frames = _read_until(dash, "dash", {"authority.ack"})

    assert frames["authority.ack"]["ok"] is False
    assert "unknown mode" in frames["authority.ack"]["error"]
    assert "known" in frames["authority.ack"]  # lists the valid modes


def test_unknown_action_is_rejected():
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/brain_metrics") as dash:
            dash.send_json({"type": "command", "action": "definitely_not_real"})
            frames = _read_until(dash, "dash", {"authority.ack"})

    assert frames["authority.ack"]["ok"] is False
    assert "unknown action" in frames["authority.ack"]["error"]


def test_dashboard_authority_mirrors_mobile_denied_set():
    """The laptop executes exactly the actions the phone is forbidden from
    sending — the two halves of the Zero-Interference contract agree."""
    assert (
        dashboard_authority.AUTHORITY_ACTIONS
        == mobile_authority.MOBILE_AUTHORITY_ONLY_ACTIONS
    )
