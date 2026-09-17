"""Tests for the gap-fix modules:
- workflows/workflow_memory.py (doc *AccessFIles §5)
- agent/governor.py (AgentGovernor, doc *AccessFIles §8)
- agent/self_model.py (self-modeling, doc *AccessFIles §9)
- voice pipeline routing file commands to VoiceFileController
"""

import asyncio

import pytest

from server.systems.workflows.workflow_memory import WorkflowMemory
from server.systems.agent.governor import AgentGovernor, get_agent_governor
from server.systems.agent.self_model import SelfModel, get_self_model
from server.systems.filesystem.voice_file_controller import VoiceFileController


# ── WorkflowMemory ────────────────────────────────────────────────────────────

def test_workflow_save_load_roundtrip(tmp_path):
    w = WorkflowMemory(str(tmp_path / "wf.json"))
    steps = [{"open": "mail"}, {"open": "calendar"}, {"run": "git pull"}]
    assert w.save_workflow("daily startup", steps) is True
    assert w.load_workflow("daily startup") == steps


def test_workflow_load_unknown_returns_none(tmp_path):
    w = WorkflowMemory(str(tmp_path / "wf.json"))
    assert w.load_workflow("nope") is None


def test_workflow_delete(tmp_path):
    w = WorkflowMemory(str(tmp_path / "wf.json"))
    w.save_workflow("a", [{"x": 1}])
    assert w.delete_workflow("a") is True
    assert w.load_workflow("a") is None


def test_workflow_rejects_bad_input(tmp_path):
    w = WorkflowMemory(str(tmp_path / "wf.json"))
    assert w.save_workflow("", [{"x": 1}]) is False
    assert w.save_workflow("name", "not-a-list") is False  # type: ignore


# ── AgentGovernor ─────────────────────────────────────────────────────────────

def test_governor_delegates_by_keyword():
    g = AgentGovernor()
    assert g.delegate("search my files")["status"] == "unhandled"  # no agents yet

    g.register(_FakeAgent("filesystem_agent"))
    decision = g.delegate({"intent": "read_file", "path": "~/x"})
    assert decision["status"] == "delegated"
    assert decision["agent"] == "filesystem_agent"


def test_governor_unhandled_unknown_intent():
    g = AgentGovernor([_FakeAgent("research_agent")])
    assert g.delegate({"intent": "dance"})["status"] == "unhandled"


def test_governor_merge_results():
    g = AgentGovernor()
    merged = g.merge_results([
        {"items": [1, 2]},
        {"items": [3]},
        {"meta": {"a": 1}},
        {"meta": {"b": 2}},
    ])
    assert merged == {"items": [1, 2, 3], "meta": {"a": 1, "b": 2}}


def test_governor_execute_runs_agent():
    g = AgentGovernor([_FakeAgent("filesystem_agent")])
    result = asyncio.run(g.execute({"intent": "list"}))
    assert result["status"] == "ok"
    assert result["result"] == {"intent": "list"}


# ── Self-Modeling ─────────────────────────────────────────────────────────────

def test_self_model_capabilities():
    model = SelfModel()
    model.register_capability("access_files", True, 0.9)
    model.register_capability("control_browser", False, 0.2)
    s = model.summary()
    assert s["can_access_files"] is True
    assert s["can_control_browser"] is False
    assert s["confidence"] == pytest.approx(0.55, abs=0.01)


def test_self_model_verifier():
    model = SelfModel()
    model.register_capability("voice", True, 1.0, verifier=lambda: False)
    assert model.can("voice") is False
    assert model.confidence("voice") == 1.0


# ── VoiceFileController routing ───────────────────────────────────────────────

def test_voice_controller_recognizes_open_command():
    vc = VoiceFileController()
    result = asyncio.run(vc.process_command("open downloads"))
    assert result["status"] in ("ok", "denied")
    assert result["action"] == "open"


def test_voice_controller_not_understood():
    vc = VoiceFileController()
    result = asyncio.run(vc.process_command("tell me a joke"))
    assert result["status"] == "not_understood"


# ── Helpers ───────────────────────────────────────────────────────────────────

class _FakeAgent:
    def __init__(self, name):
        self.name = name

    async def act(self, state):
        return state
