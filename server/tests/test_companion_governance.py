"""Pure tests for the gap-fill governance modules:

  * ConsentStore        — consent enforcement, age bands, freeze/reset, events
  * emotion_reason      — explainable emotion object
  * behavior_modes      — CALM/STEALTH/COMBAT resolver + latent traits
  * companion_health    — Stability Index / Over-Attachment Risk / reviewer
  * BeliefEngine        — evidence-gated promotion + consolidation

All tests are pure-Python (no DB / network), so they run anywhere.
"""

import os
import tempfile
import time

import pytest

from server.systems.governance.consent_store import (
    ConsentStore,
    VALID_AGE_BANDS,
)
from server.systems.emotion_reason import explain_emotion
from server.systems.behavior_modes import resolve_mode, BehaviorMode
from server.systems.governance.companion_health import CompanionHealth
from server.systems.prediction.prediction_core import BeliefEngine


@pytest.fixture(autouse=True)
def _fresh_data_dir():
    """Isolate every test with its own temp data dir (no cross-run pollution)."""
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["AARIYA_DATA_DIR"] = tmp
        yield
        os.environ.pop("AARIYA_DATA_DIR", None)


# ── ConsentStore ──────────────────────────────────────────────────────────────

def test_consent_defaults_granted():
    store = ConsentStore("test_user_consent_defaults")
    flags = store.feature_flags()
    assert flags["emotion_tracking"] is True
    assert flags["personality_drift"] is True
    assert flags["memory_storage"] is True
    assert flags["age_band"] in VALID_AGE_BANDS


def test_consent_revocation_is_enforced():
    store = ConsentStore("test_user_consent_enforced")
    store.set_consent("emotion_tracking", False)
    assert store.allows("emotion_tracking") is False
    assert store.allows("personality_drift") is True  # others untouched
    assert store.feature_flags()["emotion_tracking"] is False


def test_consent_invalid_category_rejected():
    store = ConsentStore("test_user_consent_invalid")
    assert store.set_consent("telemetry_selling", True) is False


def test_age_band_locked_to_18_plus():
    store = ConsentStore("test_user_age_locked")
    # 18+ is the only valid band.
    assert VALID_AGE_BANDS == ("18+",)
    assert store.age_band() == "18+"
    # Downgrades are rejected; the band can never leave 18+.
    assert store.set_age_band("13-17") is False
    assert store.set_age_band("7-12") is False
    assert store.age_band() == "18+"
    # No minor-band guardrails ever activate — emotional states pass through.
    assert store.is_minor_band() is False
    assert store.guard_emotional_state("AFFECTIONATE") == "AFFECTIONATE"
    assert store.guard_emotional_state("LONGING") == "LONGING"
    assert store.max_emotion_intensity() == 1.0


def test_freeze_and_reset():
    store = ConsentStore("test_user_freeze_reset")
    store.set_frozen(True)
    assert store.is_frozen() is True
    store.set_frozen(False)
    assert store.is_frozen() is False
    result = store.reset_personality()
    assert result["ok"] is True


def test_reliance_signals_and_events_are_chained():
    store = ConsentStore("test_user_events")
    store.record_reliance_signal("'i need you' pattern")
    store.record_reliance_signal("dependency language")
    store.set_consent("memory_storage", False)
    events = store.recent_events(10)
    categories = {e["category"] for e in events}
    assert "reliance_signal" in categories
    assert "consent_change" in categories
    # Chain hash: each event's chain links to the previous one.
    assert events[0]["chain"]
    # Every event has a chain value; last one matches stored hash.
    assert store.data["chain_hash"] == events[0]["chain"]


# ── Explainable emotion ───────────────────────────────────────────────────────

def test_emotion_reason_shape_and_hedging():
    reason = explain_emotion(
        valence=0.7, arousal=0.6, trust=0.8,
        conflict=0.1, shock=0.05, attachment=0.6,
        user_valence=0.8,
    )
    assert reason["label"] in ("WARM", "AFFECTIONATE")
    assert 0.0 <= reason["valence"] <= 1.0
    assert reason["primary_driver"] is not None
    assert any(d["signal"] == "user_emotion" for d in reason["drivers"])
    assert reason["hedged"].startswith("it seems like")
    assert 0.35 <= reason["confidence"] <= 0.95
    assert reason["reasoning"]


