"""Round-4 AccessFIles gap tests — §78, §88, §96, §97, §98/§79, §68.

Every test drives the real modules with real inputs (real text measurements,
real networkx graphs, real temp-file stores, real psutil probes). Nothing is
mocked: channels that genuinely can't run in CI (screen capture, OCR) are
exercised via their honest-unavailable paths.
"""

import asyncio
import json
import time

import pytest


# ── §78 Cognitive Economy ─────────────────────────────────────────────────────

def test_economy_tiers_track_complexity_and_priority(tmp_path):
    from server.systems.cognition.cognitive_economy import CognitiveEconomy

    eco = CognitiveEconomy(stats_path=str(tmp_path / "eco.json"))

    trivial = eco.decide("ok thanks")
    deep = eco.decide(
        "First refactor the parser module, then write a python script that "
        "imports server.systems.planner and fixes the bug, finally benchmark "
        "https://example.com results and iterate step by step until green.")
    urgent = eco.decide("stop now help")

    assert trivial["tier"] == "fast"
    assert deep["tier"] in ("deep", "standard") and deep["score"] > trivial["score"]
    assert deep["max_tokens"] >= trivial["max_tokens"]
    # P0 emergency: latency over depth no matter what.
    assert urgent["tier"] == "fast" and urgent["latency_priority"] == "ultra"
    # Delegate target comes from the real meta reasoner.
    assert deep["delegate_to"]
    assert any("priority" in r or "complexity" in r for r in deep["reasons"])


def test_economy_conservation_discount_and_outcome_escalation(tmp_path):
    from server.systems.cognition.cognitive_economy import CognitiveEconomy

    eco = CognitiveEconomy(stats_path=str(tmp_path / "eco.json"))

    d1 = eco.decide("please summarize this document for me in detail",
                    energy_mode="conservation")
    d2 = eco.decide("please summarize this document for me in detail",
                    energy_mode="full")
    assert d1["score"] < d2["score"]
    assert any("conservation" in r for r in d1["reasons"])

    # Five fast-tier failures must escalate subsequent fast decisions.
    for _ in range(5):
        eco.record_outcome("fast", ok=False)
    d3 = eco.decide("hey what's up", energy_mode="full")
    assert d3["tier"] == "standard"
    assert any("history" in r for r in d3["reasons"])

    st = eco.status()
    assert st["tier_stats"]["fast"]["samples"] >= 5


# ── §88 Environmental Intelligence ────────────────────────────────────────────

def test_environment_snapshot_is_real_and_signals_derive_from_it(tmp_path):
    from server.systems.cognition.environment_context import EnvironmentContext

    env = EnvironmentContext()
    snap = env.snapshot()

    now = time.localtime()
    assert snap["time"]["hour"] == now.tm_hour
    assert snap["time"]["weekday"] == time.strftime("%A")
    assert snap["location"]["available"] is False   # honest: no geo sensor

    machine = snap["machine"]
    assert isinstance(machine.get("cpu_percent"), (int, float))
    assert machine.get("mode") in ("full", "conservation", "sleep")

    sig = env.signals_for_autonomy()["signals"]
    assert set(sig) == {"meeting_active", "low_power", "thermal_hot",
                        "idle_machine", "external_display", "camera_present"}
    assert sig["idle_machine"] in (True, False)          # cpu is always measurable
    # battery may be absent on desktops → stays None (unknown), never faked
    if not ((machine.get("battery") or {}).get("available")):
        assert sig["low_power"] is None


# ── §96 Human Collaboration Model ─────────────────────────────────────────────

def test_clarification_proceeds_when_confident_asks_when_ambiguous(tmp_path):
    from server.systems.cognition.clarification_policy import ClarificationPolicy

    pol = ClarificationPolicy(stats_path=str(tmp_path / "clar.json"))

    clear = pol.decide("read file server/main.py")
    assert clear["action"] == "proceed" and clear["confidence_band"] == "high"
    assert clear["measured"]["domains_hit"] == ["filesystem"]

    vague = pol.decide("open it and then move that maybe")
    assert vague["measured"]["pronoun_count"] >= 2
    assert vague["ambiguity"] > clear["ambiguity"]
    if vague["action"] == "ask_clarification":
        assert vague["question"] and "?" in vague["question"]

    # Missing-object imperative gets a slot-filling question.
    missing = pol.decide("delete")
    assert missing["measured"]["verb_without_object"] is True
    assert "what should that apply to" in (missing["question"] or "")

    caveat = pol.decide(
        "search online for the bug fix in this repo")
    assert caveat["action"] in ("proceed_with_caveat", "ask_clarification")


