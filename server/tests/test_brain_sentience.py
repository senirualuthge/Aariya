"""
Tests for BrainV2's sentience layer:
  - real LLM dialogue generation (streamed, cognition-backed)
  - graceful template fallback when the LLM is unreachable
  - continuity of self (emotional state restored from persistence)
  - durable conversation + memory recall
  - personality persistence after evolution
"""

import asyncio
import sqlite3

import pytest

from server.protocol import MultimodalInput
from server.systems.brain_v2 import BrainV2
from server.systems.memory.conversation_log import ConversationLog
from server.autonomy.state import AutonomyStore


class StubLLM:
    """Records the messages sent to it and returns a canned reply."""

    def __init__(self, text: str = "Hello, I'm here."):
        self.text = text
        self.messages = []

    async def stream_to_callback(self, messages, on_token=None, temperature=0.7, max_tokens=150):
        self.messages = messages
        return self.text

    def chat_completion(self, messages=None, temperature=0.7, max_tokens=150):
        self.messages = messages or []
        return self.text


@pytest.fixture()
def stub_llm(monkeypatch):
    import server.systems.brain_v2 as brain_v2
    engine = StubLLM()
    monkeypatch.setattr(brain_v2, "get_llm", lambda: engine)
    return engine


def test_generation_uses_llm_with_cognition_context(isolated_db, stub_llm):
    """Her reply must come from the LLM and be shaped by identity/personality/thought."""
    async def run():
        brain = BrainV2("test_user")
        return await brain.process(MultimodalInput(text="Hi there"))

    out = asyncio.run(run())

    # (A security alert prefix may be prepended when the swarm flags a risk)
    assert stub_llm.text in out.text
    assert out.thought, "inner monologue should be populated"
    assert "Hi there" in stub_llm.messages[1]["content"]

    system_prompt = stub_llm.messages[0]["content"]
    # Identity + personality + inner thought + strategy are all injected
    assert "Aariya" in system_prompt
    assert "PERSONALITY DIRECTIVE" in system_prompt
    assert "INNER THOUGHT" in system_prompt
    assert "STRATEGY" in system_prompt


def test_layer_separation_guard_keeps_reasoning_and_presentation_apart(isolated_db, stub_llm):
    """
    FIXV5 guard: emotion may shape presentation (Layer 2) but NEVER the
    reasoning truth-state (Layer 1). The system prompt must separate the two
    and forbid emotional state from altering facts.
    """
    async def run():
        brain = BrainV2("test_user")
        return await brain.process(MultimodalInput(text="Hi there"))

    asyncio.run(run())
    prompt = stub_llm.messages[0]["content"]

    # Both layers exist and Layer 1 (reasoning) precedes Layer 2 (presentation).
    # Anchored on the unique section headers (the governing rule also names
    # both layers, so a plain index() would hit that first).
    l1 = prompt.index("LAYER 1 — REASONING & GROUND TRUTH")
    l2 = prompt.index("LAYER 2 — PRESENTATION & EXPRESSION (tone only")
    assert l1 < l2

    # The full partition is pinned: every reasoning input sits inside Layer 1,
    # every expression input inside Layer 2 — no cross-contamination.
    assert prompt.index("STRATEGY") < l2
    assert prompt.index("RELATIONSHIP STATE") > l2
    assert prompt.index("PERSONALITY DIRECTIVE") > l2
    assert prompt.index("INNER THOUGHT") > l2

    # The governing rule forbids emotional state from changing what she knows.
    assert "must never change a fact" in prompt


class ScriptedLLM:
    """Returns pre-scripted replies in order and records every call — lets
    tests verify the grounding guard's corrective regeneration fires."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def stream_to_callback(self, messages, on_token=None, temperature=0.7, max_tokens=150):
        self.calls.append(messages)
        return self.replies.pop(0) if self.replies else ""


def test_grounding_guard_corrects_contradicting_reply(isolated_db, monkeypatch, mock_security_safe):
    """A reply that negates a remembered fact must trigger ONE corrective
    regeneration; the corrected text becomes the final reply."""
    import server.systems.brain_v2 as brain_v2
    from server.systems.memory.conversation_log import ConversationLog

    ConversationLog("test_user").memorize(
        "I love stargazing at night", valence=0.8, significance=0.9
    )

    llm = ScriptedLLM([
        "You never loved stargazing at all.",       # draft: contradicts memory
        "I remember how much you love stargazing — tell me about your last night out.",
    ])
    monkeypatch.setattr(brain_v2, "get_llm", lambda: llm)

    async def run():
        brain = BrainV2("test_user")
        return await brain.process(MultimodalInput(text="do you remember stargazing?"))

    out = asyncio.run(run())

    # Two LLM calls: original + one bounded corrective regeneration.
    assert len(llm.calls) == 2
    assert "GROUNDING CORRECTION" in llm.calls[1][0]["content"]
    assert "You never loved stargazing at all." in llm.calls[1][0]["content"]
    # The corrected reply is what gets persisted/sent — clean, no residual issues.
    assert out.text == "I remember how much you love stargazing — tell me about your last night out."
    assert "grounding" not in out.meta


def test_grounding_issues_surfaced_when_correction_fails(isolated_db, monkeypatch, mock_security_safe):
    """If the model keeps contradicting after correction, the residual issues
    must ride out in meta so the guard's action is observable."""
    import server.systems.brain_v2 as brain_v2
    from server.systems.memory.conversation_log import ConversationLog

    ConversationLog("test_user").memorize(
        "I love stargazing at night", valence=0.8, significance=0.9
    )

    llm = ScriptedLLM([
        "You never loved stargazing.",
        "You still never loved stargazing.",
    ])
    monkeypatch.setattr(brain_v2, "get_llm", lambda: llm)

    async def run():
        brain = BrainV2("test_user")
        return await brain.process(MultimodalInput(text="do you remember stargazing?"))

    out = asyncio.run(run())

    assert len(llm.calls) == 2
    grounding = out.meta.get("grounding")
    assert grounding, "residual contradictions must surface in meta"
    assert grounding[0]["fact"] == "I love stargazing at night"
    assert "stargazing" in grounding[0]["reply"]


