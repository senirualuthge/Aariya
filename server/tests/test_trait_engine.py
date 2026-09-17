"""Tests for the Trait Activation Engine + Transparency Satisfaction + the
doc's STEALTH-inactivity / time-pressure mode branches (*AI Girl 2*)."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["AARIYA_DATA_DIR"] = tempfile.mkdtemp(prefix="trait_test_")

from server.systems.trait_engine import (  # noqa: E402
    TraitEngine,
    get_trait_engine,
    TRAITS,
    MODE_BANKS,
    MAX_ACTIVE_TRAITS,
    LATENT_STATE_KEYS,
)
from server.systems.governance.transparency import TransparencyMonitor  # noqa: E402
from server.systems.behavior_modes import resolve_mode  # noqa: E402


# ── Registry integrity ────────────────────────────────────────────────────────

def test_mode_banks_have_exactly_three_valid_traits():
    for mode, bank in MODE_BANKS.items():
        assert len(bank) == MAX_ACTIVE_TRAITS, f"{mode} bank"
        for tid in bank:
            assert tid in TRAITS, f"{mode} bank references unknown trait {tid}"


def test_trait_voice_rules_match_doc_table():
    # Doc "Trait-Specific Voice Rules" speech-rate multipliers.
    expected = {
        "assertive_efficiency": 0.95,
        "tactical_gravitas": 0.85,
        "sardonic_wit": 1.00,
        "empathetic_calibration": 0.90,
        "predictive_initiative": 1.05,
        "existential_awareness": 0.80,
        "threat_sensitivity": 1.15,
        "time_pressure_cognition": 1.20,
        "cognitive_transparency": 1.00,
    }
    for tid, rate in expected.items():
        assert TRAITS[tid]["rate"] == rate, tid


# ── Latent state ─────────────────────────────────────────────────────────────

def test_update_state_produces_doc_latent_keys():
    te = TraitEngine()
    st = te.update_state({"valence": 0.4, "arousal": 0.3, "trust": 0.7,
                          "conflict": 0.1, "shock": 0.0, "user_valence": 0.5})
    for key in LATENT_STATE_KEYS:
        assert key in st, key
        assert 0.0 <= st[key] <= 1.0, f"{key}={st[key]}"
    # Confidence rises with trust; cognitive load rises with arousal.
    assert st["confidence_level"] > 0.5
    assert st["cognitive_load"] >= 0.12


def test_update_state_empathy_follows_user_valence():
    te = TraitEngine()
    low = te.update_state({"user_valence": -0.8, "trust": 0.5})
    high = te.update_state({"user_valence": 0.8, "trust": 0.5})
    assert high["empathy_level"] > low["empathy_level"]


# ── Trait selection (doc mode banks, hard cap 3) ─────────────────────────────

def test_select_traits_matches_doc_banks():
    te = TraitEngine()
    assert te.select_traits("CALM") == MODE_BANKS["CALM"]
    assert te.select_traits("STEALTH") == MODE_BANKS["STEALTH"]
    assert te.select_traits("COMBAT") == MODE_BANKS["COMBAT"]
    # Unknown mode falls back to CALM, never more than the cap.
    assert te.select_traits("NOPE") == MODE_BANKS["CALM"]


# ── Voice mapping ────────────────────────────────────────────────────────────

def test_map_state_to_voice_doc_formula():
    te = TraitEngine()
    te.update_state({"focus_level": 0.5, "urgency_level": 0.2,
                     "empathy_level": 0.5, "confidence_level": 0.5,
                     "cognitive_load": 0.3})
    vp = te.map_state_to_voice(te.latent)
    # speech_rate = 0.9 + 0.3*0.5 = 1.05
    assert abs(vp["speech_rate"] - 1.05) < 1e-3
    # pitch = 1.0 - 0.2*0.2 + 0.1*0.5 = 1.01
    assert abs(vp["pitch"] - 1.01) < 1e-3


def test_map_state_to_voice_applies_mode_and_trait_multipliers():
    te = TraitEngine()
    te.update_state({"focus_level": 0.5})
    # COMBAT mode pace 1.15 × threat_sensitivity 1.15 → 1.05*1.15*1.15 ≈ 1.389
    combat = {"mode": "COMBAT", "speech": {"pace": 1.15, "energy": 0.85}}
    vp = te.map_state_to_voice(te.latent, combat, ["threat_sensitivity"])
    assert abs(vp["speech_rate"] - 1.05 * 1.15 * 1.15) < 1e-2
    # STEALTH + strategic_silence → silence_bias set (doc: no speech while idle)
    stealth = {"mode": "STEALTH", "speech": {"pace": 0.85, "energy": 0.3}}
    vp2 = te.map_state_to_voice(te.latent, stealth, ["strategic_silence"])
    assert vp2["silence_bias"] == 1.0
    assert vp2["speech_rate"] < vp["speech_rate"]


# ── Avatar mapping ───────────────────────────────────────────────────────────

def test_map_state_to_avatar_smile_follows_valence():
    te = TraitEngine()
    happy = te.map_state_to_avatar(te.update_state({"valence": 0.6}))
    sad = te.map_state_to_avatar(te.update_state({"valence": -0.6}))
    # Doc Unity rule: Smile = Clamp01((mood + 1) / 2)
    assert abs(happy["Smile"] - 0.8) < 1e-3
    assert abs(sad["Smile"] - 0.2) < 1e-3
    assert -5 <= happy["HeadTilt"] <= 5


def test_map_state_to_avatar_stealth_minimizes_movement():
    te = TraitEngine()
    calm = te.map_state_to_avatar(te.update_state({"valence": 0.3}),
                                  {"mode": "CALM"})
    stealth = te.map_state_to_avatar(te.update_state({"valence": 0.3}),
                                     {"mode": "STEALTH"})
    assert calm["MicroMovement"] == 0.0
    assert stealth["Smile"] < calm["Smile"]


# ── UI mapping ───────────────────────────────────────────────────────────────

def test_map_state_to_ui_doc_fields():
    te = TraitEngine()
    ui = te.map_state_to_ui(te.update_state({
        "cognitive_load": 0.6, "engagement_level": 0.8,
        "system_stability": 0.5, "empathy_level": 0.7,
    }))
    assert abs(ui["progress_bar"] - 0.6) < 1e-3
    assert ui["highlighted_suggestions"] is True   # engagement > 0.7
    assert ui["monitoring_status"] is True          # stability < 0.9
    assert abs(ui["color_tone"] - 0.85) < 1e-3      # 0.5 + 0.5*0.7


def test_update_from_turn_returns_full_bundle():
    te = TraitEngine()
    bundle = te.update_from_turn(
        {"valence": 0.3, "trust": 0.7, "conflict": 0.0},
        {"mode": "CALM", "speech": {"pace": 1.0, "energy": 0.5}},
    )
    assert bundle["mode"] == "CALM"
    assert len(bundle["active_traits"]) == 3
    for key in ("latent", "voice", "avatar", "ui"):
        assert key in bundle


def test_singleton_voice_params_updated_by_brain_turn():
    te = get_trait_engine()
    te.update_from_turn(
        {"valence": 0.2, "trust": 0.6},
        {"mode": "CALM", "speech": {"pace": 1.0, "energy": 0.5}},
    )
    assert "speech_rate" in te.voice_params  # VoiceManager reads this


def test_fresh_instance_does_not_clobber_singleton():
    """The daemon's idle resolution uses a fresh TraitEngine() so it can never
    overwrite the brain-turn voice params the voice pipeline reads."""
    te = get_trait_engine()
    te.update_from_turn(
        {"valence": 0.8, "trust": 0.9},
        {"mode": "CALM", "speech": {"pace": 1.0, "energy": 0.5}},
    )
    brain_rate = te.voice_params["speech_rate"]
    # Daemon-style idle resolution on a fresh instance (STEALTH, low state).
    TraitEngine().update_from_turn(
        {"valence": -0.5, "trust": 0.2},
        {"mode": "STEALTH", "speech": {"pace": 0.85, "energy": 0.3}},
    )
    assert te.voice_params["speech_rate"] == brain_rate  # singleton untouched


# ── Transparency Satisfaction ────────────────────────────────────────────────

def test_transparency_implicit_from_trust_and_conflict():
    m = TransparencyMonitor("t_user")
    good = m.compute(trust=0.8, conflict=0.0, emotion_intensity=0.3)
    bad = m.compute(trust=0.4, conflict=0.6, emotion_intensity=0.9)
    assert good["transparency_satisfaction"] > bad["transparency_satisfaction"]
    assert good["dial_back"] is False


def test_transparency_discomfort_is_redline():
    m = TransparencyMonitor("t_redline")
    state = m.record_feedback(rating=0.2, discomfort=True)
    assert state["dial_back"] is True
    assert state["redline"] is True


def test_transparency_clear_dial_back():
    m = TransparencyMonitor("t_clear")
    m.record_feedback(rating=0.2, discomfort=True)
    assert m.compute()["dial_back"] is True
    m.clear_dial_back()
    assert m.compute()["dial_back"] is False


# ── Situational arbitration (swap in, hard cap 3) ───────────────────────────

def test_arbitration_playful_swaps_sardonic_wit():
    te = TraitEngine()
    traits = te.select_traits(
        "CALM",
        {"user_valence": 0.7, "trust": 0.8, "conflict": 0.1},
    )
    assert "sardonic_wit" in traits
    assert "assertive_efficiency" not in traits
    assert len(traits) == 3
    assert te.arbitration and te.arbitration[0]["trait"] == "sardonic_wit"
    assert te.arbitration[0]["replaced"] == "assertive_efficiency"


def test_arbitration_low_trust_swaps_controlled_restraint():
    te = TraitEngine()
    traits = te.select_traits("CALM", {"trust": 0.3})
    assert "controlled_restraint" in traits
    assert "empathetic_calibration" not in traits
    assert len(traits) == 3


def test_arbitration_distress_swaps_protective_instinct():
    te = TraitEngine()
    traits = te.select_traits("CALM", {"user_valence": -0.6, "trust": 0.7})
    assert "protective_instinct" in traits
    assert "assertive_efficiency" not in traits


def test_arbitration_high_uncertainty_swaps_cognitive_transparency():
    te = TraitEngine()
    traits = te.select_traits("CALM", {"uncertainty": 0.7, "trust": 0.6})
    assert "cognitive_transparency" in traits


def test_arbitration_deep_moment_swaps_existential_awareness():
    te = TraitEngine()
    traits = te.select_traits(
        "CALM", {"valence": -0.3, "trust": 0.8, "conflict": 0.0},
    )
    assert "existential_awareness" in traits
    assert "predictive_initiative" not in traits


def test_arbitration_existential_fires_on_sensed_user_mood():
    """A quiet, reflective USER (sensed mood slightly down, not Aariya's own
    valence) also triggers existential awareness."""
    te = TraitEngine()
    traits = te.select_traits(
        "CALM", {"user_valence": -0.25, "valence": 0.0, "trust": 0.8, "conflict": 0.1},
    )
    assert "existential_awareness" in traits
    # And it stays quiet when trust is low even in a deep-feeling moment.
    assert "existential_awareness" not in te.select_traits(
        "CALM", {"user_valence": -0.25, "valence": 0.0, "trust": 0.3}
    )


def test_arbitration_never_exceeds_three():
    """Multiple rules firing at once still produce a 3-trait permutation."""
    te = TraitEngine()
    # Distress (protective) + low trust (restraint) + high uncertainty
    # (transparency) + playful-ish signals all at once.
    traits = te.select_traits("CALM", {
        "user_valence": -0.6, "trust": 0.3, "conflict": 0.6,
        "uncertainty": 0.8,
    })
    assert len(traits) == 3
    assert len(set(traits)) == 3


def test_arbitration_safety_priority_over_playfulness():
    """A distressed user never gets a witty reply: protective wins the slot
    first, so sardonic_wit (same slot) cannot fire."""
    te = TraitEngine()
    # user_valence < -0.45 fires protective; also > 0.5 would fire sardonic —
    # impossible at once, so use distress + high trust to check priority path:
    traits = te.select_traits("CALM", {"user_valence": -0.6, "trust": 0.8})
    assert "protective_instinct" in traits
    assert "sardonic_wit" not in traits
    # Order of rule application is deterministic (protective listed first).
    assert te.arbitration[0]["trait"] == "protective_instinct"


def test_arbitration_respects_mode_slots():
    """Sardonic Wit has no COMBAT slot — playful signals never swap it in
    during a crisis."""
    te = TraitEngine()
    traits = te.select_traits(
        "COMBAT",
        {"user_valence": 0.7, "trust": 0.8, "conflict": 0.1},
    )
    assert traits == MODE_BANKS["COMBAT"]
    assert "sardonic_wit" not in traits
    assert te.arbitration == []


def test_arbitration_neutral_signals_no_swaps():
    te = TraitEngine()
    traits = te.select_traits("CALM", {})
    assert traits == MODE_BANKS["CALM"]
    assert te.arbitration == []


def test_arbitration_surfaces_in_bundle():
    te = TraitEngine()
    bundle = te.update_from_turn(
        {"user_valence": 0.7, "trust": 0.8, "conflict": 0.1},
        {"mode": "CALM", "speech": {"pace": 1.0, "energy": 0.5}},
    )
    assert any(a["trait"] == "sardonic_wit" for a in bundle["arbitration"])
    # Voice prosody reflects the swapped trait (doc punchline pause).
    assert bundle["voice"]["pauses"] == TRAITS["sardonic_wit"]["pauses"]


# ── Mode resolver: doc STEALTH inactivity + time-pressure COMBAT ────────────

def test_resolve_mode_stealth_after_inactivity():
    # Doc: inactivity > 30 s with low urgency → STEALTH.
    result = resolve_mode(valence=0.1, arousal=0.1, trust=0.8,
                          inactivity_seconds=60)
    assert result["mode"] == "STEALTH"
    assert "inactive" in " ".join(result["reasons"])


def test_resolve_mode_stays_calm_under_short_inactivity():
    result = resolve_mode(valence=0.1, arousal=0.1, trust=0.8,
                          inactivity_seconds=10)
    assert result["mode"] == "CALM"


def test_resolve_mode_time_pressure_combat():
    # Doc: time_pressure && (urgency > 0.7 || error_rate > 0.5) → COMBAT.
    # urgency = 0.45*arousal + 0.35*conflict + 0.2*shock = 0.715 > 0.7
    result = resolve_mode(valence=0.1, arousal=0.9, conflict=0.6, shock=0.5,
                          trust=0.8, time_pressure=True)
    assert result["mode"] == "COMBAT"
    result2 = resolve_mode(valence=0.1, arousal=0.3, trust=0.8,
                           time_pressure=True, error_rate=0.7)
    assert result2["mode"] == "COMBAT"


def test_resolve_mode_backwards_compatible_defaults():
    # Old callers without the new params behave exactly as before.
    result = resolve_mode(valence=0.1, arousal=0.3, trust=0.7, conflict=0.1)
    assert result["mode"] == "CALM"
    assert result["inactivity_seconds"] == 0.0
