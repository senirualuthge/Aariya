"""End-to-end tests for the gap-closing modules: cognitive kernel wiring, causal
simulation, memory consolidation, user modeling, safety governor, LLM routing,
skill synthesis, and desktop twin.

All tests are pure-Python (no DB / network / chromadb) so they run anywhere.
"""

import asyncio
import os
import tempfile

import pytest

from server.safety import filesystem_guard as guard
from server.systems.skills.skill_synthesis import SkillSynthesis
from server.systems.desktop_twin import DesktopTwin
from server.systems.llm_router import LLMRouter, get_mcp_registry


class _StubEngine:
    pass


# ── Cognitive kernel ───────────────────────────────────────────────────────────

def test_cognitive_kernel_roundtrip():
    from server.systems.cognition.cognitive_kernel import get_cognitive_kernel
    k = get_cognitive_kernel()
    k.integrate_turn(text="hello there", emotion={"valence": 0.5})
    snap = k.snapshot()
    assert "world" in snap
    assert "focus" in snap
    assert "reflection_success_rate" in snap


def test_cognitive_kernel_horizon_plan():
    from server.systems.cognition.cognitive_kernel import get_cognitive_kernel
    k = get_cognitive_kernel()
    tree = k.plan_objective("ship v2", ["design", "build", "test"])
    assert tree["objective"] == "ship v2"
    assert len(tree["subgoals"]) == 3


def test_cognitive_kernel_meta_routing():
    from server.systems.cognition.cognitive_kernel import get_cognitive_kernel
    k = get_cognitive_kernel()
    assert k.route_task({"intent": "search_files"})["best_agent"] == "filesystem_agent"
    assert k.route_task({"intent": "research"})["best_agent"] == "research_agent"


# ── Causal reasoning / internal simulation ─────────────────────────────────────

def test_causal_simulation_flows():
    from server.systems.prediction.prediction_core import PredictionEngine, CausalEdge
    from server.systems.prediction.causal_simulator import CausalSimulator
    eng = PredictionEngine()
    eng.causal_graph.add_edge(CausalEdge(source="valence", relation="drives", target="engagement", confidence=0.8))
    eng.causal_graph.add_edge(CausalEdge(source="engagement", relation="drives", target="retention", confidence=0.7))
    sim = CausalSimulator(eng.causal_graph)
    effects = sim.simulate_node("valence", 0.6)["effects"]
    names = [e["target"] for e in effects]
    assert "engagement" in names and "retention" in names
    assert sim.counterfactual({"retention": 0.9}, "retention")["most_plausible"]["cause"] == "engagement"


def test_causal_intervention_cleanup():
    from server.systems.prediction.prediction_core import PredictionEngine
    from server.systems.prediction.causal_simulator import CausalSimulator
    eng = PredictionEngine()
    before = len(eng.causal_graph.edges)
    sim = CausalSimulator(eng.causal_graph)
    sim.intervene("a", "b", 1.0)
    assert len(eng.causal_graph.edges) == before  # intervention leaves no trace


# ── LLM routing ────────────────────────────────────────────────────────────────

def test_llm_router_choices():
    router = LLMRouter(_StubEngine(), _StubEngine())
    assert router.route("sentiment") == "local"
    assert router.route("code") == "remote"
    assert router.route("unknown_task") == "local"
    assert router.route("code", latency_budget_ms=50) == "none"


def test_mcp_registry_tools():
    reg = get_mcp_registry()
    names = reg.tool_names()
    assert "safety.governor.status" in names
    assert "memory.maintenance" in names
    assert "cognition.snapshot" in names


# ── Skill synthesis ────────────────────────────────────────────────────────────

def test_skill_synthesis_promotes_repeat_workflow():
    ss = SkillSynthesis()
    for _ in range(3):
        ss.observe_turn("startup_routine", ["open_editor", "init", "deps"], True)
    created = ss.synthesize()
    assert "startup_routine" in created
    assert ss.best_skill_for("startup") == "startup_routine"
    assert ss.registry.get("startup_routine")["metadata"]["source"] == "synthesized"  # type: ignore


def test_skill_synthesis_requires_repetition():
    ss = SkillSynthesis()
    ss.observe_turn("one_off", ["a", "b"], True)  # only 1 run
    assert ss.synthesize() == []


# ── Desktop twin ───────────────────────────────────────────────────────────────

def test_desktop_twin_predicts_app_switches():
    twin = DesktopTwin("u")
    twin.observe_app("chrome")
    twin.observe_app("editor")
    twin.observe_app("chrome")
    next_apps = twin.suggests_next()
    assert next_apps and next_apps[0]["app"] == "editor"
    ctx = twin.context()
    assert ctx["active_app"] == "chrome"
    assert len(ctx["top_apps"]) >= 1


# ── Safety governor (audit + rollback) ─────────────────────────────────────────

def test_safety_governor_audit_and_rollback(tmp_path):
    orig = list(guard.SAFE_DIRECTORIES)
    guard.SAFE_DIRECTORIES = [str(tmp_path.resolve())]
    try:
        from server.systems.filesystem.filesystem_agent import FileSystemAgent
        from server.safety.governor import SafetyGovernor
        agent = FileSystemAgent()
        agent.roots = guard.allowed_roots()
        gov = SafetyGovernor(agent, journal_path=str(tmp_path / "audit.jsonl"))
        target = tmp_path / "note.txt"
        assert gov.write_file(str(target), "hello", actor="test") is True
        assert target.read_text() == "hello"
        assert gov.delete_file(str(target), confirmed=True, actor="test") is True
        assert not target.exists()
        res = gov.rollback()
        assert res["restored"] == 1
        assert target.read_text() == "hello"
        actions = [e["action"] for e in gov.audit_log()]
        assert "write_file" in actions and "delete_file" in actions
    finally:
        guard.SAFE_DIRECTORIES = orig


def test_safety_governor_confirmation_gate(tmp_path):
    from server.systems.filesystem.filesystem_agent import FileSystemAgent
    from server.safety.governor import SafetyGovernor
    agent = FileSystemAgent()
    gov = SafetyGovernor(agent, journal_path=str(tmp_path / "a.jsonl"))
    # delete without confirmed=True must not touch disk
    assert gov.delete_file(str(tmp_path / "ghost.txt"), actor="test") is False


