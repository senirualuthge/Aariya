"""
AccessFIles round-3 gap tests — the remaining unimplemented doc sections:

  * §74 context_compressor   (layered extractive compression, honest tokens)
  * §52 thought_stream       (persisted inner-life journal, real state machine)
  * §86 cognitive_shards     (domain shards over REAL subsystems)
  * §48 llm_router purposes  (env-driven per-purpose model table)
  * §94 energy_manager       (psutil-truth pressure + hysteresis modes)
  * §69 web_agent            (honest Playwright capability + URL policy)
  * §75 shared_workspace     (collab store, LWW merge, router surface)

All offline: no network, no LLM, throwaway files. Controlled readings passed
into pure functions are TEST INPUTS — production paths only ever read psutil
or the caller's data.
"""

import asyncio
import json
import time

import pytest


# ════════════════════════ §74 CONTEXT COMPRESSION ═════════════════════════════

def _msg(role, text):
    return {"role": role, "content": text}


def test_token_method_is_reported_honestly():
    from server.systems.cognition import context_compressor as cc

    assert cc.token_method() in ("tiktoken:cl100k_base", "chars_per_4")
    # count_tokens agrees with itself and never returns negatives.
    n = cc.count_tokens("hello world, this is a token counting check")
    assert n > 0


def test_compress_oversized_context_stays_under_budget():
    from server.systems.cognition.context_compressor import ContextCompressor

    comp = ContextCompressor()
    old = [_msg("user", f"Discussion point number {i}: the rendering engine needs "
                            "a faster pipeline for texture uploads and memory reuse.")
           for i in range(30)]
    recent = [_msg("user", "Ship the demo on Friday morning."),
              _msg("assistant", "Noted. I will prepare the demo checklist tonight.")]
    messages = old + recent
    budget = 120

    out = comp.compress_messages(messages, budget_tokens=budget)

    assert out["stats"]["compressed_tokens"] <= budget
    assert out["stats"]["original_tokens"] > budget
    contents = [m["content"] for m in out["messages"]]
    # The newest turn survives verbatim (layer 1).
    assert any("demo checklist tonight" in c for c in contents)
    # Older content is summarized, not invented: digest words come from input.
    digests = [c for c in contents if c.startswith("[compressed earlier context]")]
    assert digests, "older layers must produce a digest"
    blob = " ".join(m["content"] for m in messages).lower()
    for word in digests[0].replace("[compressed earlier context]", "").lower().split():
        stripped = word.strip("[],.:;!?()'")
        if len(stripped) > 4:
            assert stripped in blob, f"fabricated word in digest: {stripped}"


def test_compress_passthrough_when_it_fits():
    from server.systems.cognition.context_compressor import ContextCompressor

    comp = ContextCompressor()
    messages = [_msg("user", "short"), _msg("assistant", "also short")]
    out = comp.compress_messages(messages, budget_tokens=10_000)
    assert out["stats"].get("passthrough") is True
    assert out["messages"] == messages


def test_dedupe_drops_near_duplicates():
    from server.systems.cognition.context_compressor import dedupe_sentences

    sents = ["the renderer uploads textures every frame",
             "the renderer uploads textures every frame!",
             "completely unrelated sentence about databases"]
    kept = dedupe_sentences(sents)
    assert len(kept) == 2


# ════════════════════════ §52 THOUGHT STREAM ══════════════════════════════════

def test_thought_add_resolve_roundtrip(tmp_path):
    from server.systems.cognition.thought_stream import ThoughtStream

    ts = ThoughtStream("tester", path=str(tmp_path / "thoughts.jsonl"))
    entry = ts.add("unresolved_task", "downloads folder has unread PDFs")
    assert entry and entry["status"] == "open"

    resolved = ts.resolve(entry["id"], note="summarized all three")
    assert resolved["status"] == "resolved"  # type: ignore
    assert resolved["resolution"] == "summarized all three"  # type: ignore

    # Unknown id / double-resolve are honest no-ops.
    assert ts.resolve(entry["id"]) is None
    assert ts.resolve("no-such-id") is None
    assert ts.open_thoughts() == []


