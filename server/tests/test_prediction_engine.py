"""Tests for server/systems/prediction/prediction_core.py — the unified
prediction engine (PredictionStore, PredictionCore, WorldMemory, BeliefEngine,
DecisionMemory, CausalGraph, PredictionEngine)."""

import pytest

from server.systems.prediction.prediction_core import (
    PredictionStore,
    PredictionCore,
    PredictionRequest,
    PredictionEngine,
    WorldMemory,
    BeliefEngine,
    DecisionMemory,
    CausalGraph,
    CausalEdge,
)
from server.systems.synoptic_smoother import SynopticSmoother


# ── PredictionStore ───────────────────────────────────────────────────────────

def test_store_add_and_verify_roundtrip():
    store = PredictionStore()
    entry = store.add("user will ask about x", 0.8, domain="general", entity="user")
    assert entry["id"] and not entry["verified"]

    verified = store.verify(entry["id"], "user asked about x", correct=True)
    assert verified is not None
    assert verified["verified"] is True
    assert verified["correct"] is True
    assert store.accuracy() == pytest.approx(1.0)


def test_store_unverified_excluded_from_accuracy():
    store = PredictionStore()
    store.add("p1", 0.6, domain="a", entity="e")
    store.add("p2", 0.7, domain="a", entity="e")
    assert len(store.unverified()) == 2
    assert store.accuracy() == 0.0


def test_store_verify_unknown_returns_none():
    store = PredictionStore()
    assert store.verify("missing", "outcome", correct=False) is None


# ── PredictionCore ────────────────────────────────────────────────────────────

def test_core_predict_returns_bounded_confidence():
    core = PredictionCore()
    req = PredictionRequest(
        domain="general", entity="user", horizon="short",
        features={"prev_intent": 0.9, "user_valence": -0.3},
    )
    out = core.predict(req)
    assert 0.0 <= out.confidence <= 1.0
    assert 0.0 <= out.value <= 1.0
    assert out.uncertainty >= 0.0
    assert out.reasoning_trace


def test_core_feature_fusion_deterministic():
    core = PredictionCore()
    req = PredictionRequest(domain="general", entity="user", features={"prev_intent": 0.5})
    a = core.predict(req)
    b = core.predict(req)
    assert a.value == b.value
    assert a.confidence == b.confidence


def test_core_no_features_is_uncertain():
    core = PredictionCore()
    out = core.predict(PredictionRequest(domain="d", entity="e", features={}))
    assert out.confidence == pytest.approx(0.1)
    assert out.uncertainty == pytest.approx(0.9)


# ── BeliefEngine ──────────────────────────────────────────────────────────────

def test_belief_engine_update_tracks_evidence():
    engine = BeliefEngine()
    engine.update("user_likes_dogs", 0.8)
    engine.update("user_likes_dogs", 0.8)
    conf = engine.get("user_likes_dogs")
    assert conf is not None
    assert conf > 0.7


def test_belief_engine_missing_returns_none():
    assert BeliefEngine().get("nope") is None


# ── DecisionMemory ────────────────────────────────────────────────────────────

def test_decision_memory_save_and_retrieve():
    mem = DecisionMemory()
    mem.save({"topic": "dogs"}, decision="recommend", outcome="positive", reward=1.0)
    hits = mem.retrieve_similar({"topic": "dogs", "tone": "casual"})
    assert len(hits) == 1
    assert hits[0]["decision"] == "recommend"


# ── CausalGraph ───────────────────────────────────────────────────────────────

def test_causal_graph_propagate_chains():
    g = CausalGraph()
    g.add_edge(CausalEdge("memory_fragment", "triggers", "recall", confidence=0.8, lag_days=0))
    g.add_edge(CausalEdge("recall", "leads_to", "topic_shift", confidence=0.9))
    results = g.propagate("memory_fragment")
    assert any(r["path"] == ["memory_fragment", "recall", "topic_shift"] for r in results)
    assert any(r["path"] == ["memory_fragment", "recall"] for r in results)


# ── WorldMemory ───────────────────────────────────────────────────────────────

def test_world_memory_store_and_events_for():
    wm = WorldMemory()
    wm.store({"entity": "user", "event": "asked about dogs"})
    assert len(wm.events_for("user")) == 1
    assert len(wm.events_for("other")) == 0
    assert len(wm.recent(days=7)) == 1


# ── PredictionEngine facade ───────────────────────────────────────────────────

