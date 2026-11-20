"""Shared cognitive-session coordinator + cross-surface integration tests (Patch 1).

The coordinator exists so one person has ONE live BrainV2 no matter how many
surfaces are connected. These tests pin the properties that motivated it:

  * both WebSocket endpoints resolve to the same brain for the same user;
  * simultaneous phone + computer requests are serialized inside that brain
    (BrainV2 mutates live state while processing, so turns must not interleave);
  * a reconnect reuses the live cognitive session instead of building a new
    brain;
  * different users still get separate brains and may run concurrently.

The unit tests drive the coordinator directly in one event loop; the
end-to-end tests drive the real FastAPI app through TestClient with a
deterministic brain double (no LLM / swarm / network).
"""

import asyncio
import contextlib
import json
import queue
import threading
import time

import pytest
from fastapi.testclient import TestClient

from server import main as server_main
from server.protocol import BrainState, MultimodalInput, MultimodalOutput
from server.systems import cognitive_session_coordinator as cognitive_coordinator
from server.systems.cognitive_session_coordinator import (
    CognitiveSessionCoordinator,
    MultiWorkerRuntimeError,
    assert_single_worker,
    requested_worker_count,
)


class _TrackingBrain:
    """Deterministic BrainV2 double that records construction and overlap."""

    instances: list = []
    created_for: list = []
    turns: list = []
    events: list = []
    concurrent = 0
    max_concurrent = 0
    lock = threading.Lock()
    # Set by the first turn so the test knows processing really started.
    turn_started = threading.Event()
    # When set, every turn blocks here until the test releases it, which pins
    # a turn in flight while another socket sends.
    hold = None
    # When set, each turn's BrainState is labelled with the turn it came from,
    # so a test can prove WHICH turn's completed state frame it received.
    label_state = False

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.turn_count = 0
        self.state = BrainState(valence=0.2, arousal=0.5, emotion="calm")
        with _TrackingBrain.lock:
            _TrackingBrain.instances.append(self)
            _TrackingBrain.created_for.append(user_id)

    @classmethod
    def reset(cls) -> None:
        with cls.lock:
            cls.instances.clear()
            cls.created_for.clear()
            cls.turns.clear()
            cls.events.clear()
            cls.concurrent = 0
            cls.max_concurrent = 0
            cls.hold = None
            cls.label_state = False
        cls.turn_started.clear()

    async def process(self, input_model, on_token=None):
        text = input_model.text
        with _TrackingBrain.lock:
            _TrackingBrain.concurrent += 1
            _TrackingBrain.max_concurrent = max(
                _TrackingBrain.max_concurrent, _TrackingBrain.concurrent
            )
            _TrackingBrain.events.append(("start", text))
        _TrackingBrain.turn_started.set()
        try:
            # Optional gate: block this turn until the test releases it, so a
            # turn can be held in flight while another socket sends.
            gate = _TrackingBrain.hold
            if gate is not None:
                deadline = time.monotonic() + 5.0
                while not gate.is_set():
                    if time.monotonic() > deadline:
                        raise RuntimeError("test gate was never released")
                    await asyncio.sleep(0.01)
            # Hold the turn open long enough that a genuinely concurrent second
            # turn would overlap if the coordinator failed to serialize it.
            await asyncio.sleep(0.2)
            self.turn_count += 1
            with _TrackingBrain.lock:
                _TrackingBrain.turns.append((self.user_id, text))
                _TrackingBrain.events.append(("end", text))
            if _TrackingBrain.label_state:
                self.state = BrainState(
                    valence=round(0.1 * self.turn_count, 2),
                    arousal=0.5,
                    emotion=f"after:{text}",
                )
            return MultimodalOutput(
                text=f"reply to {input_model.text}",
                expression="calm",
                gestures=[],
                thought="a quiet thought",
                state_update=self.state,
            )
        finally:
            with _TrackingBrain.lock:
                _TrackingBrain.concurrent -= 1

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
    """Skip the heavyweight file-watch observer during lifespan startup."""

    def start(self, loop):
        pass

    def stop(self):
        pass