# ── User model ─────────────────────────────────────────────────────────────────

def test_user_model_habits_and_anticipation():
    from server.systems.user_model import get_user_model
    m = get_user_model("tu")
    # Unit test of UserModel logic — force the in-memory store. Without this,
    # a live Postgres with the pattern_memory table hijacks the hierarchy path,
    # where memory_hierarchy's SQLite-style '?' placeholders fail against
    # Postgres and habits() silently returns [] (pre-existing prod issue).
    m._memory_hierarchy = False
    m.observe(topic="python", intent="code")
    m.observe(topic="python", intent="code")
    m.observe(topic="python", intent="code")
    m.observe(topic="design", intent="plan")
    habits = m.habits()
    assert habits, "expected at least one habit after repeated observation"
    anticipations = m.anticipate(current_topic="python")
    assert anticipations and "python" in anticipations[0]["suggestion"]
    assert "distribution" in m.rhythm()


# ── Filesystem background service (P2: boot wiring) ───────────────────────────

def test_filesystem_background_service_starts_and_feeds_twin():
    from server.systems.filesystem.background_service import (
        get_filesystem_service, _service as _fs_singleton,
    )
    import server.systems.filesystem.background_service as fs_mod
    # Test-isolation: system_health probes bind the module singleton to
    # "user_default", so reset it to guarantee a fresh per-user instance here.
    fs_mod._service = None
    try:
        from server.systems.desktop_twin import get_desktop_twin
        svc = get_filesystem_service("fs_test")
        svc.start(roots=[])
        assert svc.status()["started"] is True
        twin = get_desktop_twin("fs_test")
        svc.observe_document("/tmp/some_doc.md")
        assert twin.active_document == "/tmp/some_doc.md"
        svc.shutdown()
    finally:
        fs_mod._service = _fs_singleton


def test_twin_notifying_indexer_proxies_to_twin():
    from server.systems.filesystem.background_service import _TwinNotifyingIndexer
    seen = []

    class FakeIndexer:
        def index_file(self, path, text=None):
            return True

    proxy = _TwinNotifyingIndexer(FakeIndexer(), notifier=seen.append)  # type: ignore
    assert proxy.index_file("/tmp/a.md", "hello") is True
    assert seen == ["/tmp/a.md"]


# ── Task planner + action executor (P2, AccessFIles §21-22) ───────────────────

def test_task_planner_recipes_and_fallbacks():
    from server.systems.planner import TaskPlanner
    p = TaskPlanner()
    assert p.generate_plan("open chrome") == [{"action": "launch_app", "app": "chrome"}]
    assert p.generate_plan("search youtube")[1]["url"] == "https://youtube.com"
    topic = p.generate_plan("research climate change")[0]["topic"]
    assert "climate" in topic
    assert p.generate_plan("gibberish qqq") == []


def test_task_planner_goal_type_recipes_not_empty():
    """P0-4: every GoalSystem/HierarchicalGoalSystem goal type must map to an
    executable (non-empty) ActionExecutor plan so the planner→executor chain
    actually fires instead of degrading to an empty summary (AccessFIles §21)."""
    from server.systems.planner import TaskPlanner
    p = TaskPlanner()
    for goal_type in ("stabilize", "build_trust", "increase_curiosity",
                      "reduce_risk", "maintain_stability", "build_relationship",
                      "expand_knowledge"):
        plan = p.generate_plan(goal_type)
        assert plan, f"goal type '{goal_type}' produced empty plan"
        for step in plan:
            assert step["action"] in (
                "launch_app", "navigate", "wait", "type", "create_document",
                "observe", "research", "run_code", "check_in", "press_key",
                "hotkey", "click", "screen_reason",
            ), f"unsupported action in {goal_type} plan: {step}"
        assert any(s["action"] not in ("check_in", "wait") for s in plan), \
            f"goal type '{goal_type}' plan is check-in/wait-only (not actionable)"


def test_task_planner_goal_types_execute():
    """P0-4: executing a goal-type plan runs real steps through ActionExecutor."""
    from server.systems.planner import TaskPlanner
    from server.systems.executor.action_executor import ActionExecutor
    from server.systems.desktop_twin import DesktopTwin
    import asyncio
    twin = DesktopTwin("goal_exec")
    ex = ActionExecutor(twin=twin)
    plan = TaskPlanner().generate_plan("build_trust")
    res = asyncio.run(ex.execute(plan, goal="build_trust"))
    assert res["status"] == "completed"
    actions = [s["action"] for s in res["steps"]]
    assert "observe" in actions
    assert all(s["status"] != "blocked" for s in res["steps"])


def test_action_executor_dispatches_and_blocks():
    from server.systems.planner import TaskPlanner
    from server.systems.executor.action_executor import ActionExecutor
    import asyncio
    ex = ActionExecutor(twin=None)
    plan = TaskPlanner().generate_plan("open chrome")
    res = asyncio.run(ex.execute(plan, goal="open chrome"))
    assert res["status"] == "completed"
    assert ex.summary()["executed"] == 1
    blocked = asyncio.run(ex.execute([{"action": "sudo rm"}], goal="bad"))
    assert blocked["steps"][0]["status"] == "blocked"
    assert ex.summary()["blocked"] == 1


def test_action_executor_feeds_twin():
    from server.systems.planner import TaskPlanner
    from server.systems.executor.action_executor import ActionExecutor
    from server.systems.desktop_twin import DesktopTwin
    import asyncio
    twin = DesktopTwin("exec_test")
    ex = ActionExecutor(twin=twin)
    asyncio.run(ex.execute(TaskPlanner().generate_plan("open chrome"), goal="open chrome"))
    assert twin.active_app == "chrome"


# ── NEWPredictionPRT2 §8: Replanning on failure ───────────────────────────────

