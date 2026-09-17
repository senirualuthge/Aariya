"""Tests for server/systems/planner.py — the LLM hierarchical planning engine."""

import json

import pytest

from server.systems import planner


class _FakeLLM:
    """Synchronous chat_completion stub returning a canned response."""

    def __init__(self, response):
        self.response = response
        self.last_prompt = None

    def chat_completion(self, messages, temperature=0.7, max_tokens=150):
        self.last_prompt = messages[-1]["content"]
        return self.response


@pytest.fixture()
def no_llm(monkeypatch):
    """Force the fallback path (a real local Ollama may be running in dev)."""

    def _unreachable():
        raise ConnectionError("no LLM in tests")

    monkeypatch.setattr(planner, "_get_llm", _unreachable)


# ── LLM mode ──────────────────────────────────────────────────────────────────

def test_plan_llm_hierarchical_decomposition(monkeypatch):
    payload = {
        "steps": [
            {"task": "survey the literature", "parallel": False},
            {
                "task": "gather primary sources",
                "parallel": True,
                "subgoals": [
                    {"task": "web_search", "parallel": True},
                    {"task": "vault_review", "parallel": True},
                ],
            },
            {"task": "write synthesis", "parallel": False},
        ]
    }
    fake = _FakeLLM(json.dumps(payload))
    monkeypatch.setattr(planner, "_get_llm", lambda: fake)

    result = planner.plan("research quantum computing")
    assert result["strategy"] == "llm"
    assert result["goal"] == "research quantum computing"
    steps = result["steps"]
    assert len(steps) == 3
    assert steps[0] == {"task": "survey the literature", "parallel": False}
    assert steps[1]["parallel"] is True
    assert steps[1]["subgoals"][0] == {"task": "web_search", "parallel": True}
    # The LLM was actually asked for hierarchical decomposition.
    assert "subgoals" in fake.last_prompt  # type: ignore


def test_plan_llm_fenced_json(monkeypatch):
    fake = _FakeLLM('```json\n{"steps": [{"task": "do the thing", "parallel": true}]}\n```')
    monkeypatch.setattr(planner, "_get_llm", lambda: fake)

    result = planner.plan("do the thing")
    assert result["strategy"] == "llm"
    assert result["steps"] == [{"task": "do the thing", "parallel": True}]


def test_plan_sanitizes_invalid_llm_steps(monkeypatch):
    # Empty task dropped, over-long task dropped, non-dict dropped, junk dropped.
    payload = {
        "steps": [
            {"task": ""},
            {"task": "ok step"},
            "not-a-dict",
            {"task": "x" * 200},
            {"task": "good step", "parallel": True},
        ]
    }
    monkeypatch.setattr(planner, "_get_llm", lambda: _FakeLLM(json.dumps(payload)))

    result = planner.plan("anything")
    assert result["strategy"] == "llm"
    assert result["steps"] == [
        {"task": "ok step", "parallel": False},
        {"task": "good step", "parallel": True},
    ]


# ── Fallback mode ─────────────────────────────────────────────────────────────

def test_plan_falls_back_when_llm_unavailable(no_llm):
    r1 = planner.plan("build a new feature")
    r2 = planner.plan("build a new feature")

    assert r1["strategy"] == "fallback"
    assert r1 == r2  # deterministic — no RNG anywhere
    tasks = [s["task"] for s in r1["steps"]]
    assert "design_architecture" in tasks
    assert any("subgoals" in s for s in r1["steps"])  # still hierarchical


def test_plan_falls_back_on_garbage_llm(monkeypatch):
    monkeypatch.setattr(planner, "_get_llm", lambda: _FakeLLM("I only speak haiku now."))
    result = planner.plan("optimize system")
    assert result["strategy"] == "fallback"
    assert "identify_bottlenecks" in [s["task"] for s in result["steps"]]


def test_plan_falls_back_on_empty_steps_from_llm(monkeypatch):
    monkeypatch.setattr(planner, "_get_llm", lambda: _FakeLLM('{"steps": []}'))
    result = planner.plan("research anything")
    assert result["strategy"] == "fallback"
    assert "gather_sources" in [s["task"] for s in result["steps"]]


def test_plan_keeps_generic_stub_shape_for_unknown_goals(no_llm):
    result = planner.plan("mysterious vague desire")
    tasks = [s["task"] for s in result["steps"]]
    assert tasks == ["analyze_state", "select_agents", "simulate_paths", "execute_best_plan"]


# ── Goal normalization ────────────────────────────────────────────────────────

def test_plan_accepts_dict_goal(monkeypatch):
    fake = _FakeLLM('{"steps": [{"task": "a"}, {"task": "b"}]}')
    monkeypatch.setattr(planner, "_get_llm", lambda: fake)

    result = planner.plan({"description": "scale the service", "id": 1})  # type: ignore
    assert result["goal"] == "scale the service"


def test_plan_handles_empty_goal(no_llm):
    result = planner.plan("")
    assert result["goal"] == "general goal"
    assert result["steps"]


# ── score_plan ────────────────────────────────────────────────────────────────

def test_score_plan_is_deterministic_and_bounded():
    p = {"steps": [{"task": "a"}, {"task": "b"}]}
    assert planner.score_plan(p) == planner.score_plan(p)
    assert 0.0 <= planner.score_plan(p) <= 1.0


def test_score_plan_penalizes_longer_chains():
    short = {"steps": [{"task": "a"}, {"task": "b"}]}
    long = {"steps": [{"task": "a"}, {"task": "b"}, {"task": "c"}, {"task": "d"}]}
    assert planner.score_plan(short) > planner.score_plan(long)


def test_score_plan_rewards_parallelism():
    base = {"steps": [{"task": "a"}, {"task": "b"}, {"task": "c"}]}
    parallel = {"steps": [{"task": "a", "parallel": True}, {"task": "b"}, {"task": "c"}]}
    assert planner.score_plan(parallel) > planner.score_plan(base)


def test_score_plan_empty_returns_zero():
    assert planner.score_plan({"steps": []}) == 0.0
    assert planner.score_plan({}) == 0.0