@pytest.fixture(autouse=True)
def _hermetic_backend(monkeypatch, isolated_db):
    """Install the brain double where brains are built, with a clean registry."""
    monkeypatch.setattr(cognitive_coordinator, "BrainV2", _TrackingBrain)
    monkeypatch.setattr(server_main, "get_daemon", lambda *a, **k: _NoopDaemon())
    monkeypatch.setattr(server_main, "get_watcher", lambda *a, **k: _NoopWatcher())
    cognitive_coordinator.cognitive_sessions._sessions.clear()
    _TrackingBrain.reset()
    yield
    cognitive_coordinator.cognitive_sessions._sessions.clear()


def _read_until(ws, want, timeout=15.0):
    """Drain frames until every type in ``want`` arrives, with a real deadline."""
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

    threading.Thread(target=_drain, daemon=True, name="drain-frames").start()

    try:
        kind, payload = result.get(timeout=timeout)
    except queue.Empty:
        pytest.fail(f"no {sorted(want)} frame within {timeout}s")
    if kind == "err":
        pytest.fail(f"receive failed: {payload}")
    return payload


# ── Coordinator unit behaviour ───────────────────────────────────────────────

def test_same_user_always_resolves_to_one_brain():
    async def scenario():
        coordinator = CognitiveSessionCoordinator()
        first = await coordinator.get_session("alice")
        second = await coordinator.get_session("alice")
        assert first is second
        assert first.brain is second.brain
        assert await coordinator.has_session("alice") is True
        assert await coordinator.has_session("bob") is False
        assert _TrackingBrain.created_for == ["alice"]

    asyncio.run(scenario())


def test_simultaneous_turns_for_one_user_are_serialized():
    async def scenario():
        coordinator = CognitiveSessionCoordinator()
        (out_a, state_a), (out_b, state_b) = await asyncio.gather(
            coordinator.process_turn("alice", MultimodalInput(text="phone")),
            coordinator.process_turn("alice", MultimodalInput(text="laptop")),
        )
        assert {out_a.text, out_b.text} == {"reply to phone", "reply to laptop"}
        assert state_a is state_b  # same live brain state, not two snapshots
        assert _TrackingBrain.created_for == ["alice"]
        assert _TrackingBrain.max_concurrent == 1, "turns for one user overlapped"
        assert len(_TrackingBrain.turns) == 2

    asyncio.run(scenario())


def test_different_users_get_separate_brains_and_run_concurrently():
    async def scenario():
        coordinator = CognitiveSessionCoordinator()
        await asyncio.gather(
            coordinator.process_turn("alice", MultimodalInput(text="a")),
            coordinator.process_turn("bob", MultimodalInput(text="b")),
        )
        assert _TrackingBrain.created_for == ["alice", "bob"]
        assert _TrackingBrain.max_concurrent == 2, "users block each other"

    asyncio.run(scenario())


def test_missing_user_id_is_rejected():
    with pytest.raises(ValueError):
        asyncio.run(CognitiveSessionCoordinator().get_session(""))


# ── Single-worker startup guard ─────────────────────────────────────────────

def test_worker_count_defaults_to_one():
    workers, source = requested_worker_count(environ={}, argv=[])
    assert (workers, source) == (1, None)
    assert_single_worker(environ={}, argv=[])  # must not raise


@pytest.mark.parametrize(
    "environ,argv,expected",
    [
        ({"WEB_CONCURRENCY": "4"}, [], (4, "WEB_CONCURRENCY=4")),
        ({"UVICORN_WORKERS": "2"}, [], (2, "UVICORN_WORKERS=2")),
        ({}, ["--workers", "3"], (3, "--workers 3")),
        ({}, ["--workers=5"], (5, "--workers=5")),
        ({}, ["-w", "2"], (2, "-w 2")),
        ({}, ["-w2"], (2, "-w2")),
        ({"WEB_CONCURRENCY": "1"}, ["--workers", "1"], (1, None)),
        ({"WEB_CONCURRENCY": "nonsense"}, [], (1, None)),
    ],
)
def test_worker_count_sources(environ, argv, expected):
    assert requested_worker_count(environ=environ, argv=argv) == expected


@pytest.mark.parametrize(
    "environ,argv",
    [
        ({"WEB_CONCURRENCY": "4"}, []),
        ({"UVICORN_WORKERS": "2"}, []),
        ({}, ["--workers", "3"]),
    ],
)
def test_multi_worker_configuration_refuses_to_start(environ, argv):
    with pytest.raises(MultiWorkerRuntimeError) as excinfo:
        assert_single_worker(environ=environ, argv=argv)
    assert "single-process" in str(excinfo.value)