def test_replanner_returns_alternative_strategies():
    """§8 Replanning: replan(failed_task) must return alternative strategies,
    each with a strategy description and concrete whitelisted fallback steps."""
    from server.systems.planner import Replanner
    alts = Replanner().replan({"action": "research", "goal": "find climate data"})
    assert len(alts) >= 2
    for alt in alts:
        assert alt["strategy"]
        assert isinstance(alt["steps"], list) and len(alt["steps"]) >= 1
        assert all(s.get("action") for s in alt["steps"])
    assert any("backup" in a["strategy"].lower() or "replan" in a["strategy"].lower()
               for a in alts)


def test_replanner_continue_plan_shape():
    """'Use backup provider → Continue plan': continue_plan must say whether
    the plan can continue and how many alternatives exist."""
    from server.systems.planner import Replanner
    out = Replanner().continue_plan({"action": "launch_app", "goal": "open chrome"})
    assert out["failed_action"] == "launch_app"
    assert out["can_continue"] is True
    assert out["alternative_count"] >= 2
    assert all(a["steps"] for a in out["alternatives"])


def test_replanner_accepts_string_failed_task():
    from server.systems.planner import Replanner
    alts = Replanner().replan("weather_api")
    assert alts, "string failed task should still produce a last-resort strategy"
    assert alts[0]["failed_action"] == "weather_api"


def test_executor_replans_failed_step():
    """When a step raises, the executor must generate an alternative strategy
    and dispatch its fallback steps, continuing the plan (§8)."""
    from server.systems.executor.action_executor import ActionExecutor
    import asyncio

    class Flaky:
        pass

    ex = ActionExecutor(twin=None)
    # Patch the dispatcher so 'navigate' always raises → triggers replanning.
    async def flaky_dispatch(action, step):
        raise RuntimeError("network offline")

    ex._dispatch = flaky_dispatch  # type: ignore
    res = asyncio.run(ex.execute([{"action": "navigate", "url": "https://x.com"}],
                                 goal="browse"))
    assert any(s["status"] == "failed" and s["action"] == "navigate" for s in res["steps"])
    assert len(ex.replans) >= 1
    replan = ex.replans[0]
    assert replan["can_continue"] is True
    assert replan["failed_action"] == "navigate"
    # The first alternative's steps must have been dispatched as replanned steps.
    replanned = [s for s in res["steps"] if s.get("replanned_for") == "navigate"]
    assert len(replanned) >= 1
    assert all(s["status"] == "failed" for s in replanned)  # flaky dispatcher


def test_executor_records_replan_summary():
    from server.systems.executor.action_executor import ActionExecutor
    import asyncio
    ex = ActionExecutor(twin=None)
    async def flaky_dispatch(action, step):
        raise RuntimeError("boom")
    ex._dispatch = flaky_dispatch  # type: ignore
    asyncio.run(ex.execute([{"action": "check_in", "context": "hi"}], goal="hi"))
    summary = ex.summary()
    assert summary["replans"] == 1


# ── Causal learning engine (P3, NEWPredictionPRT2 §Phase 15) ──────────────────

def test_causal_learning_learns_a_b_edge():
    from server.systems.prediction.causal_learning import CausalLearningEngine
    from server.systems.prediction.prediction_core import CausalGraph
    import tempfile, time, os
    path = tempfile.mktemp(suffix=".json")
    eng = CausalLearningEngine(graph=CausalGraph(), persist_path=path,
                               min_evidence=2, window_seconds=300)
    ts = time.time()
    for i in range(4):
        eng.observe("A", entity="u", ts=ts + i * 10)
        eng.observe("B", entity="u", ts=ts + i * 10 + 2)
    exp = eng.explain("A", "B")
    assert exp is not None and exp["confidence"] > 0.7
    assert eng.known_causes("B")[0]["cause"] == "A"
    os.remove(path)


def test_causal_learning_prunes_reverse_edge():
    from server.systems.prediction.causal_learning import CausalLearningEngine
    from server.systems.prediction.prediction_core import CausalGraph
    import tempfile, time, os
    path = tempfile.mktemp(suffix=".json")
    eng = CausalLearningEngine(graph=CausalGraph(), persist_path=path,
                               min_evidence=2, window_seconds=300)
    ts = time.time()
    for i in range(4):
        eng.observe("A", entity="u", ts=ts + i * 10)
        eng.observe("B", entity="u", ts=ts + i * 10 + 2)
    edges = eng.snapshot()["edges"]
    assert len(edges) == 1 and edges[0]["source"] == "A" and edges[0]["target"] == "B"
    os.remove(path)


def test_causal_learning_persists():
    from server.systems.prediction.causal_learning import CausalLearningEngine
    from server.systems.prediction.prediction_core import CausalGraph
    import tempfile, time, os
    path = tempfile.mktemp(suffix=".json")
    eng = CausalLearningEngine(graph=CausalGraph(), persist_path=path,
                               min_evidence=1, window_seconds=300)
    eng.observe("X", entity="u", ts=time.time() - 5)
    eng.observe("Y", entity="u", ts=time.time())
    eng2 = CausalLearningEngine(graph=CausalGraph(), persist_path=path, min_evidence=1)
    assert any(e.source == "X" and e.target == "Y" for e in eng2.graph.edges)
    os.remove(path)


# ── Strategic memory: PlanMemory + FailureMemory + Lessons (P3) ───────────────

def test_plan_memory_store_and_reuse():
    from server.systems.prediction.strategic_memory import PlanMemory
    pm = PlanMemory()
    pm.store("stabilize", ["reduce_volatility", "increase_reasoning"], reward=0.9)
    pm.store("stabilize", ["reduce_volatility", "increase_reasoning"], reward=0.9)
    recalled = pm.recall("stabilize")
    assert recalled and recalled[0]["goal"] == "stabilize"
    assert pm.reuse_count and max(pm.reuse_count.values()) >= 1


def test_failure_memory_instant_recovery():
    from server.systems.prediction.strategic_memory import FailureMemory
    fm = FailureMemory()
    assert fm.recover("api_timeout") is None
    fm.record("api_timeout", "switch_backup_api")
    assert fm.recover("api_timeout") == "switch_backup_api"


def test_strategic_lessons_promote_to_principles():
    from server.systems.prediction.strategic_memory import StrategicLessons
    sl = StrategicLessons()
    for _ in range(StrategicLessons.PRINCIPLE_THRESHOLD):
        sl.learn([{"concept": "early_warning", "quality": 0.95}])
    snap = sl.snapshot()
    assert any(l["status"] == "principle" for l in snap["principles"])
    assert sl.lessons["early_warning"]["occurrences"] >= StrategicLessons.PRINCIPLE_THRESHOLD


