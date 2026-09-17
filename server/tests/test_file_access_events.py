"""
File-access event feed tests — the real telemetry behind the GUI panel.

Covers:
  * access_events.tracked()      → start + end frames with honest status and
                                   measured duration for ok / denied / error
  * governor emissions           → write/append/delete/open/denial/rollback
                                   each emit one real end frame
  * no fabricated activity       → no file op ⇒ no frame ever emitted

The session broadcast is captured by monkeypatching `manager.broadcast`; the
frames' CONTENT must be real (actual paths, actual outcomes).
"""

import asyncio

import pytest


class _BroadcastRecorder:
    def __init__(self):
        self.frames = []

    async def __call__(self, message):
        self.frames.append(message)

    def of_type(self, type_name, phase=None):
        return [f for f in self.frames
                if f.get("type") == type_name
                and (phase is None or f.get("phase") == phase)]


@pytest.fixture()
def recorder(monkeypatch):
    rec = _BroadcastRecorder()
    from server.infrastructure import session_manager as sm_mod
    monkeypatch.setattr(sm_mod.manager, "broadcast", rec)
    return rec


def _drain():
    """Let scheduled create_task coroutines run."""
    loop = asyncio.new_event_loop()
    loop.run_until_complete(asyncio.sleep(0))
    loop.run_until_complete(asyncio.sleep(0))
    loop.close()


async def _pump():
    """Yield control twice inside the CURRENT loop so fire-and-forget
    broadcast tasks actually execute."""
    await asyncio.sleep(0)
    await asyncio.sleep(0)


# ── tracked() context manager ─────────────────────────────────────────────────

def test_tracked_emits_start_and_end_on_success(recorder):
    from server.systems.filesystem.access_events import tracked

    async def run():
        async with tracked("read_file", ["/tmp/a.txt"], actor="user"):
            await asyncio.sleep(0.01)

    asyncio.run(run())
    starts = recorder.of_type("file_access", "start")
    ends = recorder.of_type("file_access", "end")
    assert len(starts) == 1 and len(ends) == 1
    assert starts[0]["op"] == "read_file"
    assert starts[0]["paths"] == ["/tmp/a.txt"]
    assert starts[0]["id"] == ends[0]["id"]          # correlated pair
    assert ends[0]["status"] == "executed"
    assert ends[0]["duration_ms"] >= 5               # real measured time


def test_tracked_marks_denials_and_errors_honestly(recorder):
    from fastapi import HTTPException
    from server.systems.filesystem.access_events import tracked

    async def denied():
        async with tracked("read_file", ["/etc/passwd"]):
            raise HTTPException(status_code=403, detail="not allowed")

    async def broken():
        async with tracked("list_directory", ["/x"]):
            raise RuntimeError("disk exploded")

    with pytest.raises(HTTPException):
        asyncio.run(denied())
    with pytest.raises(RuntimeError):
        asyncio.run(broken())

    statuses = {f["paths"][0]: f["status"]
                for f in recorder.of_type("file_access", "end")}
    assert statuses["/etc/passwd"] == "denied"
    assert statuses["/x"] == "error"


# ── SafetyGovernor emissions (sync chokepoint) ────────────────────────────────

class _StubAgent:
    """Boundary stub: records calls, succeeds unless told to fail."""

    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def write_file(self, path, content, confirmed=False):
        self.calls.append(("write_file", path))
        return not self.fail

    def append_file(self, path, content, confirmed=False):
        self.calls.append(("append_file", path))
        return not self.fail

    def delete_file(self, path, confirmed=False):
        self.calls.append(("delete_file", path))
        if self.fail:
            raise PermissionError("locked")
        return True

    def open_path(self, path):
        self.calls.append(("open_path", path))
        return not self.fail


@pytest.fixture()
def governor(tmp_path, monkeypatch):
    from server.safety.governor import SafetyGovernor
    gov = SafetyGovernor(_StubAgent(),
                         journal_path=str(tmp_path / "audit.jsonl"))
    return gov