def test_lifespan_aborts_boot_when_workers_requested(monkeypatch):
    """A real app boot under WEB_CONCURRENCY=4 must fail, not start split-brained."""
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    with pytest.raises(MultiWorkerRuntimeError):
        with TestClient(server_main.app):
            pass


# ── Idle-session eviction ────────────────────────────────────────────────────

def test_idle_session_is_evicted_and_recent_session_kept():
    async def scenario():
        coordinator = CognitiveSessionCoordinator()
        idle = await coordinator.get_session("alice")
        recent = await coordinator.get_session("bob")
        idle.last_used -= 10_000  # long idle

        assert await coordinator.evict_idle_sessions(idle_seconds=60) == ["alice"]
        assert await coordinator.has_session("alice") is False
        assert await coordinator.has_session("bob") is True
        # The kept session is the SAME live brain, not a rebuilt one.
        assert await coordinator.get_session("bob") is recent

    asyncio.run(scenario())


def test_a_turn_refreshes_last_used():
    async def scenario():
        coordinator = CognitiveSessionCoordinator()
        session = await coordinator.get_session("alice")
        session.last_used -= 10_000

        await coordinator.process_turn("alice", MultimodalInput(text="hi"))

        assert await coordinator.evict_idle_sessions(idle_seconds=60) == []
        assert await coordinator.has_session("alice") is True

    asyncio.run(scenario())


def test_session_with_turn_in_flight_is_never_evicted():
    async def scenario():
        coordinator = CognitiveSessionCoordinator()
        session = await coordinator.get_session("alice")
        session.last_used -= 10_000

        async with session.turn_lock:
            assert await coordinator.evict_idle_sessions(idle_seconds=60) == []
            assert await coordinator.has_session("alice") is True

    asyncio.run(scenario())


def test_stats_report_sessions_evictions_and_lock_waits():
    async def scenario():
        coordinator = CognitiveSessionCoordinator()
        assert coordinator.stats() == {
            "sessions": 0,
            "idle_evictions": 0,
            "lock_waits": 0,
            "lock_wait_seconds_total": 0.0,
            "users": [],
        }

        recent = await coordinator.get_session("alice")
        idle = await coordinator.get_session("bob")
        assert coordinator.stats()["sessions"] == 2

        # Two simultaneous turns for alice: the second queues on her lock.
        await asyncio.gather(
            coordinator.process_turn("alice", MultimodalInput(text="a")),
            coordinator.process_turn("alice", MultimodalInput(text="b")),
        )
        stats = coordinator.stats()
        assert stats["lock_waits"] >= 1
        assert stats["lock_wait_seconds_total"] > 0
        assert recent is not None

        idle.last_used -= 10_000
        assert await coordinator.evict_idle_sessions(idle_seconds=60) == ["bob"]
        stats = coordinator.stats()
        assert stats["idle_evictions"] == 1
        assert stats["sessions"] == 1

    asyncio.run(scenario())


def test_stats_expose_per_user_lock_state_and_waiters():
    async def scenario():
        coordinator = CognitiveSessionCoordinator()
        gate = threading.Event()
        _TrackingBrain.hold = gate
        _TrackingBrain.turn_started.clear()

        running = asyncio.create_task(
            coordinator.process_turn("alice", MultimodalInput(text="long"))
        )
        deadline = time.monotonic() + 5
        while not _TrackingBrain.turn_started.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.01)
        assert _TrackingBrain.turn_started.is_set(), "turn never started"

        row = coordinator.stats()["users"][0]
        assert row["user_id"] == "alice"
        assert row["turn_in_flight"] is True
        assert row["turn_elapsed_seconds"] is not None
        assert row["waiting_turns"] == 0
        assert row["idle_seconds"] >= 0

        queued = asyncio.create_task(
            coordinator.process_turn("alice", MultimodalInput(text="queued"))
        )
        deadline = time.monotonic() + 5
        while (
            coordinator.stats()["users"][0]["waiting_turns"] != 1
            and time.monotonic() < deadline
        ):
            await asyncio.sleep(0.01)
        assert coordinator.stats()["users"][0]["waiting_turns"] == 1

        gate.set()
        await asyncio.gather(running, queued)

        row = coordinator.stats()["users"][0]
        assert row["turn_in_flight"] is False
        assert row["waiting_turns"] == 0

    asyncio.run(scenario())