def test_engine_predict_turn_and_snapshot():
    engine = PredictionEngine()
    result = engine.predict_turn({"prev_intent": 0.6, "user_valence": 0.4})
    assert 0.0 <= result["value"] <= 1.0
    assert len(result["forecast"]) == 3

    snap = engine.snapshot()
    assert "predictions" in snap
    assert "accuracy" in snap
    assert "beliefs" in snap
    assert "recent_events" in snap


def test_multi_horizon_forecast_ladder():
    engine = PredictionEngine()
    result = engine.predict_turn({"prev_intent": 0.6, "user_valence": 0.4})
    horizons = result.get("horizons", {}).get("horizons", {})
    assert set(horizons.keys()) == {"1h", "1d", "1w", "1m"}
    assert horizons["1h"]["uncertainty"] <= horizons["1m"]["uncertainty"]
    assert horizons["1m"]["confidence"] <= horizons["1h"]["confidence"]
    assert result["horizons"]["direction"] in ("rising", "falling", "stable")
    for h in horizons.values():
        assert 0.0 <= h["value"] <= 1.0
        assert "band" in h


# ── SynopticSmoother ──────────────────────────────────────────────────────────

def test_smoother_converges_and_tracks_velocity():
    s = SynopticSmoother(alpha=0.5)
    s.smooth({"emotion": 1.0})
    s.smooth({"emotion": 1.0})
    snap = s.snapshot()
    assert abs(snap["smoothed"]["emotion"] - 1.0) < 0.2
    assert "emotion" in snap["velocity"]


# ── Self Evaluation Engine (NEWPredictionPRT2 §3) ─────────────────────────────

def test_store_records_predicted_and_actual_value_with_error():
    store = PredictionStore()
    entry = store.add("user turn outcome", 0.8, value=0.7, domain="conversation")
    assert entry["predicted_value"] == pytest.approx(0.7)
    assert entry["error"] is None

    verified = store.verify(entry["id"], "resolved", correct=True, actual_value=0.5)
    assert verified["actual_value"] == pytest.approx(0.5)  # type: ignore
    assert verified["error"] == pytest.approx(0.2)  # |0.7 - 0.5|  # type: ignore


def test_self_evaluator_records_error_and_converges():
    from server.systems.prediction.self_evaluator import SelfEvaluator, Evaluator, LearningLoop

    # Doc §3: error = |prediction - actual|.
    assert Evaluator().evaluate(0.8, 0.3) == pytest.approx(0.5)

    loop = LearningLoop(learning_rate=0.01)
    for _ in range(12):
        loop.update(0.0)  # perfect predictions
    assert loop.convergence_rate() == pytest.approx(1.0)
    assert loop.mean_abs_error() == 0.0

    se = SelfEvaluator()
    se.record(0.8, 0.2, domain="conversation")
    se.record(0.7, 0.9, domain="conversation")
    se.record(0.5, 0.5, domain="user")
    metrics = se.metrics()
    assert metrics["mae"] == pytest.approx(round((0.6 + 0.2 + 0.0) / 3, 4))
    assert metrics["per_domain"]["conversation"] == pytest.approx(round((0.6 + 0.2) / 2, 4))
    assert metrics["n_samples"] == 3


def test_learning_loop_decays_weights_on_error():
    from server.systems.prediction.self_evaluator import LearningLoop
    loop = LearningLoop(learning_rate=0.1)
    loop.set_weight("prev_intent", 1.0)
    loop.update(0.5, feature="prev_intent")
    assert loop.weights["prev_intent"] < 1.0
    assert loop.weights["prev_intent"] == pytest.approx(1.0 * (1 - 0.1 * 0.5))
    # Convergence stays 1.0 until enough samples exist (< 10 returns 1.0).
    assert loop.convergence_rate() == 1.0


def test_engine_quantitative_verification_roundtrip():
    import tempfile, os
    from server.systems.prediction.prediction_core import PredictionEngine
    tmp = tempfile.mkdtemp()
    engine = PredictionEngine(persist_dir=f"{tmp}/pe")
    entry = engine.store.add("turn value", 0.7, domain="conversation", value=0.75)
    out = engine.verify_prediction(entry["id"], actual_value=0.4)
    assert out["quantitative"] is True
    assert out["predicted"] == pytest.approx(0.75)
    assert out["actual"] == pytest.approx(0.4)
    assert out["error"] == pytest.approx(0.35)
    assert out["self_eval"]["n_samples"] == 1
    assert engine.self_eval_metrics()["per_domain"]["conversation"] == pytest.approx(0.35)


def test_engine_quantitative_verification_unknown_id():
    from server.systems.prediction.prediction_core import PredictionEngine
    engine = PredictionEngine()
    assert engine.verify_prediction("nope", 0.5)["error"] == "unknown prediction"