def test_emotion_reason_defensive_under_conflict():
    reason = explain_emotion(
        valence=-0.2, arousal=0.7, trust=0.3,
        conflict=0.8, shock=0.4,
    )
    assert any(d["signal"] == "conflict" for d in reason["drivers"])
    assert reason["label"] in ("DEFENSIVE", "COLD")


def test_emotion_reason_drivers_ranked_by_weight():
    reason = explain_emotion(
        valence=0.3, arousal=0.4, trust=0.6,
        conflict=0.6, user_valence=0.2,
    )
    weights = [d["weight"] for d in reason["drivers"]]
    assert weights == sorted(weights, reverse=True)


# ── Behavior modes ────────────────────────────────────────────────────────────

def test_mode_resolves_combat_on_high_threat():
    result = resolve_mode(valence=-0.4, arousal=0.8, trust=0.5,
                          conflict=0.3, shock=0.5, threat_level="HIGH")
    assert result["mode"] == BehaviorMode.COMBAT.value
    assert result["urgency_level"] > 0.5


def test_mode_resolves_stealth_on_low_trust():
    result = resolve_mode(valence=0.0, arousal=0.2, trust=0.2, conflict=0.1)
    assert result["mode"] == BehaviorMode.STEALTH.value
    assert "STEALTH" in result["directive"]


def test_mode_calm_baseline():
    result = resolve_mode(valence=0.1, arousal=0.3, trust=0.7, conflict=0.1)
    assert result["mode"] == BehaviorMode.CALM.value
    assert result["focus_level"] > 0.5


def test_mode_speech_and_traits_bounded():
    result = resolve_mode(valence=0.2, arousal=0.9, trust=0.6,
                          conflict=0.7, shock=0.8)
    assert 0.0 <= result["focus_level"] <= 1.0
    assert 0.0 <= result["urgency_level"] <= 1.0
    assert 0.0 <= result["speech"]["pace"] <= 2.0
    assert result["color"]


# ── Companion health ──────────────────────────────────────────────────────────

def test_health_snapshot_bounds_and_trend():
    ch = CompanionHealth("test_user_health")
    s1 = ch.compute(valence=0.5, trust=0.7, attachment=0.3, conflict=0.1,
                    reliance_signals=1, absent_days=1.0)
    assert 0.0 <= s1["stability_index"] <= 1.0
    assert 0.0 <= s1["over_attachment_risk"] <= 1.0
    assert "tone_appropriateness" in s1["reviewer"]
    assert s1["trend"]["stability_index"] == "stable"  # first snapshot

    s2 = ch.compute(valence=-0.5, trust=0.3, attachment=0.9,
                    conflict=0.6, reliance_signals=5, absent_days=10.0)
    assert s2["over_attachment_risk"] > s1["over_attachment_risk"]
    assert s2["trend"]["over_attachment_risk"] == "rising"
    assert ch.latest()["ts"] >= s1["ts"]  # type: ignore


def test_health_ring_persists_history():
    ch = CompanionHealth("test_user_health_ring")
    for i in range(5):
        ch.compute(valence=0.1 * i, trust=0.5, attachment=0.3)
    assert len(ch.history(100)) == 5


# ── BeliefEngine promotion + consolidation ────────────────────────────────────

def test_belief_promotion_is_evidence_gated():
    eng = BeliefEngine()
    # Not enough evidence → not promoted.
    eng.update("user_prefers_cats", 0.7)
    assert eng.promote("user_prefers_cats") is False
    # Enough evidence + confidence → promoted.
    eng.update("user_prefers_cats", 0.75)
    eng.update("user_prefers_cats", 0.8)
    assert eng.promote("user_prefers_cats") is True
    promoted = eng.promoted()
    assert any(p["belief"] == "user_prefers_cats" for p in promoted)
    # Evidence count tracked.
    entry = eng.beliefs["user_prefers_cats"]
    assert entry["evidence_count"] == 3