def test_eviction_loop_sweeps_until_cancelled():
    async def scenario():
        coordinator = CognitiveSessionCoordinator()
        session = await coordinator.get_session("alice")
        session.last_used -= 10_000

        task = asyncio.create_task(
            coordinator.eviction_loop(idle_seconds=60, interval_seconds=0.01)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert await coordinator.has_session("alice") is False

    asyncio.run(scenario())


# ── End-to-end: both WebSocket endpoints, one user ──────────────────────────

def test_phone_and_computer_simultaneous_turns_share_one_brain():
    """A phone turn and a laptop turn fired together must use ONE brain and
    must not execute inside it at the same time."""
    # Entered TestClient: both sockets run in ONE event loop, like the real
    # single-worker Uvicorn process this coordinator is written for.
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/mobile?user_id=alice") as phone, \
             client.websocket_connect("/ws/brain?user_id=alice") as laptop:

            # Fire both turns before reading either reply, so both handlers are
            # inside process_turn at once from the app's point of view.
            laptop.send_json({"text": "from laptop"})
            phone.send_json({"type": "input.multimodal", "content": "from phone"})

            phone_frames = _read_until(phone, {"ai_response", "state.update"})
            laptop_frames = _read_until(laptop, {"ai_response", "state.update"})

    assert _TrackingBrain.created_for == ["alice"], (
        f"expected one brain for alice, built {_TrackingBrain.created_for}"
    )
    assert _TrackingBrain.max_concurrent == 1, (
        "phone and computer turns mutated the same brain concurrently"
    )
    assert phone_frames["ai_response"]["text"] == "reply to from phone"
    assert laptop_frames["ai_response"]["text"] == "reply to from laptop"
    # Both surfaces saw the same brain state frame.
    assert phone_frames["state.update"]["state"] == laptop_frames["state.update"]["state"]


def test_reconnect_reuses_the_live_cognitive_session():
    """Closing and reopening a socket must not rebuild the brain."""
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/brain?user_id=carol") as first:
            first.send_json({"text": "first"})
            _read_until(first, {"ai_response", "state.update"})

        # Socket closed above — then the same person reconnects on another surface.
        with client.websocket_connect("/ws/mobile?user_id=carol") as second:
            second.send_json({"type": "input.multimodal", "content": "second"})
            frames = _read_until(second, {"ai_response", "state.update"})

    assert frames["ai_response"]["text"] == "reply to second"
    assert _TrackingBrain.created_for == ["carol"], (
        f"reconnect rebuilt the brain: {_TrackingBrain.created_for}"
    )
    brain = _TrackingBrain.instances[0]
    assert brain.turn_count == 2, "second turn did not run on the original brain"
    assert [text for _, text in _TrackingBrain.turns] == ["first", "second"]


def test_reconnect_message_queues_behind_in_flight_turn():
    """A turn arriving on a reconnected socket while the previous turn is still
    running must QUEUE behind it — same brain, no interleaved execution.

    Deterministic: the first turn is held open by a gate, the second socket
    sends during that hold, and we assert the second turn has not started
    before releasing the gate.
    """
    gate = threading.Event()
    _TrackingBrain.hold = gate

    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/brain?user_id=dana") as first:
            first.send_json({"text": "first"})
            assert _TrackingBrain.turn_started.wait(timeout=5), (
                "the first turn never started"
            )

            # The original socket is still mid-turn; the user reconnects on
            # another surface and speaks immediately.
            with client.websocket_connect("/ws/mobile?user_id=dana") as second:
                second.send_json({"type": "input.multimodal", "content": "second"})
                time.sleep(0.2)  # let the app receive and try to run this turn

                # QUEUED, not raced: the in-flight turn is untouched and the
                # reconnected turn has not entered the brain yet.
                assert ("start", "second") not in _TrackingBrain.events, (
                    "reconnected turn started inside the in-flight turn"
                )
                assert _TrackingBrain.max_concurrent == 1

                gate.set()  # release the held turn; the queued turn may now run
                frames = _read_until(second, {"ai_response", "state.update"})

    assert frames["ai_response"]["text"] == "reply to second"
    assert _TrackingBrain.created_for == ["dana"], (
        f"reconnect rebuilt the brain: {_TrackingBrain.created_for}"
    )
    # Strict ordering: the held turn fully finished before the queued one began.
    assert _TrackingBrain.events == [
        ("start", "first"),
        ("end", "first"),
        ("start", "second"),
        ("end", "second"),
    ]
    assert _TrackingBrain.instances[0].turn_count == 2


def test_dropped_socket_mid_turn_does_not_leak_the_turn_lock():
    """Closing the socket while a turn is still running must not leave the
    per-user turn lock held: the abandoned turn has to unwind and release it,
    otherwise every later turn for that user blocks forever.

    Deterministic: the turn is held open by a gate, the socket is dropped
    during that hold, and only then is the turn allowed to finish.
    """
    gate = threading.Event()
    _TrackingBrain.hold = gate
    user = "dana-drop"

    with TestClient(server_main.app) as client:
        first = client.websocket_connect(f"/ws/brain?user_id={user}")
        first.__enter__()
        try:
            first.send_json({"text": "slow"})
            assert _TrackingBrain.turn_started.wait(timeout=5), (
                "the turn never started"
            )

            # Drop the socket mid-turn. TestClient queues the disconnect; the
            # handler only observes it after the turn unwinds.
            first.close()
            time.sleep(0.2)

            session = cognitive_coordinator.cognitive_sessions._sessions[user]
            assert session.turn_lock.locked(), (
                "the turn was expected to still be in flight on a held lock"
            )

            gate.set()  # let the abandoned turn finish and unwind

            deadline = time.monotonic() + 5.0
            while (
                session.turn_lock.locked() or _TrackingBrain.concurrent
            ) and time.monotonic() < deadline:
                time.sleep(0.01)

            assert not session.turn_lock.locked(), (
                "turn lock leaked after the socket was dropped mid-turn"
            )
            assert _TrackingBrain.concurrent == 0
        finally:
            gate.set()
            with contextlib.suppress(Exception):
                first.__exit__(None, None, None)

        # A leaked lock would make this turn hang until the read deadline.
        with client.websocket_connect(f"/ws/mobile?user_id={user}") as second:
            second.send_json({"type": "input.multimodal", "content": "after-drop"})
            frames = _read_until(second, {"ai_response", "state.update"})

    assert frames["ai_response"]["text"] == "reply to after-drop"
    assert _TrackingBrain.created_for == [user], "dropped socket rebuilt the brain"
    assert _TrackingBrain.instances[0].turn_count == 2
    assert _TrackingBrain.max_concurrent == 1


def test_reconnect_during_in_flight_turn_receives_earlier_state_frame():
    """A surface that connects (or reconnects) WHILE a turn is in flight must
    still receive that earlier turn's completed `state.update` frame.

    The turn is held open by a gate; the second socket joins mid-turn and sends
    nothing, so any frame it receives can only be the first turn's completion.
    """
    gate = threading.Event()
    _TrackingBrain.hold = gate
    _TrackingBrain.label_state = True
    user = "erin-catchup"

    try:
        with TestClient(server_main.app) as client:
            with client.websocket_connect(f"/ws/brain?user_id={user}") as first:
                first.send_json({"text": "first"})
                assert _TrackingBrain.turn_started.wait(timeout=5), (
                    "the first turn never started"
                )

                # Reconnect mid-turn on another surface; it sends NOTHING.
                with client.websocket_connect(f"/ws/mobile?user_id={user}") as second:
                    gate.set()  # let the in-flight turn complete

                    _read_until(first, {"ai_response", "state.update"})
                    catchup = _read_until(second, {"state.update"})
    finally:
        gate.set()

    state = catchup["state.update"]["state"]
    assert state["emotion"] == "after:first", (
        f"reconnect missed the earlier turn's completed state: {state}"
    )
    assert state["valence"] == 0.1
    assert _TrackingBrain.created_for == [user]


def test_surfaces_for_different_users_do_not_share_a_brain():
    with TestClient(server_main.app) as client:
        with client.websocket_connect("/ws/mobile?user_id=alice") as phone, \
             client.websocket_connect("/ws/brain?user_id=bob") as laptop:
            phone.send_json({"type": "input.multimodal", "content": "from alice"})
            laptop.send_json({"text": "from bob"})
            _read_until(phone, {"ai_response", "state.update"})
            _read_until(laptop, {"ai_response", "state.update"})

    assert _TrackingBrain.created_for == ["alice", "bob"]
    assert _TrackingBrain.instances[0] is not _TrackingBrain.instances[1]