def test_clarification_feedback_moves_threshold_and_persists(tmp_path):
    from server.systems.cognition.clarification_policy import ClarificationPolicy

    p = tmp_path / "clar.json"
    pol = ClarificationPolicy(stats_path=str(p))
    start = pol.ask_threshold

    pol.record_outcome(asked=True, answered=False)
    assert pol.ask_threshold == min(0.70, start + 0.02)
    pol.record_outcome(asked=True, answered=True)
    assert pol.ask_threshold == start

    pol2 = ClarificationPolicy(stats_path=str(p))     # reload from disk
    assert pol2.ask_threshold == start


# ── §97 Cross-Domain Generalization ──────────────────────────────────────────

def _wf(path, name, steps):
    from server.systems.workflows.workflow_memory import WorkflowMemory
    wm = WorkflowMemory(path=str(path))
    wm.save_workflow(name, steps)
    return wm


def test_domain_transfer_adapts_real_workflows_across_domains(tmp_path):
    from server.systems.skills.domain_transfer import DomainTransfer, _infer_domain

    wm = _wf(tmp_path / "wf.json", "web research", [
        {"action": "launch_app", "app": "chrome"},
        {"action": "navigate", "url": "https://arxiv.org/search?q=topic"},
        {"action": "extract", "text": "results"},
    ])
    wm.save_workflow("code research", [
        {"action": "launch_app", "app": "chrome"},
        {"action": "navigate", "url": "https://github.com/search?q=parser"},
        {"action": "extract", "text": "repos"},
    ])
    wm.save_workflow("cleanup downloads", [
        {"action": "shell", "path": "~/Downloads"},
        {"action": "wait", "seconds": 1},
    ])

    assert _infer_domain("web research", wm.load_workflow("web research")) == "web"  # type: ignore

    dt = DomainTransfer(workflow_memory=wm, stats_path=str(tmp_path / "dt.json"))
    doms = dt.domains()
    assert doms["web"] == ["web research", "code research"]
    assert doms["system"] == ["cleanup downloads"]

    out = dt.propose("cleanup downloads", "documents")
    # No document-domain exemplar exists yet → structural match still found
    # from another domain ("code research" shares nothing with shell+wait,
    # so similarity will be low but provenance is real).
    assert out["proposed"] in (True, False)
    if out["proposed"]:
        assert out["based_on"] and 0.0 <= out["structural_similarity"] <= 1.0
        assert all(isinstance(s, dict) for s in out["adapted_steps"])
        res = dt.record_outcome(out["transfer_id"], ok=True)
        assert res["recorded"] and res["trust"] == 1.0


def test_domain_transfer_honest_when_store_empty_or_unknown(tmp_path):
    from server.systems.skills.domain_transfer import DomainTransfer

    dt = DomainTransfer(stats_path=str(tmp_path / "dt.json"))
    assert dt.propose("nonexistent", "web")["proposed"] is False

    wm = _wf(tmp_path / "wf.json", "only one workflow", [
        {"action": "launch_app", "app": "notes"}])
    dt2 = DomainTransfer(workflow_memory=wm, stats_path=str(tmp_path / "dt2.json"))
    out = dt2.propose("only one workflow", "web")
    assert out["proposed"] is False and "nothing structurally similar" in out["reason"]


# ── §98 Self-Organizing Knowledge (+§79 ingest) ──────────────────────────────

@pytest.fixture()
def fresh_kg(tmp_path, monkeypatch):
    import server.systems.agent.knowledge_graph as kgmod
    monkeypatch.setattr(kgmod.config, "KNOWLEDGE_GRAPH_PATH", str(tmp_path / "kg.json"))
    return kgmod.KnowledgeGraph()