# ── Prediction verification loop (NEWPredictionPRT2 §11 / Phase 8) ────────────

def test_verifier_closes_loop_with_resolver():
    from server.systems.prediction.prediction_core import PredictionEngine
    from server.systems.prediction.verifier import PredictionVerifier
    eng = PredictionEngine(persist_dir=tempfile.mkdtemp())
    for _ in range(3):
        eng.predict_turn({"valence": 0.8, "arousal": 0.5})
    verifier = PredictionVerifier(eng, horizon_seconds=0.0)
    result = verifier.verify_due(
        resolver=lambda entry: entry.get("domain") == "conversation"
    )
    assert result["verified_this_pass"] == 3
    metrics = verifier.metrics()
    assert metrics["verified"] == 3
    assert metrics["accuracy"] == 1.0
    assert metrics["loop_closed"] is True
    assert all(p["verified"] for p in eng.store.predictions)


def test_verifier_recalibrates_incorrect_predictions():
    from server.systems.prediction.prediction_core import PredictionEngine
    from server.systems.prediction.verifier import PredictionVerifier
    eng = PredictionEngine(persist_dir=tempfile.mkdtemp())
    entry = eng.store.add("valence will rise", 0.9, domain="conversation")
    verifier = PredictionVerifier(eng, horizon_seconds=0.0)
    verifier.verify_due(resolver=lambda e: False)  # it was wrong
    assert eng.store.predictions[0]["verified"]
    assert not eng.store.predictions[0]["correct"]
    assert eng.store.predictions[0]["confidence"] < 0.9  # decayed via recalibrate
    assert verifier.metrics()["accuracy"] == 0.0


def test_verifier_skips_unknown_verdicts():
    from server.systems.prediction.prediction_core import PredictionEngine
    from server.systems.prediction.verifier import PredictionVerifier
    eng = PredictionEngine(persist_dir=tempfile.mkdtemp())
    eng.store.add("valence will rise", 0.7, domain="conversation")
    verifier = PredictionVerifier(eng, horizon_seconds=0.0)
    verifier.verify_due(resolver=lambda e: None)  # no real verdict yet
    assert not eng.store.predictions[0]["verified"]
    assert verifier.metrics()["verified"] == 0


# ── Prediction store persistence (NEWPredictionPRT2 §Phase 2.5 / §Phase 4) ────

def test_prediction_store_persists_across_reload():
    from server.systems.prediction.prediction_core import PredictionStore
    path = os.path.join(tempfile.mkdtemp(), "predictions.json")
    store = PredictionStore(persist_path=path)
    store.add("good day", 0.8, domain="conversation")
    reloaded = PredictionStore(persist_path=path)
    assert len(reloaded.predictions) == 1
    assert reloaded.predictions[0]["prediction"] == "good day"


def test_world_memory_and_beliefs_persist():
    from server.systems.prediction.prediction_core import BeliefEngine, WorldMemory
    base = tempfile.mkdtemp()
    wm = WorldMemory(persist_path=os.path.join(base, "world.json"))
    wm.store({"entity": "u", "domain": "conversation", "valence": 0.5})
    be = BeliefEngine(persist_path=os.path.join(base, "beliefs.json"))
    be.set("user_is_happy", 0.6)
    assert len(WorldMemory(persist_path=os.path.join(base, "world.json")).events) == 1
    assert BeliefEngine(persist_path=os.path.join(base, "beliefs.json")).beliefs.get("user_is_happy")


def test_shared_engine_is_singleton_across_modules():
    from server.systems.prediction.prediction_core import get_prediction_engine
    assert get_prediction_engine() is get_prediction_engine()


def test_drift_detector_flags_accuracy_shift():
    from server.systems.prediction.drift_detector import DriftDetector
    dd = DriftDetector(window=10, baseline_window=10, threshold=0.3)
    for _ in range(10):
        dd.record(True)   # establish a strong baseline
    assert dd.snapshot()["drift_detected"] is False
    for _ in range(10):
        dd.record(False)  # recent accuracy collapses
    snap = dd.snapshot()
    assert snap["recent_accuracy"] < snap["baseline"]
    assert snap["drift_detected"] is True
    assert snap["verdict"] == "drift"


def test_prediction_rest_endpoints():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server.routers.prediction_router import router
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    for path in ["/api/prediction/status", "/api/prediction/calibration",
                 "/api/prediction/causal-graph", "/api/prediction/strategic",
                 "/api/prediction/forecast?value=0.6&drift=0.01"]:
        assert c.get(path).status_code == 200
    assert c.get("/api/prediction/forecast").json()["direction"] in ("rising", "falling", "stable")


# ── Previously-dead modules now wired (P2 / AccessFIles) ──────────────────────

def test_social_policy_enforces_trust_boundary():
    from server.systems.neural_policy import SocialPolicyNetwork
    sp = SocialPolicyNetwork()
    action = sp.predict_action({"valence": 0.9, "arousal": 0.8, "trust": 0.3, "contradiction": 0.1})
    constrained = sp.apply_safety_constraints(
        action, user_id="u", session_id="s", trust=0.3,
        contradiction_history=0.1, boundary_flags=[],
    )
    assert constrained["emotion_intensity"] <= 0.3  # hard rule: intensity ≤ trust


def test_ppo_policy_selects_style_without_errors():
    from server.systems.rl.rl_policy import get_ppo_policy
    policy = get_ppo_policy()
    style = policy.select_style({"valence": 0.6, "arousal": 0.4, "trust": 0.7,
                                 "contradiction": 0.0, "history_len": 5})
    assert style in ("supportive", "playful", "assertive", "reflective", "neutral")
    assert isinstance(policy.get_style_prompt_modifier(style), str)


def test_turn_predictor_rates_final_vs_continuation():
    from server.systems.turn_predictor import create_turn_predictor
    tp = create_turn_predictor()
    finished = tp.predict("Tell me about yourself.", 0, True).completion_probability
    assert finished >= 0.8
    cont = tp.predict("and then I was thinking that maybe", 0, False).completion_probability
    assert cont < finished