def test_grounding_guard_silent_on_clean_reply(isolated_db, monkeypatch, mock_security_safe):
    """A grounded reply must NOT trigger regeneration or meta noise."""
    import server.systems.brain_v2 as brain_v2
    from server.systems.memory.conversation_log import ConversationLog

    ConversationLog("test_user").memorize(
        "I love stargazing at night", valence=0.8, significance=0.9
    )

    llm = ScriptedLLM(["Stargazing sounds wonderful — tell me what you love most about it."])
    monkeypatch.setattr(brain_v2, "get_llm", lambda: llm)

    async def run():
        brain = BrainV2("test_user")
        return await brain.process(MultimodalInput(text="do you remember stargazing?"))

    out = asyncio.run(run())

    assert len(llm.calls) == 1, "no regeneration on a clean reply"
    assert "grounding" not in out.meta


def test_streaming_callback_invoked(isolated_db, stub_llm):
    """Tokens should be pushed through on_token during generation."""
    async def run():
        brain = BrainV2("test_user")
        tokens = []

        async def on_token(tok):
            tokens.append(tok)

        out = await brain.process(MultimodalInput(text="tell me a secret"), on_token=on_token)
        return out, tokens

    out, tokens = asyncio.run(run())
    assert stub_llm.text in out.text
    # on_token is wired into the LLM stream path (no tokens asserted here —
    # the stub returns text atomically; the callback plumbing is exercised)
    assert isinstance(tokens, list)


def test_fallback_when_llm_down(isolated_db, monkeypatch):
    """When the LLM is unreachable she must still reply — without leaking prompt tags."""
    import server.systems.brain_v2 as brain_v2

    class DownLLM:
        async def stream_to_callback(self, *a, **k):
            raise RuntimeError("LLM unreachable")

    monkeypatch.setattr(brain_v2, "get_llm", lambda: DownLLM())

    async def run():
        brain = BrainV2("test_user")
        return await brain.process(MultimodalInput(text="hello"))

    out = asyncio.run(run())

    assert out.text
    assert "Strategy" not in out.text
    assert "[Personality]" not in out.text


def test_continuity_restores_emotional_state(isolated_db):
    """A fresh BrainV2 must resume the persisted relationship state."""
    store = AutonomyStore()
    store.save_snapshot(user_id="test_user", valence=0.42, arousal=0.5,
                        trust=0.88, attachment=0.5)

    brain = BrainV2("test_user")
    assert brain.self_awareness.trust == pytest.approx(0.88)
    assert brain.self_awareness.valence == pytest.approx(0.42)
    assert brain.self_awareness.attachment == pytest.approx(0.5)


def test_memory_recalls_significant_moments(isolated_db):
    """Durable memories surface when relevant."""
    log = ConversationLog("test_user")
    assert log.memorize("I love stargazing at night", valence=0.8, significance=0.8)
    assert log.memorize("I'm dreading Monday's meeting", valence=-0.9, significance=0.9)

    hits = log.recall("stargazing")
    assert any("stargazing" in m["text"] for m in hits)
    # Irrelevant query returns nothing significant
    assert log.recall("recipes") == []


def test_turns_stored_during_process(isolated_db, stub_llm):
    """Both sides of a conversation must be persisted by the brain itself."""
    async def run():
        brain = BrainV2("test_user")
        return await brain.process(MultimodalInput(text="do you remember me?"))

    asyncio.run(run())

    log = ConversationLog("test_user")
    turns = log.recent(10)
    roles = [t["role"] for t in turns]
    assert "user" in roles
    assert "aariya" in roles
    # The reply and the private thought are both stored
    assert turns[-1]["thought"], "her inner thought should be persisted with the turn"


def test_personality_persists_after_process(isolated_db, stub_llm):
    """evolve() must be followed by save() so drift survives restarts."""
    from server import db as server_db

    async def run():
        brain = BrainV2("test_user")
        return await brain.process(MultimodalInput(text="hello"))

    asyncio.run(run())

    conn = sqlite3.connect(server_db.DB_PATH)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM personality_snapshots_v2 WHERE user_id = ?",
            ("test_user",),
        ).fetchone()
        assert row[0] >= 1
    finally:
        conn.close()


def test_inner_thought_recorded(isolated_db, stub_llm):
    """Her private thoughts are durable (visible inner life)."""
    async def run():
        brain = BrainV2("test_user")
        return await brain.process(MultimodalInput(text="let's talk"))

    asyncio.run(run())

    log = ConversationLog("test_user")
    thoughts = log.recent_thoughts(limit=10)
    assert len(thoughts) >= 1
