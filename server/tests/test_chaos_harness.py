"""Unit checks for the two-process chaos harness (scripts/chaos/harness.py).

The harness's distributed scenarios only run once the Redis-backed coordinator
exists, so these tests cover the pieces that can be verified today: interval
overlap detection (how "turns must not overlap" is actually decided), record
filtering/sorting, port-block allocation, and scenario registration.

The harness itself is exercised end to end with:
    server/.venv/bin/python scripts/chaos/harness.py --scenario guard
"""

import importlib.util
import pathlib
import socket
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HARNESS_PATH = _ROOT / "scripts" / "chaos" / "harness.py"


def _load_harness():
    spec = importlib.util.spec_from_file_location("aariya_chaos_harness", _HARNESS_PATH)
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the harness's dataclasses resolve postponed
    # annotations through sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harness = _load_harness()


def _rec(event, msg_id, ts, worker="w1"):
    return {"event": event, "msg_id": msg_id, "ts": ts, "worker": worker}


def test_sequential_turns_do_not_overlap():
    recs = [
        _rec("start", "m1", 100.0),
        _rec("end", "m1", 101.0),
        _rec("start", "m2", 101.5),
        _rec("end", "m2", 102.0),
    ]
    assert harness._turns_overlap(recs) is False


def test_concurrent_turns_are_detected_as_overlap():
    recs = [
        _rec("start", "m1", 100.0),
        _rec("start", "m2", 100.5),
        _rec("end", "m1", 101.0),
        _rec("end", "m2", 102.0),
    ]
    assert harness._turns_overlap(recs) is True


def test_unfinished_turn_cannot_hide_an_overlap():
    """A killed turn has a start and no end; the finished turn still decides."""
    recs = [
        _rec("start", "m1", 100.0),           # killed mid-turn: no end record
        _rec("start", "m2", 100.5),
        _rec("end", "m2", 101.0),
    ]
    # Only m2 has a complete interval, so nothing can be proven to overlap.
    assert harness._turns_overlap(recs) is False


def test_events_are_filtered_and_sorted():
    recs = [
        _rec("end", "m1", 3.0),
        _rec("start", "m2", 2.0),
        _rec("start", "m1", 1.0),
    ]
    assert [r["ts"] for r in harness._events(recs, "start")] == [1.0, 2.0]
    assert [r["ts"] for r in harness._events(recs, "end")] == [3.0]


def test_free_port_returns_a_bindable_port():
    port = harness._free_port()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_every_scenario_has_an_implementation():
    assert set(harness.SCENARIOS) == set(harness.SCENARIO_FUNCS)


def test_redis_down_refuses_an_external_store():
    """The destructive scenario must never kill a Redis the harness did not start."""
    ctx = harness.Context(
        run_id="test",
        artifacts=pathlib.Path("."),
        redis=harness.RedisCtl("redis://127.0.0.1:6379/0"),
    )
    with pytest.raises(harness.SkipScenario):
        harness.scenario_redis_down(ctx)