def test_action_evaluator_ranks_by_predicted_outcome():
    from server.systems.prediction.prediction_core import PredictionEngine
    eng = PredictionEngine(persist_dir=f"{tempfile.mkdtemp()}/pe")
    cands = [
        {"id": "d", "description": "soothe the user", "intent": "de-escalate"},
        {"id": "n", "description": "balanced neutral reply", "intent": "neutral"},
        {"id": "a", "description": "direct assertive reply", "intent": "assertive"},
    ]
    ranked = eng.evaluate_actions(cands, state={"valence": -0.6, "trust": 0.3})
    assert ranked[0]["id"] == "d"
    assert ranked[0]["score"] >= ranked[1]["score"] >= ranked[2]["score"]
    assert eng.select_action(cands, state={"valence": -0.6, "trust": 0.3})["id"] == "d"


def test_action_evaluator_consults_decision_memory_prior():
    from server.systems.prediction.prediction_core import PredictionEngine
    eng = PredictionEngine(persist_dir=f"{tempfile.mkdtemp()}/pe")
    for _ in range(3):
        eng.decisions.save({"intent": "playful"}, "tease", "user loved it", 1.0)
    cands = [
        {"id": "p", "description": "tease playfully", "intent": "playful"},
        {"id": "n", "description": "neutral reply", "intent": "neutral"},
    ]
    ranked = eng.evaluate_actions(cands, state={"valence": 0.8, "trust": 0.9})
    playful = next(r for r in ranked if r["id"] == "p")
    neutral = next(r for r in ranked if r["id"] == "n")
    assert playful["prior_reward"] > neutral["prior_reward"]


def test_core_calibrates_overconfidence_down():
    from server.systems.prediction.prediction_core import PredictionEngine
    eng = PredictionEngine(persist_dir=f"{tempfile.mkdtemp()}/pe")
    samples = [{"confidence": 0.9, "correct": 0, "value": 0.8}] * 5
    res = eng.core.calibrate(samples)
    assert res["calibrated"] is True
    assert res["bias"] < 0
    assert eng.core.calibration_state()["bias"] < 0


def test_drift_recalibrate_widens_uncertainty():
    from server.systems.prediction.prediction_core import PredictionEngine
    eng = PredictionEngine(persist_dir=f"{tempfile.mkdtemp()}/pe")
    before = eng.core.calibration_state()["bias"]
    res = eng.core.drift_recalibrate({"drift_detected": True, "shift_score": 0.6})
    assert res["recalibrated"] is True
    assert eng.core.calibration_state()["bias"] < before


def test_verify_due_triggers_drift_retrain():
    import time
    from server.systems.prediction.prediction_core import PredictionEngine
    from server.systems.prediction.verifier import PredictionVerifier
    eng = PredictionEngine(persist_dir=f"{tempfile.mkdtemp()}/pe")
    v = PredictionVerifier(eng, horizon_seconds=0.01)
    for i in range(60):
        eng.store.add(f"base{i}", 0.8, domain="conversation")
    for i in range(40):
        eng.store.add(f"rec{i}", 0.8, domain="conversation")
    for e in eng.store.predictions:
        e["added_at"] = time.time() - 100
        e["confidence"] = 0.8
    res = v.verify_due(resolver=lambda p: "base" in p["prediction"], force=True)
    assert res["drift"]["drift_detected"] is True
    assert res["recalibration"]["recalibrated"] is True
    assert "core_calibration" in v.metrics()
    assert "calibration" in eng.snapshot()


def test_proactive_alert_chain_ranks_events():
    from server.systems.prediction.prediction_core import PredictionEngine
    eng = PredictionEngine(persist_dir=f"{tempfile.mkdtemp()}/pe")
    eng.world_memory.store({"entity": "user", "domain": "conversation", "valence": -0.7})
    eng.world_memory.store({"entity": "user", "domain": "conversation", "valence": 0.1})
    alerts = eng.assess_alerts(user_state={"valence": -0.5, "trust": 0.4})
    assert alerts, "expected at least one alert"
    assert alerts[0]["score"] >= alerts[-1]["score"]
    assert alerts[0]["actionable"] is True


def test_followup_trigger_fires_on_actionable_alert():
    from server.autonomy.config import config  # noqa: F401 (breaks import cycle)
    from server.systems.prediction.prediction_core import PredictionEngine
    from server.systems.proactive.engine import ProactiveAIEngine
    eng = PredictionEngine(persist_dir=f"{tempfile.mkdtemp()}/pe")
    eng.world_memory.store({"entity": "user", "domain": "conversation", "valence": -0.8})
    alerts = eng.assess_alerts(user_state={"valence": -0.6, "trust": 0.4})
    engine = ProactiveAIEngine("u")
    trigger = engine.evaluate(
        prediction={"confidence": 0.5}, trust=0.5, session_active=True,
        extra={"proactive_alerts": alerts},
    )
    assert trigger is not None
    assert trigger["type"] == "followup"
    assert "domain" in trigger["payload"]


def test_daemon_extra_includes_proactive_alerts():
    import inspect
    import server.autonomy.daemon as daemon_mod
    src = inspect.getsource(daemon_mod)
    assert "proactive_alerts" in src
    assert "assess_alerts" in src


def test_belief_engine_evidence_updates_and_persists():
    import server.systems.prediction.prediction_core as pc_mod
    pc_mod._engine = None
    from server.systems.prediction.prediction_core import get_prediction_engine
    eng = get_prediction_engine()
    eng.beliefs.beliefs.clear()
    eng.beliefs.update("user_distressed", 0.9)
    eng.beliefs.update("user_distressed", 0.5)
    assert 0.5 < eng.beliefs.get("user_distressed") < 0.9  # type: ignore
    eng2 = get_prediction_engine()
    assert eng2.beliefs.get("user_distressed") is not None


