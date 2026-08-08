"""Regression tests for cross-surface brain-state broadcast.

The /ws/mobile endpoint pushes `state.update` via
`session_manager.broadcast_state` instead of sending inline to its own socket.
That means every connected surface (mobile phones, React dashboard, Unity)
must receive brain-state frames regardless of which surface produced the turn.
These tests lock in that contract against the SessionManager singleton logic.
"""

import asyncio

from server.infrastructure.session_manager import SessionManager
from server.protocol import BrainState


class _FakeSocket:
    """Minimal stand-in for a FastAPI WebSocket — records sent payloads."""

    def __init__(self):
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


def test_broadcast_state_reaches_every_surface():
    """A state frame produced on one surface must hit sockets on all surfaces."""
    manager = SessionManager()
    phone_a = _FakeSocket()    # surfaces["mobile"]
    phone_b = _FakeSocket()    # surfaces["mobile"]
    dashboard = _FakeSocket()  # surfaces["dashboard"]
    unity = _FakeSocket()      # surfaces["main"]

    manager.add_surface("mobile", "user_default", phone_a)
    manager.add_surface("mobile", "user_default", phone_b)
    manager.add_surface("dashboard", "user_default", dashboard)
    manager.add_surface("main", "user_default", unity)

    asyncio.run(manager.broadcast_state(
        "user_default",
        BrainState(valence=-0.5, arousal=0.9, emotion="fear"),
    ))

    for socket in (phone_a, phone_b, dashboard, unity):
        assert len(socket.sent) == 1, "every surface must get exactly one frame"
        payload = socket.sent[0]
        assert payload["type"] == "state.update"
        assert payload["state"]["valence"] == -0.5
        assert payload["state"]["emotion"] == "fear"
        # datetime timestamp must be JSON-serialized (ISO string), not an object
        assert isinstance(payload["state"]["timestamp"], str)


def test_broadcast_state_is_scoped_to_user():
    """Frames for one user must never leak to another user's sockets."""
    manager = SessionManager()
    alice = _FakeSocket()
    bob = _FakeSocket()

    manager.add_surface("mobile", "alice", alice)
    manager.add_surface("mobile", "bob", bob)

    asyncio.run(manager.broadcast_state("alice", BrainState()))

    assert len(alice.sent) == 1
    assert bob.sent == []