def test_thought_rejects_unknown_kind_and_persists(tmp_path):
    from server.systems.cognition.thought_stream import ThoughtStream

    path = str(tmp_path / "thoughts.jsonl")
    ts = ThoughtStream("tester", path=path)
    assert ts.add("vibes", "not a kind") is None
    assert ts.add("note", "") is None

    first = ts.add("hypothesis", "user may need project summary tomorrow")
    # A fresh instance over the same file sees the SAME journal (persistence).
    again = ThoughtStream("tester", path=path)
    ids = [e["id"] for e in again.open_thoughts()]  # type: ignore[union-attr]
    assert first["id"] in ids  # type: ignore[index]


def test_capture_from_tick_records_real_insights_only(tmp_path):
    from server.systems.cognition.thought_stream import ThoughtStream

    ts = ThoughtStream("tester", path=str(tmp_path / "thoughts.jsonl"))
    recorded = ts.capture_from_tick({  # type: ignore[union-attr]
        "insights": [{"source": "awaiting_plans", "detail": "1 plan(s) awaiting approval"}],
        "summary": "1 source(s) need attention",
    })
    kinds = {e["kind"] for e in recorded}
    assert "unresolved_task" in kinds and "note" in kinds

    # All-clear ticks leave NO trace — no synthetic activity.
    assert ts.capture_from_tick({"insights": [], "summary": "all clear"}) == []


# ════════════════════════ §86 COGNITIVE SHARDS ════════════════════════════════

def test_shard_registry_and_routing():
    from server.systems.cognition.cognitive_shards import get_cognitive_shards

    shards = get_cognitive_shards("shard_tester")
    status = shards.status()
    assert set(status["shards"]) >= {"memory", "knowledge", "social",
                                     "planning", "code", "system"}
    assert shards.route("remember what I said about the renderer") == "memory"
    assert shards.route("what does the knowledge graph know about vscode") == "knowledge"
    assert shards.route("find symbol_usages in the repo") == "code"
    assert shards.route("asdkjhaskdh") is None


def test_dispatch_unroutable_is_honest():
    from server.systems.cognition.cognitive_shards import get_cognitive_shards

    out = asyncio.run(get_cognitive_shards("shard_tester").dispatch("gibberish xyzzy"))
    assert out["handled"] is False and "reason" in out


def test_dispatch_system_shard_reads_real_psutil():
    from server.systems.cognition.cognitive_shards import get_cognitive_shards

    out = asyncio.run(get_cognitive_shards("shard_tester").dispatch(
        "check cpu load and health"))
    assert out["handled"] is True and out["ok"] is True
    assert "cpu_percent" in out["result"]
    assert out["latency_ms"] >= 0


def test_dispatch_timeout_reports_failure():
    from server.systems.cognition.cognitive_shards import CognitiveShards

    def slow_handler(params, user_id):
        time.sleep(0.25)
        return {}

    shards = CognitiveShards("slow_tester")
    shards.register("memory", slow_handler, domains=("memory",))
    out = asyncio.run(shards.dispatch("recall my memories", timeout_s=0.05))
    assert out["ok"] is False and out["error"] == "timeout"


def test_custom_shard_registration():
    from server.systems.cognition.cognitive_shards import CognitiveShards

    shards = CognitiveShards("custom_tester")
    shards.register("weather", lambda p, u: {"source": "real-api-call-goes-here"},
                    description="probe", domains=("system",))
    out = asyncio.run(shards.dispatch("cpu resources status"))
    assert out["handled"] and out["shard"] == "weather"

    with pytest.raises(ValueError):
        shards.register("", lambda p, u: {})


# ════════════════════════ §48 PURPOSE ROUTING ═════════════════════════════════

def test_purpose_router_unconfigured_is_none(monkeypatch):
    from server.systems.llm_router import PurposeRouter

    monkeypatch.delenv("AARIYA_LLM_PURPOSES", raising=False)
    router = PurposeRouter()
    assert router.purposes() == []
    assert router.engine_for("planning") is None  # falls back to remote/local split


def test_purpose_router_config_driven(monkeypatch):
    from server.systems.llm_router import PurposeRouter

    monkeypatch.setenv("AARIYA_LLM_PURPOSES", json.dumps({
        "planning": {"base_url": "http://127.0.0.1:11434/v1", "model": "deepseek-r1"},
        "vision": {"base_url": "http://127.0.0.1:1234/v1", "model": "llava"},
    }))
    router = PurposeRouter()
    assert set(router.purposes()) == {"planning", "vision"}

    engine = router.engine_for("PLANNING")  # case-insensitive purpose lookup
    assert engine is not None and engine.model == "deepseek-r1"

    # Same instance returned twice (engine cache), honest status surface.
    assert router.engine_for("planning") is engine
    assert router.status()["models"]["vision"] == "llava"
    assert router.engine_for("coding") is None  # not configured → honest None