def test_governor_write_emits_real_frame(recorder, governor):
    target = "/tmp/hello.txt"

    async def run():
        assert governor.write_file(target, "hi", actor="user") is True
        await _pump()

    asyncio.run(run())
    frames = recorder.of_type("file_access")
    assert frames and frames[-1]["type"] == "file_access"
    end = frames[-1]
    assert end["op"] == "write_file"
    assert end["paths"] == [target]
    assert end["status"] == "executed"
    assert end["actor"] == "user"
    assert "2 bytes" in end["detail"]          # REAL byte count of "hi"


def test_governor_failure_emits_denied_frame(recorder, tmp_path):
    """Agent returns False (guard denial) → frame says 'denied'."""
    from server.safety.governor import SafetyGovernor
    gov = SafetyGovernor(_StubAgent(fail=True),
                         journal_path=str(tmp_path / "a.jsonl"))

    async def run():
        # write/append return False on refusal (never raise)
        assert gov.write_file("/tmp/no.txt", "x") is False
        assert gov.append_file("/tmp/no.txt", "x") is False
        await _pump()

    asyncio.run(run())
    ends = recorder.of_type("file_access", "end")
    denied = [f for f in ends if f["status"] == "denied"]
    assert {f["op"] for f in denied} >= {"write_file", "append_file"}


def test_governor_agent_exception_emits_error_frame(recorder, tmp_path):
    """An unexpected agent crash still emits an honest error frame, then
    propagates — telemetry must never swallow or lie about failures."""
    from server.safety.governor import SafetyGovernor

    class _CrashAgent(_StubAgent):
        def write_file(self, path, content, confirmed=False):
            raise PermissionError("disk on fire")

    gov = SafetyGovernor(_CrashAgent(),
                         journal_path=str(tmp_path / "c.jsonl"))

    async def run():
        with pytest.raises(PermissionError):
            gov.write_file("/tmp/boom.txt", "x")
        await _pump()

    asyncio.run(run())
    ends = recorder.of_type("file_access", "end")
    assert ends[-1]["status"] == "error"
    assert "disk on fire" in ends[-1]["detail"]


def test_governor_denial_recorded_as_event(recorder, governor):
    async def run():
        governor.record_denial("delete_file", "/tmp/x", "guard rejected")
        await _pump()

    asyncio.run(run())
    ends = recorder.of_type("file_access", "end")
    assert ends[-1]["status"] == "denied"
    assert ends[-1]["actor"] == "governor"
    assert "guard rejected" in ends[-1]["detail"]


def test_governor_rollback_lists_touched_paths(recorder, governor):
    async def run():
        governor.write_file("/tmp/f1.txt", "one")
        governor.write_file("/tmp/f2.txt", "two")
        result = governor.rollback(1)
        assert result["restored"] == 1
        await _pump()

    asyncio.run(run())
    rb = [f for f in recorder.of_type("file_access", "end")
          if f["op"] == "rollback"]
    assert rb, "no rollback frame emitted"
    assert rb[-1]["paths"] == ["/tmp/f2.txt"]   # newest-first undo
    assert rb[-1]["status"] == "executed"


def test_no_file_op_means_no_frames(recorder):
    _drain()
    assert recorder.frames == []


def test_notify_sync_without_loop_drops_frame_gracefully():
    from server.systems.filesystem.access_events import notify_sync
    # No running loop in this thread → must NOT raise, just drop.
    eid = notify_sync("read_file", ["/tmp/q"], status="executed")
    assert isinstance(eid, str) and eid


# ── Frame hygiene: real data only ─────────────────────────────────────────────

def test_frames_carry_no_mock_markers(recorder, governor):
    async def run():
        governor.write_file("/tmp/real.bin", "real bytes here")
        await _pump()

    asyncio.run(run())
    blob = repr(recorder.frames).lower()
    for bad in ("mock", "synthetic", "fake_", "dummy"):
        assert bad not in blob