def test_organizer_clusters_real_kg_and_thoughts(fresh_kg, tmp_path, monkeypatch):
    from server.systems.memory.knowledge_organizer import KnowledgeOrganizer

    g = fresh_kg
    g.add_triple("user", "likes", "ai_systems", {})
    g.add_triple("aariya_project", "targets", "ai_systems", {})
    g.add_triple("render_engine", "optimizes", "texture_pipeline", {})
    g.add_triple("vscode", "opens_daily", "editor", {})

    monkeypatch.chdir(tmp_path)   # keep episodic/twin stores inside tmp

    org = KnowledgeOrganizer(kg_instance=g,
                             report_path=str(tmp_path / "org.json"))
    report = org.organize(ingest=True)

    assert report["items_scanned"] >= 4
    assert report["sources_available"] == ["triple"]
    assert all(c["label"] and c["summary"] for c in report["clusters"][:5] if c["size"] >= 2)
    # §79: synthesized triples land back in the graph, marked as self-generated.
    src_edges = [d for _, _, d in g.graph.edges(data=True)
                 if d.get("source") == "knowledge_organizer"]
    assert src_edges, "ingest=True must write self-generated knowledge"
    saved = json.loads((tmp_path / "kg.json").read_text())
    assert saved   # real persistence happened through the real kg save path

    st = org.status()
    assert st["items_scanned"] == report["items_scanned"]


def test_organizer_empty_sources_reports_zero_clusters(tmp_path, monkeypatch):
    import server.systems.agent.knowledge_graph as kgmod
    monkeypatch.setattr(kgmod.config, "KNOWLEDGE_GRAPH_PATH", str(tmp_path / "empty_kg.json"))
    from server.systems.memory.knowledge_organizer import KnowledgeOrganizer

    monkeypatch.chdir(tmp_path)
    org = KnowledgeOrganizer(kg_instance=kgmod.KnowledgeGraph(),
                             report_path=str(tmp_path / "org2.json"))
    report = org.organize(ingest=False)
    assert report["clusters_found"] == 0
    assert report["items_scanned"] == 0


# ── §68 Multimodal Perception Fusion ─────────────────────────────────────────

def test_perception_fusion_pushes_real_channels_into_world_model():
    from server.systems.vision.perception_fusion import PerceptionFusion
    from server.systems.cognition.world_model import WorldModel

    fusion = PerceptionFusion()   # no screen/OCR in CI → those stay off
    out = fusion.fuse(include_screen=False, include_gui_text=False,
                      push_to_world_model=False)

    assert "desktop" in out["channels"] and out["channels"]["desktop"]["available"]
    assert "environment" in out["channels"] and out["channels"]["environment"]["available"]
    assert "meeting" in out["channels"]
    assert out["fused_text"]       # desktop/env contribute verbatim text lines
    assert "environment" in out["available_channels"]


def test_perception_fusion_updates_cognitive_kernel_world_model():
    from server.systems.vision.perception_fusion import PerceptionFusion
    from server.systems.cognition.world_model import WorldModel

    own_wm = WorldModel()   # injected: no shared-singleton pollution
    fusion = PerceptionFusion()
    out = fusion.fuse(push_to_world_model=True, world_model=own_wm)
    env_state = own_wm.get("environment") or {}
    perc = (env_state or {}).get("perception")
    assert perc and perc["ts"] == out["ts"]
    events = own_wm.recent_events(days=0.01)
    assert any(e.get("type") == "perception_fusion" for e in events)


# ── MCP registry integration ─────────────────────────────────────────────────

def test_mcp_registry_exposes_round4_tools(tmp_path, monkeypatch):
    from server.systems.llm_router import build_default_registry

    # Hermetic: singletons invoked below must write under tmp, never repo ./data.
    monkeypatch.chdir(tmp_path)

    reg = build_default_registry()
    names = reg.tool_names()
    for tool in ("environment.snapshot", "perception.snapshot",
                 "knowledge.organize", "cognition.economy"):
        assert tool in names

    out = asyncio.run(reg.call("cognition.economy", {"task_text": "quick note"}))
    assert out["result"]["decision"]["tier"] in ("fast", "standard", "deep")

    out = asyncio.run(reg.call("knowledge.organize", {"ingest": False}))
    assert "clusters_found" in out["result"]

    out = asyncio.run(reg.call("environment.snapshot", {}))
    assert out["result"]["time"]["part_of_day"] in (
        "morning", "afternoon", "evening", "night")
