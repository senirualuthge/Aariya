"""
RL long-horizon reward tests (Track E — partials plan).

Covers the durable transition log (E1), the n-step return (E2), the corpus
retrain cadence (E3) and the status surface (E4). Everything runs against real
SQLite rows and a redirected (tmp) checkpoint, so the developer's real
ppo_checkpoint.pt is never touched.

Run: python -m pytest server/tests/test_rl_longhorizon.py -v
"""

import json
import os

import pytest

import server.systems.rl.rl_policy as rl
from server.systems.rl.rl_policy import (
    ACTION_STYLE_MAP,
    PPOPolicy,
    _n_step_returns,
)
from server.systems.rl.store import get_transition_store


@pytest.fixture
def policy(tmp_path, monkeypatch, isolated_db):
    """A fresh policy whose checkpoint lives in tmp (never the real one)."""
    monkeypatch.setattr(rl, "MODEL_PATH", str(tmp_path / "ppo_test.pt"))
    return PPOPolicy()


def _ctx(valence=0.0, arousal=0.5, trust=0.5, contradiction=0.0, history_len=0):
    return {
        "valence": valence, "arousal": arousal, "trust": trust,
        "contradiction": contradiction, "history_len": history_len,
    }


# ── E1: durable transitions ──────────────────────────────────────────────────

def test_transitions_persist_and_replay(policy):
    store = get_transition_store()
    assert store.count() == 0

    for i in range(5):
        policy.select_style(_ctx(valence=0.1 * i))
        policy.observe_outcome(
            _ctx(valence=0.1 * i),
            _ctx(valence=0.1 * i + 0.2),
            meta={"user_id": "u1"},
        )

    assert store.count() == 5
    rows = store.recent(limit=10, user_id="u1")
    assert len(rows) == 5

    # read-back replays the identical encoded state vector
    first = rows[0]
    assert json.loads(first["state_json"]) == rl.encode_state(_ctx(valence=0.0)).tolist()
    assert json.loads(first["next_state_json"]) == rl.encode_state(_ctx(valence=0.2)).tolist()
    assert first["user_id"] == "u1"


def test_buffer_records_next_state_and_done(policy):
    policy.select_style(_ctx())
    policy.observe_outcome(_ctx(), _ctx(valence=0.4), meta={"user_id": "u1", "done": True})
    assert len(policy.buffer) == 1
    assert policy.buffer.dones == [True]
    assert policy.buffer.next_states[0] is not None


# ── E2: n-step returns ───────────────────────────────────────────────────────

def test_n_step_credits_delayed_reward():
    # reward only arrives at t=2, which is also terminal
    rewards = [0.0, 0.0, 10.0, 0.0]
    values = [0.0, 0.0, 0.0, 0.0]
    dones = [False, False, True, False]
    returns = _n_step_returns(rewards, values, dones, n_step=3, gamma=0.99)

    # t=0 sees the terminal reward two steps later → discounted credit
    assert returns[0].item() == pytest.approx(0.99 ** 2 * 10.0, rel=1e-4)
    # the credited earlier action beats the un-credited step after the terminal
    assert returns[0].item() > returns[3].item()


def test_n_step_bootstraps_from_value_at_horizon():
    rewards = [1.0, 1.0, 1.0, 1.0, 1.0]
    values = [0.0, 0.0, 9.9, 0.0, 0.0]
    dones = [False, False, False, False, False]
    returns = _n_step_returns(rewards, values, dones, n_step=2, gamma=0.99)

    # t=0: r0 + gamma*r1 + gamma^2 * V(s2)
    assert returns[0].item() == pytest.approx(
        1.0 + 0.99 * 1.0 + 0.99 ** 2 * 9.9, rel=1e-4
    )


# ── E3: corpus retrain cadence ───────────────────────────────────────────────

def test_corpus_retrain_respects_threshold_and_interval(policy):
    # fresh corpus → no retrain
    assert policy.maybe_retrain_from_corpus(
        min_new_transitions=3, min_interval_seconds=0) is False
    assert not os.path.exists(rl.MODEL_PATH)

    for i in range(5):
        policy.select_style(_ctx(valence=0.1 * i))
        policy.observe_outcome(
            _ctx(valence=0.1 * i), _ctx(valence=0.1 * i + 0.2), meta={"user_id": "u1"})

    # threshold crossed → retrain runs and writes a checkpoint
    assert policy.maybe_retrain_from_corpus(
        min_new_transitions=3, min_interval_seconds=0) is True
    assert os.path.exists(rl.MODEL_PATH)

    # interval guard blocks an immediate second pass
    assert policy.maybe_retrain_from_corpus(
        min_new_transitions=3, min_interval_seconds=3600) is False


# ── E4: status surface ───────────────────────────────────────────────────────

def test_status_reflects_reality(policy):
    status = policy.get_status()
    assert status["trained"] is False            # no checkpoint yet
    assert status["transitions"] == 0
    assert set(status["action_distribution"]) == set(ACTION_STYLE_MAP.values())

    policy.select_style(_ctx())
    policy.observe_outcome(_ctx(), _ctx(valence=0.3), meta={"user_id": "u1"})

    status2 = policy.get_status()
    assert status2["transitions"] == 1
    assert sum(status2["action_distribution"].values()) == 1