def test_self_evaluator_persists_history():
    import tempfile, os
    from server.systems.prediction.self_evaluator import SelfEvaluator
    path = f"{tempfile.mkdtemp()}/self_eval.json"
    se1 = SelfEvaluator(persist_path=path)
    se1.record(0.9, 0.1, domain="general")
    se2 = SelfEvaluator(persist_path=path)
    assert se2.metrics()["n_samples"] == 1
    assert se2.metrics()["per_domain"]["general"] == pytest.approx(0.8)
    os.remove(path)


# ── Meta-policy gate (NEWPredictionPRT2 §"Meta-Policy") ───────────────────────

def test_uncertainty_score_combines_model_and_direction_mass():
    from server.systems.prediction.meta_policy.uncertainty import Uncertainty
    u = Uncertainty()
    # High model uncertainty + no dominant direction → capped near 1.0.
    assert u.score({"uncertainty": 0.8, "up": 0.1, "down": 0.1, "neutral": 0.1}) == pytest.approx(1.0)
    # Decisive forecast → low score.
    assert u.score({"uncertainty": 0.1, "up": 0.8, "down": 0.1, "neutral": 0.1}) == pytest.approx(0.3)


def test_conflict_detector_sees_up_and_down():
    from server.systems.prediction.meta_policy.conflict import ConflictDetector
    cd = ConflictDetector()
    assert cd.detect([{"direction": "up"}, {"direction": "down"}]) is True
    assert cd.detect([{"direction": "up"}, {"direction": "up"}]) is False
    assert cd.detect([{"direction": "stable"}]) is False


def test_risk_engine_scales_volatility_by_doubt():
    from server.systems.prediction.meta_policy.risk import RiskEngine
    r = RiskEngine()
    # High volatility + low confidence → high risk.
    assert r.score(0.9, 0.1) == pytest.approx(0.81)
    # High volatility but high confidence → low risk.
    assert r.score(0.9, 0.9) == pytest.approx(0.09)


def test_meta_policy_accept_when_safe():
    from server.systems.prediction.meta_policy import MetaPolicy
    d = MetaPolicy().decide({
        "uncertainty": 0.2, "confidence": 0.8,
        "volatility": 0.1, "up": 0.9, "down": 0.05, "neutral": 0.05,
    })
    assert d.action == "ACCEPT"
    assert 0.3 <= d.confidence <= 0.99
    assert d.explanation


def test_meta_policy_request_more_data_when_uncertain():
    from server.systems.prediction.meta_policy import MetaPolicy
    d = MetaPolicy().decide({"uncertainty": 0.9, "confidence": 0.1,
                             "up": 0.1, "down": 0.1, "neutral": 0.1})
    assert d.action == "REQUEST_MORE_DATA"


def test_meta_policy_caution_when_risky():
    from server.systems.prediction.meta_policy import MetaPolicy
    d = MetaPolicy().decide({"uncertainty": 0.2, "confidence": 0.1,
                             "volatility": 0.9, "up": 0.9, "down": 0.05, "neutral": 0.05})
    assert d.action == "CAUTION"


def test_meta_policy_abstain_on_conflict():
    from server.systems.prediction.meta_policy import MetaPolicy
    d = MetaPolicy().decide(
        {"uncertainty": 0.2, "confidence": 0.8, "volatility": 0.1,
         "up": 0.9, "down": 0.05, "neutral": 0.05},
        memory=[{"direction": "up"}, {"direction": "down"}],
    )
    assert d.action == "ABSTAIN"


def test_meta_policy_gate_precedence_uncertainty_over_risk():
    from server.systems.prediction.meta_policy import MetaPolicy
    # Both uncertain and risky → uncertainty wins (first rule in the doc).
    d = MetaPolicy().decide({"uncertainty": 0.9, "confidence": 0.1,
                             "volatility": 0.9, "up": 0.1, "down": 0.1, "neutral": 0.1})
    assert d.action == "REQUEST_MORE_DATA"


def test_engine_governed_predict_includes_policy():
    from server.systems.prediction.prediction_core import PredictionEngine
    eng = PredictionEngine()
    out = eng.governed_predict({"prev_intent": 0.9, "user_valence": 0.4, "trust": 0.7})
    assert out["policy"]["action"] in ("REQUEST_MORE_DATA", "CAUTION", "ABSTAIN", "ACCEPT")
    assert out["policy"]["explanation"]
    assert out["policy"]["confidence"] >= 0.0
    # SAFE features → ACCEPT is the typical result.
    safe = eng.governed_predict({"prev_intent": 0.9, "user_valence": 0.9,
                                 "trust": 0.9, "agree": 0.9})
    assert safe["policy"]["action"] == "ACCEPT"