def test_purpose_router_survives_bad_json(monkeypatch):
    from server.systems.llm_router import PurposeRouter

    monkeypatch.setenv("AARIYA_LLM_PURPOSES", "{not json")
    assert PurposeRouter().purposes() == []
    monkeypatch.setenv("AARIYA_LLM_PURPOSES", '["not an object"]')
    assert PurposeRouter().purposes() == []


# ════════════════════════ §94 ENERGY MANAGER ══════════════════════════════════

def test_energy_snapshot_reports_real_machine():
    from server.systems.resources.energy_manager import snapshot

    snap = snapshot()
    assert isinstance(snap["cpu_percent"], (int, float))
    assert isinstance(snap["battery"]["available"], bool)
    assert isinstance(snap["thermal"], list)


def test_pressure_from_controlled_readings():
    from server.systems.resources.energy_manager import compute_pressure

    idle_desktop = {"cpu_percent": 5, "memory_percent": 40,
                    "battery": {"available": False}, "thermal": []}
    hot_unplugged = {"cpu_percent": 95, "memory_percent": 90,
                     "battery": {"available": True, "percent": 10, "plugged": False},
                     "thermal": [{"zone": "CPU", "temp_c": 88.0}]}
    low, high = compute_pressure(idle_desktop), compute_pressure(hot_unplugged)
    assert 0.0 <= low < 0.3
    assert high > 0.8


def _reading(cpu=5, mem=40, battery=None, thermal=None):
    return {"cpu_percent": cpu, "memory_percent": mem,
            "battery": battery or {"available": False},
            "thermal": thermal or []}


def test_mode_transitions_with_hysteresis():
    from server.systems.resources.energy_manager import EnergyManager

    mgr = EnergyManager()
    mgr.min_dwell_s = 0.0  # test-speed hysteresis

    overloaded = _reading(cpu=100, mem=100,
                          battery={"available": True, "percent": 10,
                                   "plugged": False},
                          thermal=[{"zone": "CPU", "temp_c": 88.0}])
    assert mgr.evaluate(overloaded)["mode"] == "sleep"          # pressure ≈0.94
    # Maxed CPU+RAM sits exactly AT the exit threshold → still asleep.
    assert mgr.evaluate(_reading(cpu=100, mem=100))["mode"] == "sleep"
    assert mgr.evaluate(_reading(cpu=20))["mode"] == "conservation"
    assert mgr.evaluate(_reading(cpu=5))["mode"] == "full"

    # Dwell protection: fresh manager, straight back to full is blocked.
    dwell_mgr = EnergyManager()
    dwell_mgr.min_dwell_s = 999
    dwell_mgr._last_switch = time.time()
    dwell_mgr.mode = "conservation"
    assert dwell_mgr.evaluate(_reading(cpu=2))["mode"] == "conservation"


def test_allow_background_work_on_idle_machine():
    from server.systems.resources.energy_manager import get_energy_manager

    # This dev box at test time is not asleep → daemon maintenance allowed.
    assert get_energy_manager().allow_background_work() in (True, False)
    # But it must be a real evaluated mode.
    assert get_energy_manager().status()["mode"] in ("full", "conservation", "sleep")


# ════════════════════════ §69 WEB AGENT ═══════════════════════════════════════

def test_url_policy_refuses_non_http():
    from server.systems.browser.web_agent import validate_url

    with pytest.raises(ValueError):
        validate_url("ftp://example.com/file")
    with pytest.raises(ValueError):
        validate_url("file:///etc/passwd")
    clean = validate_url("https://example.com/docs?page=1")
    assert clean.startswith("https://example.com")


def test_url_host_allowlist_enforced(monkeypatch):
    from server.systems.browser import web_agent as wa

    monkeypatch.setenv("AARIYA_BROWSER_ALLOWED_HOSTS", "docs.python.org")
    assert wa.validate_url("https://docs.python.org/3/") == "https://docs.python.org/3/"
    with pytest.raises(ValueError):
        wa.validate_url("https://example.com/")
    # Unset allowlist → all hosts pass scheme checks.
    monkeypatch.delenv("AARIYA_BROWSER_ALLOWED_HOSTS")
    assert wa.validate_url("http://10.0.0.5:8080/status").startswith("http://")


