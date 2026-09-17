"""Tests for the new synoptic v2 modules: cognitive_field, goal_system,
narrative_engine, narrative_arcs, meta_cognition, synoptic_engine."""

import time

import pytest

from server.systems.cognitive_field import (
    INFLUENCE_MATRIX,
    apply_cognitive_influence,
    predict_domains,
)
from server.systems.goal_system import (
    GOAL_TEMPLATES,
    GoalSystem,
    apply_actions,
    create_plan,
    generate_goals,
)
from server.systems.narrative_engine import NarrativeEngine, create_event
from server.systems.narrative_arcs import (
    BASE_PERSONALITY,
    NarrativeArc,
    NarrativeArcEngine,
    apply_personality_drift,
    stabilize_personality,
)
from server.systems.meta_cognition import (
    ReflectionState,
    MetaCognitionEngine,
    compute_alignment,
    compute_drift,
    compute_reflection,
)
from server.systems.synoptic_engine import SynopticDynamics, SynopticEngine


# ── cognitive_field ─────────────────────────────────────────────────────────────

def test_influence_matrix_has_domains():
    for src in ("reasoning", "emotion", "memory"):
        assert src in INFLUENCE_MATRIX


def test_apply_cognitive_influence_normalizes():
    domains = {"reasoning": 0.5, "emotion": 0.5, "memory": 0.0, "risk": 0.0}
    out = apply_cognitive_influence(domains)
    assert all(v >= 0.0 for v in out.values())
    assert abs(sum(out.values()) - 1.0) < 1e-6
    # cross-domain influence may surface new keys (e.g. emotion→personality)
    assert set(domains) <= set(out)


def test_predict_domains_clamps_and_keeps_shape():
    domains = {"reasoning": 0.5, "emotion": 0.3, "memory": 0.2}
    velocity = {"reasoning": 0.1, "emotion": -0.05, "memory": 0.0}
    pred = predict_domains(domains, velocity)
    assert set(pred) == set(domains)
    assert all(0.0 <= v <= 1.0 for v in pred.values())


# ── goal_system ────────────────────────────────────────────────────────────────

def test_goal_templates_defined():
    assert set(GOAL_TEMPLATES) == {
        "stabilize", "build_trust", "increase_curiosity", "reduce_risk"}


def test_generate_goals_returns_sorted_by_priority():
    reflection = ReflectionState(
        coherence=0.4, stability=0.2, alignment=0.4, drift=0.35)
    arcs = {"conflict_arc": NarrativeArc(id="conflict", arc_type="conflict", strength=0.8, trend=0.3,
                                         event_count=4)}
    goals = generate_goals(reflection, arcs)
    assert 0 < len(goals) <= 6
    priorities = [g.priority for g in goals]
    assert priorities == sorted(priorities, reverse=True)


def test_create_plan_and_apply_actions():
    reflection = ReflectionState(0.5, 0.3, 0.5, 0.1)  # low stability → goals
    goals = generate_goals(reflection, {})
    assert goals
    plan = create_plan(goals[0])
    assert plan.actions
    domains = {"reasoning": 0.5, "emotion": 0.5}
    personality = dict(BASE_PERSONALITY)
    out_d, out_p = apply_actions(domains, personality, plan.actions)
    assert all(0.0 <= v <= 1.0 for v in out_d.values())
    assert all(0.0 <= v <= 1.0 for v in out_p.values())


def test_goal_system_step_returns_quadruple():
    gs = GoalSystem()
    reflection = ReflectionState(0.5, 0.5, 0.6, 0.2)
    arcs = {}
    domains = {"reasoning": 0.5, "emotion": 0.5}
    personality = dict(BASE_PERSONALITY)
    goal, plan, doms, pers = gs.step(reflection, arcs, domains, personality)
    assert doms and pers
    if goal is not None:
        assert plan is not None
        assert 0.0 <= goal.progress <= 1.0


# ── narrative_engine ───────────────────────────────────────────────────────────

def test_create_event_classifies_question():
    ev = create_event("Is the sky blue?", emotion_valence=0.0,
                      contradiction_level=0.0)
    assert ev.event_type == "question"
    assert ev.domain_impact.get("reasoning", 0) > 0
    assert ev.domain_impact.get("memory", 0) > 0


def test_compute_shock_returns_domain_effects():
    eng = NarrativeEngine(decay=1.5)
    eng.add_event(create_event("I am so sad", emotion_valence=-0.9,
                               contradiction_level=0.7))
    shock = eng.compute_shock()
    assert isinstance(shock, dict)
    assert any(abs(v) > 0 for v in shock.values())
    # scalar legacy still available
    assert isinstance(eng.compute_shock_scalar(), float)


