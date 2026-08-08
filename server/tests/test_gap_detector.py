"""Tests for server/meta/gap_detector.py — the swarm capability spawner."""

import ast
from pathlib import Path

import pytest

from server.meta import gap_detector


@pytest.fixture()
def spawn_dir(tmp_path, monkeypatch):
    """Isolate generated-agent output into a throwaway dir and disable cooldown."""
    d = tmp_path / "generated"
    monkeypatch.setattr(gap_detector, "GENERATED_AGENTS_DIR", d)
    monkeypatch.setattr(gap_detector, "SPAWN_COOLDOWN_SECONDS", 0)
    gap_detector._spawned_at.clear()
    return d


@pytest.fixture()
def no_llm(monkeypatch):
    """Force the template path: simulate an unreachable LLM. (A local Ollama may
    otherwise be running in the dev environment and would make tests flaky.)"""
    def _unreachable():
        raise ConnectionError("no LLM in tests")
    monkeypatch.setattr(gap_detector, "_get_llm", _unreachable)


def _assert_valid_agent_file(path: Path, class_name: str, cap: str):
    """The written file must be parseable, define exactly one Agent subclass
    with an async `act`, and name-match the capability keywords used by
    scan_for_gaps() for ITS OWN capability."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    assert len(classes) == 1
    assert classes[0].name == class_name
    assert any(
        isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "act"
        for n in classes[0].body
    )
    # Capability keyword matching — the next scan_for_gaps() tick must see this
    # capability filled (a single agent only covers its own gap).
    assert cap not in gap_detector.scan_for_gaps([{"name": class_name}])


# ── scan_for_gaps (unchanged behavior) ───────────────────────────────────────

def test_scan_for_gaps():
    agents = [{"name": "EmotionAgent"}, {"name": "VisionAgent"}]
    missing = gap_detector.scan_for_gaps(agents)
    assert "dialogue" in missing
    assert "memory_retrieval" in missing
    assert "emotion_engine" not in missing
    assert "visual_tracking" not in missing


# ── template mode ─────────────────────────────────────────────────────────────

def test_trigger_spawner_writes_template_agent(spawn_dir, no_llm):
    result = gap_detector.trigger_spawner("memory_retrieval")
    assert result["ok"] is True
    assert result["method"] == "template"
    assert result["agent_name"] == "MemoryRetrievalAgent"

    path = Path(result["file"])
    assert path.exists()
    assert path.parent == spawn_dir
    _assert_valid_agent_file(path, "MemoryRetrievalAgent", "memory_retrieval")


def test_trigger_spawner_is_idempotent(spawn_dir, no_llm):
    first = gap_detector.trigger_spawner("dialogue")
    second = gap_detector.trigger_spawner("dialogue")

    assert first["ok"] is True
    assert first.get("skipped") is not True
    assert second["ok"] is True
    assert second["skipped"] is True
    assert len(list(spawn_dir.glob("*.py"))) == 1


def test_trigger_spawner_cooldown_blocks_rapid_respawns(monkeypatch, tmp_path, no_llm):
    # Cooldown active + the file gets removed between attempts → second call blocked.
    d = tmp_path / "generated"
    monkeypatch.setattr(gap_detector, "GENERATED_AGENTS_DIR", d)
    monkeypatch.setattr(gap_detector, "SPAWN_COOLDOWN_SECONDS", 600)
    gap_detector._spawned_at.clear()

    first = gap_detector.trigger_spawner("visual_tracking")
    assert first["ok"] is True

    Path(first["file"]).unlink()
    second = gap_detector.trigger_spawner("visual_tracking")
    assert second["ok"] is False
    assert second["error"] == "cooldown"


# ── LLM mode ──────────────────────────────────────────────────────────────────

def test_trigger_spawner_llm_mode(spawn_dir, monkeypatch):
    class FakeLLM:
        def chat_completion(self, messages, temperature=0.7, max_tokens=150):
            return (
                '```python\n'
                'from .base import Agent\n'
                '\n'
                'class SmartDialogueAgent(Agent):\n'
                '    def __init__(self):\n'
                '        super().__init__("dialogue")\n'
                '    async def act(self, state):\n'
                '        return {"agent": "dialogue", "context": "hi", "confidence": 0.9}\n'
                '```'
            )

    monkeypatch.setattr(gap_detector, "_get_llm", lambda: FakeLLM())

    result = gap_detector.trigger_spawner("dialogue")
    assert result["ok"] is True
    assert result["method"] == "llm"
    assert "SmartDialogueAgent" in Path(result["file"]).read_text(encoding="utf-8")


def test_trigger_spawner_llm_falls_back_on_garbage(spawn_dir, monkeypatch):
    class GarbageLLM:
        def chat_completion(self, messages, temperature=0.7, max_tokens=150):
            return "Sorry, I only speak haiku now."

    monkeypatch.setattr(gap_detector, "_get_llm", lambda: GarbageLLM())

    result = gap_detector.trigger_spawner("visual_tracking")
    assert result["ok"] is True
    assert result["method"] == "template"
    _assert_valid_agent_file(Path(result["file"]), "VisualTrackerAgent", "visual_tracking")


def test_trigger_spawner_llm_rejects_invalid_code(spawn_dir, monkeypatch):
    # Parses, but no Agent base / no act() → must fall back to the template.
    class BadLLM:
        def chat_completion(self, messages, temperature=0.7, max_tokens=150):
            return "def helper():\n    return 1\n"

    monkeypatch.setattr(gap_detector, "_get_llm", lambda: BadLLM())

    result = gap_detector.trigger_spawner("emotion_engine")
    assert result["ok"] is True
    assert result["method"] == "template"
    _assert_valid_agent_file(Path(result["file"]), "EmotionEngineAgent", "emotion_engine")


# ── edge cases ────────────────────────────────────────────────────────────────

def test_trigger_spawner_unknown_capability(spawn_dir, no_llm):
    result = gap_detector.trigger_spawner("quantum_analysis")
    assert result["ok"] is True
    assert result["method"] == "template"
    path = Path(result["file"])
    assert path.name == "quantum_analysis_agent.py"
    ast.parse(path.read_text(encoding="utf-8"))  # valid syntax
    assert "QuantumAnalysisAgent" in path.read_text(encoding="utf-8")


def test_trigger_spawner_invalid_capability(spawn_dir, no_llm):
    result = gap_detector.trigger_spawner("!!!")
    assert result["ok"] is False
    assert "invalid capability" in result["error"]
    assert list(spawn_dir.glob("*.py")) == []


# ── integration: the generated file is auto-discovered ────────────────────────

def test_generated_agent_is_discovered_by_scanner(tmp_path, monkeypatch, no_llm):
    """The whole premise: a spawned agent lands where the AgentScanner finds it
    (folder strategy needs an `agents/` path part — mirror the real layout)."""
    from server.infrastructure.agent_scanner import AgentScanner

    agents_dir = tmp_path / "server" / "systems" / "swarm" / "agents" / "generated"
    monkeypatch.setattr(gap_detector, "GENERATED_AGENTS_DIR", agents_dir)
    monkeypatch.setattr(gap_detector, "SPAWN_COOLDOWN_SECONDS", 0)
    gap_detector._spawned_at.clear()

    result = gap_detector.trigger_spawner("memory_retrieval")
    assert result["ok"] is True

    records = AgentScanner(root=tmp_path).scan()
    names = {r["name"] for r in records}
    assert "MemoryRetrievalAgent" in names

    rec = next(r for r in records if r["name"] == "MemoryRetrievalAgent")
    assert "folder" in rec["detection"]     # agents/ path part
    assert "inheritance" in rec["detection"]  # subclass of Agent