def test_engine_govern_forecast_explains_components():
    from server.systems.prediction.prediction_core import PredictionEngine
    eng = PredictionEngine()
    out = eng.govern_forecast({
        "value": 0.5, "confidence": 0.9, "uncertainty": 0.1,
        "up": 0.9, "down": 0.05, "neutral": 0.05, "volatility": 0.1,
    })
    assert out["policy"]["action"] == "ACCEPT"
    assert out["forecast"]["value"] == 0.5
    # explain() returns the component breakdown for the dashboard.
    from server.systems.prediction.meta_policy import MetaPolicy
    detail = MetaPolicy().explain({"confidence": 0.9, "uncertainty": 0.1, "volatility": 0.1})
    assert "uncertainty" in detail["components"]
    assert "risk" in detail["components"]
    assert "conflict" in detail["components"]


# ── Learned forecast (NEWPredictionPRT2 §ForecastModel) ───────────────────────

def test_forecast_model_falls_back_when_untrained():
    from server.systems.prediction.forecast_model import ForecastModel
    fm = ForecastModel()
    assert fm.trained is False
    series = fm.predict({"value": 0.5}, steps=5)
    assert len(series) == 5
    assert all(0.0 <= v <= 1.0 for v in series)


def test_forecast_model_needs_min_samples():
    from server.systems.prediction.forecast_model import ForecastModel
    fm = ForecastModel()
    # Too few samples → not trained.
    assert fm.learn([(0.5, 0.5, 0.6), (0.6, 0.6, 0.7)]) is False
    assert fm.trained is False


def test_forecast_model_trains_on_verified_transitions():
    from server.systems.prediction.forecast_model import ForecastModel
    fm = ForecastModel()
    # Consistent linear history: next ≈ prev + 0.1.
    history = [(v, 0.6, min(1.0, v + 0.1)) for v in [0.1 * i for i in range(1, 9)]]
    assert fm.learn(history) is True
    assert fm.trained is True
    assert fm.state()["n_samples"] >= 8
    series = fm.predict({"value": 0.2, "confidence": 0.6}, steps=3)
    assert len(series) == 3
    assert all(0.0 <= v <= 1.0 for v in series)


def test_forecast_model_learn_from_store_verification():
    from server.systems.prediction.forecast_model import ForecastModel
    fm = ForecastModel()
    predictions = [
        {"verified": True, "predicted_value": 0.5, "confidence": 0.7, "actual_value": 0.6},
        {"verified": True, "predicted_value": 0.6, "confidence": 0.7, "actual_value": 0.7},
        {"verified": True, "predicted_value": 0.7, "confidence": 0.7, "actual_value": 0.8},
        {"verified": True, "predicted_value": 0.8, "confidence": 0.7, "actual_value": 0.9},
        {"verified": True, "predicted_value": 0.1, "confidence": 0.7, "actual_value": 0.2},
        {"verified": True, "predicted_value": 0.2, "confidence": 0.7, "actual_value": 0.3},
        {"verified": True, "predicted_value": 0.3, "confidence": 0.7, "actual_value": 0.4},
        {"verified": True, "predicted_value": 0.4, "confidence": 0.7, "actual_value": 0.5},
        # Unverified + no-numeric entries are skipped.
        {"verified": False, "predicted_value": 0.9, "confidence": 0.7},
        {"verified": True, "confidence": 0.7},
    ]
    assert fm.learn_from_verification(predictions) is True
    assert fm.state()["n_samples"] == 8


def test_engine_learn_forecast_and_predict():
    from server.systems.prediction.prediction_core import PredictionEngine
    import tempfile
    tmp = tempfile.mkdtemp()
    eng = PredictionEngine(persist_dir=f"{tmp}/pe")
    # Build 8 verified transitions in the store, then train.
    for i in range(8):
        v = 0.1 * (i + 1)
        e = eng.store.add(f"p{i}", 0.7, value=v)
        eng.store.verify(e["id"], "resolved", correct=True, actual_value=min(1.0, v + 0.1))
    res = eng.learn_forecast()
    assert res["trained"] is True
    assert eng.core.forecast_model.trained is True
    series = eng.core.predict_future({"value": 0.5, "confidence": 0.7}, steps=3)
    assert len(series) == 3
    assert all(0.0 <= v <= 1.0 for v in series)