# ── narrative_arcs ─────────────────────────────────────────────────────────────

def test_arc_engine_update_and_decay():
    eng = NarrativeArcEngine()
    eng.update(create_event("Why do you keep lying", emotion_valence=-0.9,
                            contradiction_level=0.7))
    eng.update(create_event("I do not trust you anymore", emotion_valence=-0.8,
                            contradiction_level=0.65))
    dom = eng.get_dominant()
    assert dom is not None
    assert dom.arc_type == "conflict_arc"
    assert dom.event_count >= 2
    eng.decay_arcs()
    assert eng.get_dominant().strength <= dom.strength  # type: ignore


def test_personality_drift_and_stabilize_bounded():
    arcs = {"conflict_arc": NarrativeArc(id="conflict_arc", arc_type="conflict_arc",
                                         strength=0.8, trend=0.3, event_count=4)}
    drifted = apply_personality_drift(dict(BASE_PERSONALITY), arcs)
    assert all(0.0 <= v <= 1.0 for v in drifted.values())
    stabilized = stabilize_personality(drifted)
    assert all(0.0 <= v <= 1.0 for v in stabilized.values())


# ── meta_cognition ─────────────────────────────────────────────────────────────

def test_compute_reflection_metrics():
    synoptic = {"coherence": 0.6, "conflict": 0.4}
    arcs = {}
    personality = dict(BASE_PERSONALITY)
    ref = compute_reflection(synoptic, arcs, personality)
    assert 0.0 <= ref.coherence <= 1.0
    assert ref.stability == pytest.approx(0.6)
    assert 0.0 <= ref.drift <= 1.0


def test_decide_respects_cooldown():
    eng = MetaCognitionEngine(cooldown=2.0)
    ref = ReflectionState(coherence=0.3, stability=0.2, alignment=0.3,
                          drift=0.5)
    actions = eng.decide(ref)
    assert actions
    # immediate second call within cooldown → no new actions
    assert eng.decide(ref) == []
    eng.last_adjustment = 0.0
    assert eng.decide(ref)


def test_apply_adjustments():
    eng = MetaCognitionEngine(cooldown=0.0)
    domains = {"reasoning": 0.9, "emotion": 0.1}
    personality = {"empathy": 0.9, "curiosity": 0.1}
    arcs = {"conflict_arc": NarrativeArc(id="conflict", arc_type="conflict", strength=0.5, trend=0.0,
                                         event_count=1)}
    doms, pers = eng.apply([("realign_personality", 0.03), ("stabilize_system",
                                                             0.05)],
                           domains, personality, arcs)
    assert all(0.0 <= v <= 1.0 for v in doms.values())
    assert all(0.0 <= v <= 1.0 for v in pers.values())


def test_compute_alignment_conflict_arc_reduces():
    arcs = {"conflict_arc": NarrativeArc(id="conflict", arc_type="conflict", strength=0.9, trend=0.0,
                                         event_count=1)}
    low = compute_alignment(arcs, {"empathy": 0.9, "curiosity": 0.5})
    high = compute_alignment(arcs, {"empathy": 0.1, "curiosity": 0.5})
    assert low < high


# ── synoptic_engine ────────────────────────────────────────────────────────────

def test_synoptic_dynamics_tracks_velocity():
    dyn = SynopticDynamics()
    v1 = dyn.update({"a": 1.0, "b": 0.5})
    v2 = dyn.update({"a": 1.2, "b": 0.4})
    assert v2["a"] == pytest.approx(0.2)
    assert v2["b"] == pytest.approx(-0.1)


def test_compute_synoptic_full_pipeline():
    eng = SynopticEngine()
    nar = NarrativeEngine(decay=1.5)
    nar.add_event(create_event("I am worried", emotion_valence=-0.5,
                               contradiction_level=0.4))
    result = eng.compute_synoptic(
        {"reasoning": 0.6, "emotion": 0.4},
        narrative_engine=nar,
        arcs={},
    )
    assert set(result) >= {"domains", "dominant", "coherence", "conflict",
                           "trend", "shock", "predicted"}
    assert abs(sum(result["domains"].values()) - 1.0) < 0.01
    assert result["dominant"] in result["domains"]


def test_compute_synoptic_folds_agent_keys():
    eng = SynopticEngine()
    result = eng.compute_synoptic({"strategy": 0.8, "empathy": 0.2})
    assert result["domains"]


def test_to_planets_includes_velocity():
    eng = SynopticEngine()
    result = eng.compute_synoptic({"reasoning": 0.6, "emotion": 0.4})
    planets = eng.to_planets(result)
    assert planets
    for p in planets:
        assert "velocity" in p
        assert "activation" in p
        assert 0.0 <= p["activation"] <= 1.0