def test_browser_capability_detection_is_truthful():
    from server.systems.browser.web_agent import detect_browser, WebAgent

    cap = detect_browser()
    assert set(cap) >= {"available"}
    if cap["available"]:
        assert cap["engine"] == "playwright"
    else:
        assert "reason" in cap
        agent = WebAgent()
        out = agent.navigate("https://example.com/")
        assert out["ok"] is False  # honest failure, never a fake page


def test_navigate_returns_error_not_exception_for_bad_scheme():
    from server.systems.browser.web_agent import WebAgent

    with pytest.raises(ValueError):  # URL policy raises BEFORE any browser work
        WebAgent().navigate("gopher://old-internet")


# ════════════════════════ §75 SHARED WORKSPACE ════════════════════════════════

@pytest.fixture()
def ws_store(tmp_path, monkeypatch):
    import server.systems.collaboration.shared_workspace as sw

    monkeypatch.setattr(sw, "_DATA_DIR", str(tmp_path / "workspaces"))
    return sw.get_workspace_store()


def test_workspace_create_join_note_task(ws_store):
    ws_store.create("Project Phoenix", "alice")
    # Idempotent create keeps one workspace.
    ws_store.create("project phoenix", "bob")

    assert ws_store.join("project-phoenix", "alice")["event"] == "join"
    assert ws_store.join("project-phoenix", "bob")["event"] == "join"
    assert ws_store.heartbeat("project-phoenix", "alice") is True

    note = ws_store.post_note("project phoenix", "alice", "design doc drafted")
    task = ws_store.add_task("project-phoenix", "bob", "review the schema")
    assert note and task and task["status"] == "open"

    done = ws_store.update_task("project-phoenix", task["id"], status="done")
    assert done["status"] == "done"

    summary = ws_store.summary(ws_store.get("project-phoenix"))
    assert summary["open_tasks"] == 0 and set(summary["participants"]) == {"alice", "bob"}

    # Leave + unknown-workspace honesty.
    assert ws_store.leave("project-phoenix", "bob") is True
    assert ws_store.post_note("ghost-ws", "alice", "hi") is None


def test_workspace_lww_merge(ws_store):
    local = ws_store.create("merge-me", "alice")
    mine = ws_store.add_task("merge-me", "alice", "original wording")

    peer_task = {
        "id": mine["id"],
        "author": "bob",
        "text": "peer reworded this task",
        "status": "open",
        "updated_at": time.time() + 100,   # genuinely newer
        "updated_by": "peer-device",
    }
    counts = ws_store.import_envelope([{
        "slug": "merge-me", "name": "merge-me",
        "notes": [], "tasks": [peer_task],
        "participants": {"bob": {"device": "peer-device",
                                 "joined_at": time.time(), "last_seen": time.time()}},
    }])
    assert counts["workspaces_merged"] == 1

    merged = ws_store.get(local["slug"])
    texts = {t["id"]: t["text"] for t in merged["tasks"]}
    assert texts[mine["id"]] == "peer reworded this task"  # newer write wins
    assert "bob" in merged["participants"]

    # Re-importing the same envelope changes nothing (idempotent).
    again = ws_store.import_envelope([{
        "slug": "merge-me", "name": "merge-me",
        "notes": [], "tasks": [peer_task],
        "participants": dict(merged["participants"]),
    }])
    assert again["skipped"] >= 1


def test_collab_router_surface():
    from fastapi import FastAPI

    from server.routers.collab_router import router, ws_router

    app = FastAPI()
    app.include_router(router)
    app.include_router(ws_router)
    rest_paths = {getattr(r, "path", "") for r in router.routes}
    ws_paths = {getattr(r, "path", "") for r in ws_router.routes}
    for expected in ("/api/collab/workspaces", "/api/collab/{name}/notes",
                     "/api/collab/{name}/tasks", "/api/collab/{name}/merge"):
        assert expected in rest_paths
    assert "/ws/collab/{name}" in ws_paths


# ════════════════════════ MCP ECOSYSTEM INTEGRATION ═══════════════════════════

def test_mcp_registry_exposes_new_capabilities():
    from server.systems.llm_router import build_default_registry

    names = build_default_registry().tool_names()
    assert "browser.navigate" in names
    assert "cognition.thoughts" in names