def test_decision_memory_save_and_retrieve():
    from server.systems.prediction.prediction_core import PredictionEngine
    eng = PredictionEngine(persist_dir=f"{tempfile.mkdtemp()}/pe")
    eng.decisions.save({"intent": "de-escalate"}, "soothe", "observed_valence", 0.6)
    hits = eng.decisions.retrieve_similar({"intent": "de-escalate"}, top_k=1)
    assert hits and hits[0]["reward"] == 0.6
    miss = eng.decisions.retrieve_similar({"intent": "playful"}, top_k=1)
    assert miss == []


# ── Prediction P2: meta-reasoning routing + governor delegation ───────────────

def test_meta_reasoner_routes_by_keywords():
    from server.systems.cognition.meta_reasoner import MetaReasoner
    m = MetaReasoner()
    assert m.evaluate({"intent": "", "query": "please write a file for me"})["best_agent"] == "filesystem_agent"
    assert m.evaluate({"intent": "", "query": "search the web for news"})["best_agent"] == "research_agent"
    assert m.evaluate({"intent": "", "query": "fix the bug in my code"})["best_agent"] == "coding_agent"
    assert m.evaluate({"intent": "", "query": "make a plan for this goal"})["best_agent"] == "planner_agent"
    assert m.evaluate({"intent": "", "query": "that movie made me smile"})["best_agent"] == "general_agent"


def test_governor_delegates_and_executes_agent():
    from server.systems.agent.governor import AgentGovernor

    class _FakeAgent:
        name = "fake_agent"
        def can_handle(self, task):
            return "fake" in str(task)
        async def act(self, task):
            return {"handled": True}

    gov = AgentGovernor(agents=[_FakeAgent()])
    dec = gov.delegate("a fake request")
    assert dec["status"] == "delegated" and dec["agent"] == "fake_agent"
    import asyncio
    res = asyncio.run(gov.execute("a fake request"))
    assert res["status"] == "ok" and res["result"]["handled"] is True
    assert gov.merge_results([{"a": [1]}, {"a": [2], "b": "x"}]) == {"a": [1, 2], "b": "x"}


def test_brain_meta_route_surfaces_routing(isolated_db):
    import asyncio
    from server.protocol import MultimodalInput
    from server.systems.prediction.prediction_core import PredictionEngine
    import server.systems.prediction.prediction_core as pc_mod
    pc_mod._engine = PredictionEngine(persist_dir=f"{tempfile.mkdtemp()}/pe")
    from server.systems.brain_v2 import BrainV2
    b = BrainV2(user_id="u1")
    async def run(text):
        await b.process(MultimodalInput(text=text, metadata={"user_id": "u1", "session_id": "s1"}))
        return b.get_state().synoptic
    syn = asyncio.run(run("please write a file for me"))
    assert syn.get("meta_route", {}).get("best_agent") == "filesystem_agent"
    syn2 = asyncio.run(run("that movie made me smile today"))
    assert "meta_route" not in syn2


# ── P0-1: World State Snapshot (single source of truth) ───────────────────────

def test_world_state_snapshot_roundtrip():
    """Persisted canonical world state: single write path, known categories
    only, survives reload (NEWPredictionPRT2 §"4. Single Source of Truth")."""
    import tempfile, os
    from server.systems.world_model.world_state import WorldState
    path = tempfile.mktemp(suffix=".json")
    ws = WorldState(persist_path=path)
    ws.update("user", "valence", 0.42)
    ws.update_many("system", {"daemon_alive": True, "active_goal": "build_trust"})
    ws.update("bogus_cat", "x", 1)  # unknown category → refused
    snap = ws.snapshot()
    assert snap["state"]["user"]["valence"] == 0.42
    assert snap["state"]["system"]["active_goal"] == "build_trust"
    assert "bogus_cat" not in snap["state"]
    ws2 = WorldState(persist_path=path)
    assert ws2.get("user", "valence") == 0.42
    assert ws2.get_category("system")["daemon_alive"] is True
    assert ws2.get("missing", "k", "d") == "d"
    os.remove(path)


def test_brain_turn_writes_world_state(isolated_db):
    """A brain turn must fold its cognitive state into the persisted world
    state so the daemon/routers read one canonical store, not disjoint copies."""
    import asyncio, tempfile, os
    from server.protocol import MultimodalInput
    from server.systems.prediction.prediction_core import PredictionEngine
    import server.systems.prediction.prediction_core as pc_mod
    import server.systems.world_model.world_state as ws_mod
    tmp = tempfile.mkdtemp()
    pc_mod._engine = PredictionEngine(persist_dir=f"{tmp}/pe")
    path = f"{tmp}/world_state.json"
    ws_mod._singleton = None
    from server.systems.world_model.world_state import get_world_state
    get_world_state(persist_path=path)  # prime the singleton
    from server.systems.brain_v2 import BrainV2
    b = BrainV2(user_id="u1")
    asyncio.run(b.process(MultimodalInput(text="hello there", metadata={"user_id": "u1", "session_id": "s1"})))
    snap = get_world_state(persist_path=path).snapshot()
    assert snap["state"]["user"]["trust"] >= 0.0
    assert "dominant_domain" in snap["state"]["system"]
    assert b.get_state().synoptic.get("world_state_ts") is not None


def test_brain_turn_surfaces_meta_policy_gate(isolated_db):
    """A brain turn must run the turn forecast through the MetaPolicy gate and
    surface the governed decision (REQUEST_MORE_DATA/CAUTION/ABSTAIN/ACCEPT)
    under synoptic['policy'] (NEWPredictionPRT2 §"Meta-Policy")."""
    import asyncio
    from server.protocol import MultimodalInput
    from server.systems.prediction.prediction_core import PredictionEngine
    import server.systems.prediction.prediction_core as pc_mod
    import tempfile
    tmp = tempfile.mkdtemp()
    pc_mod._engine = PredictionEngine(persist_dir=f"{tmp}/pe")
    from server.systems.brain_v2 import BrainV2
    b = BrainV2(user_id="u1")
    asyncio.run(b.process(MultimodalInput(text="hello", metadata={"user_id": "u1", "session_id": "s1"})))
    syn = b.get_state().synoptic
    assert syn.get("predicted_trajectory", {}).get("value") is not None
    policy = syn.get("policy")
    assert policy is not None
    assert policy["action"] in ("REQUEST_MORE_DATA", "CAUTION", "ABSTAIN", "ACCEPT")
    assert policy["explanation"]
    assert policy["confidence"] >= 0.0


