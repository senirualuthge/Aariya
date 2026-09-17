"""Tests for server/safety/filesystem_guard.py — path validation + dangerous
action classification, and swarm get_activations mapping."""

import os
import tempfile

import pytest

from server.safety import filesystem_guard as guard
from server.systems.synoptic_aggregator import SynopticAggregator


def test_is_dangerous():
    assert guard.is_dangerous("delete") is True
    assert guard.is_dangerous("read") is False


def test_validate_blocks_system_paths():
    assert guard.validate_path("/etc/passwd") is None
    assert guard.validate_path("/usr/bin/python3") is None
    assert guard.validate_path("") is None
    assert guard.validate_path(None) is None  # type: ignore


def test_validate_accepts_safe_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AARIYA_SAFE_DIRECTORIES", str(tmp_path))
    # SAFE_DIRECTORIES is computed at import time, so push the tmp root in
    # directly and restore it after.
    orig = list(guard.SAFE_DIRECTORIES)
    guard.SAFE_DIRECTORIES = [str(tmp_path.resolve())]
    try:
        target = tmp_path / "notes" / "a.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("hi")
        resolved = guard.validate_path(str(target))
        assert resolved is not None
        assert resolved == str(target.resolve())
    finally:
        guard.SAFE_DIRECTORIES = orig


def test_validate_require_exists(tmp_path):
    guard.SAFE_DIRECTORIES = [str(tmp_path.resolve())]
    try:
        assert guard.validate_path(str(tmp_path / "missing.txt"), require_exists=True) is None
    finally:
        pass


def test_aggregator_folds_agent_keys():
    agg = SynopticAggregator()
    # Feed the same frame repeatedly so the EMA converges.
    frame = {"planner": 0.9, "emotion_agent": 0.2, "vision_agent": 0.6}
    state = None
    for _ in range(40):
        state = agg.aggregate_synoptic(frame)
    assert state.domains["reasoning"] > 0.8  # type: ignore
    assert state.domains["perception"] > 0.5  # type: ignore
    assert state.domains["emotion"] > 0.1  # type: ignore


def test_aggregator_direct_domain_keys():
    agg = SynopticAggregator()
    state = None
    for _ in range(40):
        state = agg.aggregate_synoptic({"memory": 0.9})
    assert state.domains["memory"] > 0.8  # type: ignore