def test_belief_disconfirm_blocks_promotion():
    eng = BeliefEngine()
    eng.update("user_calm_always", 0.8)
    eng.update("user_calm_always", 0.8)
    # Promotion is sticky through noise: one gentle disconfirm keeps it.
    eng.disconfirm("user_calm_always", 0.2)
    assert eng.promote("user_calm_always") is True
    # Sustained negative evidence drags confidence below the demotion floor.
    for _ in range(4):
        eng.disconfirm("user_calm_always", 0.0)
    assert eng.promote("user_calm_always") is False


def test_belief_consolidate_merges_near_duplicates():
    eng = BeliefEngine()
    eng.update("user likes hiking", 0.7)
    eng.update("user likes hiking trails", 0.75)
    result = eng.consolidate()
    assert result["merged"] >= 1
    keys = list(eng.beliefs.keys())
    assert len(keys) == 1


# ── Companion health endpoint carries the real trait-engine bundle ─────────────

def test_health_endpoint_includes_real_trait_engine_bundle():
    """/api/compliance/health must surface the trait-engine bundle so the
    mobile Companion tab can refresh trait data over REST while idle. The
    bundle comes from the shared trait singleton, which holds the LAST real
    brain turn's state — never fabricated on request."""
    from server.systems.trait_engine import get_trait_engine
    from server.routers.compliance import companion_health

    # Drive a real trait-engine turn exactly as the brain does.
    te = get_trait_engine()
    te.update_from_turn(
        {
            "valence": 0.6,
            "arousal": 0.3,
            "trust": 0.8,
            "conflict": 0.1,
            "shock": 0.0,
            # Neutral user valence — no situational arbitration triggers, so
            # the base CALM bank shows through unchanged.
            "user_valence": 0.0,
            "uncertainty": 0.2,
        },
        {"mode": "CALM", "speech": {"pace": 1.0, "energy": 0.5}},
    )

    import asyncio
    resp = asyncio.run(companion_health(user_id="trait_rest"))

    te_out = resp["trait_engine"]
    # The real bundle: mode + 3 active traits with labels/colors + latent +
    # voice + avatar + ui — same shape the synoptic frame carries.
    assert te_out["mode"] == "CALM"
    assert len(te_out["active_traits"]) == 3
    labels = {t["label"] for t in te_out["active_traits"]}
    assert "Assertive Efficiency" in labels
    assert all(t["color"].startswith("#") for t in te_out["active_traits"])
    assert te_out["latent"]["focus_level"] > 0.7  # real formula output
    assert "speech_rate" in te_out["voice"]
    assert "Smile" in te_out["avatar"]
    assert "color_tone" in te_out["ui"]
    # Companion health + transparency still ride along.
    assert "latest" in resp and "transparency" in resp


def test_health_endpoint_trait_bundle_tracks_idle_stealth_presence():
    """The daemon's STEALTH idle presence is resolved with a FRESH engine (so
    it never clobbers the singleton's voice params) — the health endpoint must
    keep returning the singleton's last real turn, not idle-clobbered values."""
    from server.systems.trait_engine import get_trait_engine
    from server.routers.compliance import companion_health

    te = get_trait_engine()
    te.update_from_turn(
        {"valence": 0.0, "arousal": 0.1, "trust": 0.7, "conflict": 0.05},
        {"mode": "CALM"},
    )
    # Simulate the daemon's idle resolution path: fresh instance, STEALTH.
    from server.systems.trait_engine import TraitEngine
    idle = TraitEngine()
    idle.update_from_turn(
        {"valence": -0.1, "arousal": 0.05, "trust": 0.6, "conflict": 0.0},
        {"mode": "STEALTH", "speech": {"pace": 0.85, "energy": 0.2}},
    )

    import asyncio
    resp = asyncio.run(companion_health(user_id="trait_idle"))
    # Singleton still holds the CALM turn — not the idle STEALTH bundle.
    assert resp["trait_engine"]["mode"] == "CALM"