# ── NEWPredictionPRT2: multi-scenario planning ────────────────────────────────

def test_scenario_planner_produces_best_expected_worst():
    """Multi-Scenario Planning (§6): plan() must branch a single state value
    into Best/Expected/Worst, each with a trajectory, probability and trigger."""
    from server.systems.prediction.prediction_core import ScenarioPlanner
    plan = ScenarioPlanner().plan(value=0.5, confidence=0.7, steps=3)
    assert plan["value"] == 0.5
    assert plan["confidence"] == 0.7
    for name in ("best", "expected", "worst"):
        sc = plan["scenarios"][name]
        assert len(sc["trajectory"]) == 3
        assert 0.0 <= sc["value"] <= 1.0
        assert 0.0 <= sc["probability"] <= 1.0
        assert sc["trigger"]
    assert plan["scenarios"]["best"]["value"] >= plan["scenarios"]["expected"]["value"]
    assert plan["scenarios"]["expected"]["value"] >= plan["scenarios"]["worst"]["value"]
    assert plan["dominant"] == "expected"


def test_scenario_planner_low_confidence_flips_dominant():
    """When confidence is low the Worst branch should gain probability and
    become dominant (uncertainty-scaled risk), so the brain plans a fallback."""
    from server.systems.prediction.prediction_core import ScenarioPlanner
    high = ScenarioPlanner().plan(value=0.5, confidence=0.95)
    low = ScenarioPlanner().plan(value=0.5, confidence=0.05)
    assert low["scenarios"]["worst"]["probability"] > high["scenarios"]["worst"]["probability"]
    assert low["dominant"] == "worst"
    assert low["scenarios"]["worst"]["value"] < high["scenarios"]["worst"]["value"]


def test_multi_scenario_via_engine_and_brain_synoptic(isolated_db):
    """multi_scenario() must pick a chosen action and expose all three branches;
    a brain turn must surface them under synoptic['scenarios']."""
    import asyncio
    from server.systems.prediction.prediction_core import PredictionEngine, ScenarioPlanner
    from server.protocol import MultimodalInput
    import server.systems.prediction.prediction_core as pc_mod
    import tempfile
    tmp = tempfile.mkdtemp()
    pc_mod._engine = PredictionEngine(persist_dir=f"{tmp}/pe")
    eng = pc_mod._engine
    cands = [
        {"id": "soothe", "description": "gentle reassurance",
         "predicted_value": 0.85, "confidence": 0.9, "score": 0.9},
        {"id": "joke", "description": "crack a joke",
         "predicted_value": 0.4, "confidence": 0.3, "score": 0.4},
    ]
    scen = eng.multi_scenario(cands)
    assert scen["chosen"]["id"] == "soothe"
    assert set(scen.keys()) == {"chosen", "expected", "best", "worst", "plan"}
    assert scen["plan"]["steps"] == 3
    # Single-candidate path through the brain synoptic
    from server.systems.brain_v2 import BrainV2
    b = BrainV2(user_id="u1")
    asyncio.run(b.process(MultimodalInput(text="I'm anxious", metadata={"user_id": "u1", "session_id": "s1"})))
    syn = b.get_state().synoptic
    assert syn.get("selected_action", {}).get("id", "") != ""
    assert syn.get("scenarios", {}).get("dominant") in ("best", "expected", "worst")


def test_scenario_plan_for_action_uses_candidate_outcome():
    from server.systems.prediction.prediction_core import ScenarioPlanner
    cand = {"id": "a", "predicted_value": 0.75, "confidence": 0.6}
    plan = ScenarioPlanner().plan_for_action(cand)
    assert plan["value"] == 0.75
    assert plan["confidence"] == 0.6
    assert plan["dominant"] == "expected"


# ── AccessFIles P1: desktop controller + executor runtime path ────────────────

def test_executor_proposes_desktop_when_disabled():
    from server.systems.executor.action_executor import ActionExecutor
    import asyncio
    ex = ActionExecutor(controller=None, execute_desktop=False)
    res = asyncio.run(ex.execute([{"action": "launch_app", "app": "chrome"}], goal="g"))
    outcome = res["steps"][0]["outcome"]
    assert "proposed" in outcome


def test_executor_performs_desktop_when_enabled():
    from server.systems.executor.action_executor import ActionExecutor
    import asyncio

    class _FakeController:
        available = True
        def __init__(self):
            self.calls = []
        def open_application(self, app):
            self.calls.append(("open", app)); return True
        def type_text(self, t):
            self.calls.append(("type", t)); return True
        def click(self):
            self.calls.append(("click",)); return True

    ctrl = _FakeController()
    ex = ActionExecutor(controller=ctrl, execute_desktop=True)
    res = asyncio.run(ex.execute([
        {"action": "launch_app", "app": "chrome"},
        {"action": "type", "text": "hi"},
        {"action": "click"},
    ], goal="g"))
    assert "executed=ok" in res["steps"][0]["outcome"]
    assert "executed=ok" in res["steps"][1]["outcome"]
    assert ctrl.calls == [("open", "chrome"), ("type", "hi"), ("click",)]


def test_executor_screen_reason_graceful():
    from server.systems.executor.action_executor import ActionExecutor
    import asyncio
    ex = ActionExecutor(execute_desktop=True)
    res = asyncio.run(ex.execute([{"action": "screen_reason"}], goal="g"))
    assert "screen_reason" in res["steps"][0]["outcome"]


def test_executor_blocks_unknown_actions():
    from server.systems.executor.action_executor import ActionExecutor
    import asyncio
    ex = ActionExecutor(execute_desktop=True)
    res = asyncio.run(ex.execute([{"action": "rm -rf /"}], goal="g"))
    assert res["steps"][0]["status"] == "blocked"


# ── AccessFIles P1: agent society specialists + consensus ─────────────────────

def test_society_specialists_gather_votes():
    from server.systems.swarm.society import get_society
    import asyncio
    soc = get_society()
    votes = asyncio.run(soc.gather({"query": "refactor this python function"}))
    agents = {v["agent"] for v in votes}
    assert agents == {"coder", "researcher", "verifier", "archivist"}
    for v in votes:
        assert 0 <= v["confidence"] <= 1


def test_society_consensus_arbitrates():
    from server.systems.swarm.society import get_society
    import asyncio
    soc = get_society()
    res = asyncio.run(soc.gather({"query": "research climate change"}))
    consensus = soc.resolve(res)
    assert consensus["arbitrated"] is True
    assert consensus["consensus"]["agent"] in {"coder", "researcher", "verifier", "archivist"}
    assert 0 <= consensus["confidence"] <= 1
    empty = soc.resolve([])
    assert empty["arbitrated"] is False


def test_swarm_process_turn_surfaces_society():
    from server.systems.swarm.orchestrator import SwarmSystem
    import asyncio
    sw = SwarmSystem()
    res = asyncio.run(sw.process_turn({
        "trust": 0.6, "valence": 0.2, "strategy": "problem_solving",
        "vision_data": None, "image_b64": None,
    }))
    assert res["society"]["arbitrated"] is True
    assert res["society"]["consensus"]["agent"] is not None


def test_governor_registers_specialists():
    from server.systems.swarm.orchestrator import SwarmSystem
    sw = SwarmSystem()
    names = {getattr(a, "name", "") for a in sw.governor.agents}
    assert "filesystem_agent" in names
    assert "local_knowledge_agent" in names


# ── NEWPredictionPRT2 §1: Goal Management Engine ──────────────────────────────

def test_goal_manager_create_and_lifecycle():
    """§1 Goal Management: create_goal + update_progress auto-completes at 100."""
    from server.systems.goal_manager import GoalManager
    gm = GoalManager()
    gid = gm.create_goal_from("Become an AI engineer",
                              subgoals=["Learn Python", "Learn ML", "Build Projects", "Apply Jobs"])
    goal = gm.get_goal(gid)
    assert goal is not None
    assert goal.status == "active"
    assert goal.progress == 0
    assert len(goal.subgoals) == 4
    assert all(sg["status"] == "active" for sg in goal.subgoals)

    gm.update_progress(gid, 40)
    assert gm.get_goal(gid).progress == 40  # type: ignore
    assert gm.get_goal(gid).status == "active"  # type: ignore

    gm.update_progress(gid, 120)  # clamp
    assert gm.get_goal(gid).progress == 100  # type: ignore
    assert gm.get_goal(gid).status == "completed"  # type: ignore
    assert gm.get_goal(gid).completed_at is not None  # type: ignore


def test_goal_manager_next_action_returns_active_subgoal():
    """§1: next_action() returns the first active subgoal for an active goal."""
    from server.systems.goal_manager import GoalManager
    gm = GoalManager()
    gid = gm.create_goal_from("Build AARIYA", subgoals=["Router", "Planner", "World Model"])
    na = gm.next_action(gid)
    assert na["status"] == "active"
    assert na["action"] == "Router"

    # Complete the first subgoal → next action advances.
    gm.complete_subgoal(gid, f"{gid}_sg0")
    assert gm.next_action(gid)["action"] == "Planner"

    # Unknown / completed goals are unavailable.
    assert gm.next_action("missing")["status"] == "unavailable"
    gm.update_progress(gid, 100)
    assert gm.next_action(gid)["status"] == "unavailable"


def test_goal_manager_summary_matches_doc_shape():
    """The doc's memory contract: { goal, progress, next_step }."""
    from server.systems.goal_manager import GoalManager
    gm = GoalManager()
    gid = gm.create_goal_from("Build AARIYA", subgoals=["Router", "Planner", "World Model"])
    gm.complete_subgoal(gid, f"{gid}_sg0")
    summary = gm.summary()
    assert summary["active_count"] == 1
    snap = summary["goals"][0]
    assert snap["goal"] == "Build AARIYA"
    assert snap["progress"] == round(100 / 3, 1)
    assert snap["next_step"] == "Planner"
    assert snap["completed_subgoals"] == 1
    assert GoalManager().summary()["active_count"] == 0


def test_goal_manager_persists_across_instances():
    import tempfile, os
    from server.systems.goal_manager import GoalManager
    path = f"{tempfile.mkdtemp()}/goals.json"
    gm1 = GoalManager(persist_path=path)
    gid = gm1.create_goal_from("Learn ML", subgoals=["Linear algebra", "Networks"])
    gm1.complete_subgoal(gid, f"{gid}_sg0")
    gm2 = GoalManager(persist_path=path)
    g = gm2.get_goal(gid)
    assert g is not None
    assert g.progress == 50
    assert gm2.next_steps()[0]["action"] == "Networks"
    os.remove(path)


def test_brain_turn_folds_goals_into_world_state_tasks(isolated_db):
    """A brain turn must surface the long-term goal registry under the world
    state's tasks category (§1 Goal Management + Single Source of Truth)."""
    import asyncio, tempfile
    from server.protocol import MultimodalInput
    from server.systems.prediction.prediction_core import PredictionEngine
    import server.systems.prediction.prediction_core as pc_mod
    import server.systems.world_model.world_state as ws_mod
    from server.systems.world_model.world_state import get_world_state
    from server.systems.goal_manager import GoalManager
    tmp = tempfile.mkdtemp()
    pc_mod._engine = PredictionEngine(persist_dir=f"{tmp}/pe")
    ws_mod._singleton = None
    get_world_state(persist_path=f"{tmp}/world_state.json")
    from server.systems.brain_v2 import BrainV2
    b = BrainV2(user_id="u1")
    b._goal_manager = GoalManager(persist_path=f"{tmp}/goals.json")
    gid = b._goal_manager.create_goal_from("Build AARIYA", subgoals=["Router", "Planner"])
    asyncio.run(b.process(MultimodalInput(text="hello", metadata={"user_id": "u1", "session_id": "s1"})))
    snap = get_world_state(persist_path=f"{tmp}/world_state.json").snapshot()
    tasks = snap["state"]["tasks"]
    assert tasks["goals"]["active_count"] == 1
    assert tasks["goals"]["goals"][0]["goal"] == "Build AARIYA"
    assert tasks["goals"]["goals"][0]["next_step"] == "Router"
    assert b._goal_manager.get_goal(gid) is not None

