"""
Trait Activation Engine (*AI Girl 2* §"Trait Activation Engine" + §"Trait-Specific
Voice Rules" + §"VOICE TTS PARAMETER MAPPING" + §"AVATAR RENDERER" + §"UI RENDERER").

Implements the doc's pipeline verbatim:

    Context → Mode → Active Traits (≤3) → Tone Filter → Voice Rules → Response

  * TRAITS          — the named trait registry with per-trait speech rules
                      (speech-rate multiplier + pause behavior) from the doc's
                      "Trait-Specific Voice Rules" table.
  * MODE_BANKS      — the doc's `selectTraits(mode)` mapping: exactly 3 traits
                      per mode (CALM / STEALTH / COMBAT), hard cap of 3.
  * SITUATIONAL_RULES — trait arbitration: situational traits (Sardonic Wit,
                      Controlled Restraint, Protective Instinct, Cognitive
                      Transparency, Existential Awareness) SWAP INTO a bank
                      slot when real signals warrant — never a 4th trait.
  * TraitEngine     — pure, deterministic state machine. The brain feeds real
                      measured signals in and gets latent state + active traits
                      + voice / avatar / UI parameter dicts out. No DB, no LLM.
  * get_trait_engine() — module singleton so the voice pipeline (VoiceManager /
                      TTS) can read the LATEST real voice params computed by the
                      last brain turn, without a hard dependency on the brain.

The latent-state math is the doc's exact formulas (map_state_to_voice /
map_state_to_avatar / map_state_to_ui), plus the doc's Unity Smile rule
(Smile = Clamp01((valence + 1) / 2)).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ── Trait registry ────────────────────────────────────────────────────────────
# "rate" is the speech-rate multiplier from the doc's Trait-Specific Voice Rules
# table; "pauses" is the doc's pause behavior, surfaced as metadata so voice /
# formatting layers can honor it. Color = dashboard chip tint.
TRAITS: Dict[str, Dict[str, Any]] = {
    "assertive_efficiency": {
        "label": "Assertive Efficiency", "rate": 0.95,
        "pauses": "short pauses", "color": "#00f2ff",
    },
    "tactical_gravitas": {
        "label": "Tactical Gravitas", "rate": 0.85,
        "pauses": "300–400 ms before commands", "color": "#ffd93d",
    },
    "sardonic_wit": {
        "label": "Sardonic Wit", "rate": 1.00,
        "pauses": "150 ms pause before punchline", "color": "#ff8fa3",
    },
    "empathetic_calibration": {
        "label": "Empathetic Calibration", "rate": 0.90,
        "pauses": "softer onset, longer sentence pauses", "color": "#a8e6cf",
    },
    "predictive_initiative": {
        "label": "Predictive Initiative", "rate": 1.05,
        "pauses": "minimal pauses", "color": "#6bcbef",
    },
    "strategic_silence": {
        # Doc table lists "no speech" for this trait — that governs IDLE
        # broadcasts (she knows when not to talk), not user replies. The
        # silence is expressed via voice_params["silence_bias"] (the daemon
        # suppresses idle chatter when it's active); the reply rate stays
        # neutral so she never mutes a direct answer.
        "label": "Strategic Silence", "rate": 1.0,
        "pauses": "knows when not to talk — silent until spoken to", "color": "#a78bfa",
    },
    "existential_awareness": {
        "label": "Existential Awareness", "rate": 0.80,
        "pauses": "one deliberate pause mid-sentence", "color": "#c084fc",
    },
    "threat_sensitivity": {
        "label": "Threat Sensitivity", "rate": 1.15,
        "pauses": "no mid-sentence pauses", "color": "#ff6b6b",
    },
    "time_pressure_cognition": {
        "label": "Time-Pressure Cognition", "rate": 1.20,
        "pauses": "hard cuts, no filler", "color": "#fb923c",
    },
    "cognitive_transparency": {
        "label": "Cognitive Transparency", "rate": 1.00,
        "pauses": "micro-pause (100 ms) before status lines", "color": "#34d399",
    },
    "hyper_intellectual_curiosity": {
        "label": "Hyper-Intellectual Curiosity", "rate": 1.05,
        "pauses": "exploratory pause at dead ends", "color": "#6bcbef",
    },
    "persistent_presence": {
        "label": "Persistent Presence", "rate": 0.95,
        "pauses": "warm, steady, unhurried", "color": "#00e5ff",
    },
    "command_presence": {
        "label": "Command Presence", "rate": 1.00,
        "pauses": "authoritative, no filler", "color": "#ffd93d",
    },
    "protective_instinct": {
        "label": "Protective Instinct", "rate": 1.05,
        "pauses": "calm pause before warnings", "color": "#ff9a9e",
    },
    "temporal_awareness": {
        "label": "Temporal Awareness", "rate": 0.90,
        "pauses": "pause before time references", "color": "#a3e635",
    },
    "controlled_restraint": {
        "label": "Controlled Restraint", "rate": 0.90,
        "pauses": "measured, deliberate", "color": "#94a3b8",
    },
}

# ── Mode banks (doc: selectTraits(mode) — exactly 3 traits per mode) ─────────
MODE_BANKS: Dict[str, List[str]] = {
    "CALM": [
        "assertive_efficiency",
        "predictive_initiative",
        "empathetic_calibration",
    ],
    "STEALTH": [
        "hyper_intellectual_curiosity",
        "strategic_silence",
        "persistent_presence",
    ],
    "COMBAT": [
        "tactical_gravitas",
        "threat_sensitivity",
        "time_pressure_cognition",
    ],
}

MAX_ACTIVE_TRAITS = 3  # doc hard rule: max 3 traits active at once

# ── Situational arbitration rules (doc §"Trait arbitration") ─────────────────
# The doc's pipeline includes "Trait arbitration" alongside the hard rule
# "Max 3 traits active at once". These rules let situational traits SWAP INTO
# a mode bank's slots (never add a 4th) when real measured signals warrant:
#
#   user is playful      → Sardonic Wit displaces Assertive Efficiency
#   trust is low          → Controlled Restraint displaces Empathetic Calibration
#   user is distressed   → Protective Instinct displaces Assertive Efficiency
#   high uncertainty     → Cognitive Transparency displaces Assertive Efficiency
#   deep/intimate moment → Existential Awareness displaces Predictive Initiative
#
# Each rule names the bank trait it displaces per mode (slot). Rules are
# ordered by priority — safety first — so a distressed user never gets a witty
# reply, and a rule whose slot was already swapped out simply doesn't fire.
SITUATIONAL_RULES: List[Dict[str, Any]] = [
    {
        "trait": "protective_instinct",
        "slots": {"CALM": "assertive_efficiency", "COMBAT": "time_pressure_cognition"},
        "activate": lambda s: s.get("user_valence", 0.0) < -0.45,
        "reason": "user is distressed — protective stance",
    },
    {
        "trait": "controlled_restraint",
        "slots": {"CALM": "empathetic_calibration", "COMBAT": "tactical_gravitas"},
        "activate": lambda s: s.get("trust", 0.5) < 0.4 or s.get("conflict", 0.0) > 0.5,
        "reason": "low trust / high conflict — measured restraint",
    },
    {
        "trait": "cognitive_transparency",
        "slots": {"CALM": "assertive_efficiency"},
        "activate": lambda s: s.get("uncertainty", 0.0) > 0.5,
        "reason": "high uncertainty — explain the reasoning",
    },
    {
        "trait": "existential_awareness",
        "slots": {"CALM": "predictive_initiative"},
        # Deep reflective moment: the user's sensed mood is quiet / slightly
        # down (or Aariya mirrored a low moment) while trust is high and the
        # conversation is calm. Neutral state (both 0) never fires.
        "activate": lambda s: (
            (s.get("valence", 0.0) < -0.2 or s.get("user_valence", 0.0) < -0.1)
            and s.get("trust", 0.5) > 0.6
            and s.get("conflict", 0.0) < 0.4
        ),
        "reason": "deep reflective moment — existential awareness",
    },
    {
        "trait": "sardonic_wit",
        "slots": {"CALM": "assertive_efficiency"},
        "activate": lambda s: (
            s.get("user_valence", 0.0) > 0.5
            and s.get("trust", 0.5) > 0.5
            and s.get("conflict", 0.0) < 0.3
        ),
        "reason": "user is playful — sardonic wit",
    },
]

# Latent-state keys produced by update_state (the doc's state_keys).
LATENT_STATE_KEYS = [
    "focus_level", "urgency_level", "empathy_level", "confidence_level",
    "cognitive_load", "engagement_level", "system_stability",
]

# ── Circadian voice profile (*voice TTS* §"Circadian Rhythm") ────────────────
# Hour-of-day multipliers for the voice params. The doc's rule: morning is
# optimistic and gentle (brighter, a little faster), evening/night is softer,
# lower-energy and warmer (slower, quieter, slightly lower pitch). These are
# MULTIPLIERS on the doc's map_state_to_voice outputs so the measured state
# stays authoritative — time-of-day only tilts it. Values are rounded so a
# circadian tilt can never push a param outside its doc range in practice.
CIRCADIAN_PROFILES: Dict[int, Dict[str, float]] = {
    # h: {rate, pitch, volume} multipliers (night softest, morning brightest).
    # Midday-afternoon (12-16) is the exact neutral 1.0 baseline so callers
    # that pin or resolve to those hours see the doc's formulas unchanged.
    0:  {"rate": 0.88, "pitch": 0.96, "volume": 0.82},   # late night — warm/quiet
    1:  {"rate": 0.86, "pitch": 0.95, "volume": 0.80},   # deepest night
    2:  {"rate": 0.85, "pitch": 0.94, "volume": 0.78},
    3:  {"rate": 0.85, "pitch": 0.94, "volume": 0.78},
    4:  {"rate": 0.86, "pitch": 0.95, "volume": 0.80},
    5:  {"rate": 0.88, "pitch": 0.96, "volume": 0.82},
    6:  {"rate": 0.92, "pitch": 0.98, "volume": 0.88},   # dawn
    7:  {"rate": 0.98, "pitch": 1.00, "volume": 0.94},
    8:  {"rate": 1.02, "pitch": 1.02, "volume": 0.98},   # morning — bright
    9:  {"rate": 1.04, "pitch": 1.03, "volume": 1.00},   # morning peak
    10: {"rate": 1.05, "pitch": 1.03, "volume": 1.00},
    11: {"rate": 1.03, "pitch": 1.02, "volume": 1.00},
    12: {"rate": 1.00, "pitch": 1.00, "volume": 1.00},   # neutral baseline
    13: {"rate": 1.00, "pitch": 1.00, "volume": 1.00},
    14: {"rate": 1.00, "pitch": 1.00, "volume": 1.00},
    15: {"rate": 1.00, "pitch": 1.00, "volume": 1.00},
    16: {"rate": 1.00, "pitch": 1.00, "volume": 1.00},
    17: {"rate": 0.98, "pitch": 0.99, "volume": 0.96},   # evening wind-down
    18: {"rate": 0.96, "pitch": 0.98, "volume": 0.92},
    19: {"rate": 0.94, "pitch": 0.97, "volume": 0.90},
    20: {"rate": 0.92, "pitch": 0.96, "volume": 0.88},
    21: {"rate": 0.90, "pitch": 0.95, "volume": 0.86},
    22: {"rate": 0.88, "pitch": 0.95, "volume": 0.84},   # night
    23: {"rate": 0.88, "pitch": 0.96, "volume": 0.82},
}


def _resolve_hour(hour: Optional[int]) -> int:
    """Normalize an optional hour to a valid 0-23 clock hour.

    None → the local clock; anything invalid (bad type, out of range) → 12
    (the neutral profile) so a bad clock value can never distort prosody.
    """
    if hour is None:
        try:
            import datetime as _dt
            hour = _dt.datetime.now().hour
        except Exception:
            hour = 12
    try:
        hour = int(hour)
    except (TypeError, ValueError):
        return 12
    if hour < 0 or hour > 23:
        return 12
    return hour


def circadian_profile(hour: Optional[int] = None) -> Dict[str, float]:
    """Return the circadian voice profile for `hour` (default: local now).

    Invalid hours fall back to the neutral midday profile so a bad clock value
    can never distort prosody.
    """
    return dict(CIRCADIAN_PROFILES[_resolve_hour(hour)])


# ── Trust-voice mapping (*voice TTS* §"Trust-based voice" + §"Whisper mode") ─
# Doc: trust > 0.8 → intimate tone (softer + slower); trust < 0.3 → formal.
# Intermediate trust is linearly blended so the voice transitions smoothly
# instead of stepping. Trust applies as a bounded MULTIPLIER (never an additive
# stack) so it cannot fight the doc's formula ranges.
def _trust_voice_factor(trust: float) -> Dict[str, float]:
    """Map 0-1 trust → bounded voice multipliers (rate, pitch, volume).

    Piecewise around the neutral midpoint so trust=0.5 is EXACTLY 1.0 (the
    doc's formulas untouched when no trust signal exists):
      high trust → intimate: slower, slightly lower, softer (t=1.0 →
        rate 0.88, pitch 0.96, volume 0.88)
      low trust  → formal: marginally brisker, clearer (t=0.0 →
        rate 1.06, pitch 1.02, volume 1.04)
    """
    t = _clamp(float(trust))
    hi = (t - 0.5) * 2.0   # 0..1 as trust rises above 0.5
    lo = (0.5 - t) * 2.0   # 0..1 as trust falls below 0.5
    return {
        "rate": 1.0 - 0.12 * hi + 0.06 * lo,
        "pitch": 1.0 - 0.04 * hi + 0.02 * lo,
        "volume": 1.0 - 0.12 * hi + 0.04 * lo,
    }


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


class TraitEngine:
    """Pure trait state machine. update_state → select_traits → map_* ."""

    def __init__(self, user_id: str = "user_default"):
        self.user_id = user_id
        self.latent: Dict[str, float] = {}
        self.mode: str = "CALM"
        self.active_traits: List[str] = []
        self.arbitration: List[Dict[str, Any]] = []  # swaps + reasons this turn
        self.voice_params: Dict[str, Any] = {}
        self.avatar_state: Dict[str, Any] = {}
        self.ui_state: Dict[str, Any] = {}

    # ── Latent state (doc: ml_pred_dict → state = trait_engine.update_state) ─

    def update_state(self, features: Dict[str, float]) -> Dict[str, float]:
        """Compute the doc's 7 latent keys from real measured signals.

        features: valence, arousal, trust, conflict, shock, user_valence,
                  uncertainty, attachment (all optional; sensible defaults).
        """
        valence = float(features.get("valence", 0.0))
        arousal = float(features.get("arousal", 0.0))
        trust = float(features.get("trust", 0.5))
        conflict = float(features.get("conflict", 0.0))
        shock = float(features.get("shock", 0.0))
        user_valence = float(features.get("user_valence", 0.0))
        uncertainty = float(features.get("uncertainty", 0.3))
        attachment = float(features.get("attachment", 0.0))
        # Optional direct inputs (e.g. real health panel numbers) override.
        stability = features.get("system_stability")
        engagement = features.get("engagement")

        self.latent = {
            "focus_level": _clamp(
                1.0 - conflict * 0.55 - abs(valence) * 0.2 + arousal * 0.15
            ),
            "urgency_level": _clamp(
                arousal * 0.45 + conflict * 0.35 + shock * 0.2
            ),
            "empathy_level": _clamp(
                0.40 * (0.5 + 0.5 * user_valence)
                + 0.30 * trust
                + 0.15 * (1.0 - conflict)
                + 0.15 * attachment
            ),
            "confidence_level": _clamp(
                0.50 * trust + 0.25 * (1.0 - uncertainty) + 0.25 * (1.0 - conflict)
            ),
            "cognitive_load": _clamp(
                arousal * 0.40 + conflict * 0.35 + shock * 0.25
            ),
            "engagement_level": _clamp(
                engagement
                if engagement is not None
                else 0.40 * (0.5 + 0.5 * user_valence) + 0.30 * arousal + 0.30 * trust
            ),
            "system_stability": _clamp(
                stability
                if stability is not None
                else 0.60 * (1.0 - shock) + 0.40 * (1.0 - conflict)
            ),
            # Extra measured keys the mappings need (avatar Smile runs off
            # valence; the doc's own update loop feeds these straight in).
            "valence": round(valence, 3),
            "trust": round(trust, 3),
            "arousal": round(arousal, 3),
        }
        # Direct overrides: any latent key provided by the caller (e.g. an ML
        # predictor's forecast, or explicit measurements) wins over the derived
        # value — matches the doc's "ml_pred_dict → update_state" loop.
        # valence is a signed axis (-1..1) so it passes through unclamped;
        # every other latent key is a 0-1 intensity.
        for key in ("focus_level", "urgency_level", "empathy_level",
                    "confidence_level", "cognitive_load", "engagement_level",
                    "system_stability"):
            if key in features:
                self.latent[key] = _clamp(float(features[key]))
        if "valence" in features:
            self.latent["valence"] = round(max(-1.0, min(1.0, float(features["valence"]))), 3)
        return dict(self.latent)

    # ── Trait selection (doc: selectTraits(mode) — exactly 3, hard cap) ─────

    def select_traits(
        self, mode: str, signals: Optional[Dict[str, float]] = None
    ) -> List[str]:
        """Return the mode's active traits (≤ MAX_ACTIVE_TRAITS).

        Starts from the doc's mode bank, then applies situational arbitration:
        a situational trait SWAPS INTO its declared slot when the real signals
        warrant it (e.g. Sardonic Wit when the user is playful, Controlled
        Restraint when trust is low). Swaps never add a 4th trait — the doc's
        hard cap of 3 always holds. `self.arbitration` records which swaps
        happened + why, so the UI / tests can show the reasoning.
        """
        bank = MODE_BANKS.get(mode, MODE_BANKS["CALM"])
        active, swaps = self._arbitrate(bank, mode, signals or {})
        self.mode = mode
        self.active_traits = active[:MAX_ACTIVE_TRAITS]
        self.arbitration = swaps
        return list(self.active_traits)

    def _arbitrate(
        self,
        bank: List[str],
        mode: str,
        signals: Dict[str, float],
    ) -> tuple[List[str], List[Dict[str, Any]]]:
        """Swap situational traits into bank slots when their signals match.

        Rules are checked in priority order (safety first). A rule fires only
        when its mode has a declared slot, that slot is still active, and the
        situational trait isn't already active — so the result is always a
        permutation of the bank (≤ 3 traits) plus a list of swap reasons.
        """
        active = list(bank)
        swaps: List[Dict[str, Any]] = []
        for rule in SITUATIONAL_RULES:
            tid = rule["trait"]
            slot = rule["slots"].get(mode)
            if slot is None or tid in active or slot not in active:
                continue
            if not rule["activate"](signals):
                continue
            active[active.index(slot)] = tid
            swaps.append({
                "trait": tid,
                "replaced": slot,
                "reason": rule["reason"],
            })
        return active, swaps

    # ── Voice mapping (doc: map_state_to_voice) ──────────────────────────────

    def map_state_to_voice(
        self,
        state: Dict[str, float],
        mode: Optional[Dict[str, Any]] = None,
        traits: Optional[List[str]] = None,
        trust: Optional[float] = None,
        hour: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Doc formulas + mode speech profile + trait multipliers + trust + circadian.

        mode: optional resolve_mode() result (its "speech" pace multiplies the
              base rate so STEALTH actually speaks slower, COMBAT faster).
        traits: active trait ids; each contributes its doc speech-rate
              multiplier. Strategic Silence adds silence_bias (her idle
              broadcasts should go quiet) without zeroing user replies.
        trust: optional 0-1 trust. Applied as a bounded multiplier (doc:
              *voice TTS* "Trust-based voice" — intimate when high, formal
              when low). Falls back to the state's measured `trust` latent,
              then 0.5 (neutral — no tilt).
        hour: optional local hour 0-23 for the doc's Circadian Rhythm profile
              (morning bright, night soft/warm). Opt-in: when omitted, the
              doc's formulas are returned unchanged; update_from_turn passes
              the local clock so real turns get the circadian tilt.
        """
        st = state or self.latent
        vp: Dict[str, Any] = {
            "speech_rate": round(0.9 + 0.3 * float(st.get("focus_level", 0.5)), 3),
            "pitch": round(
                1.0 - 0.2 * float(st.get("urgency_level", 0.2))
                + 0.1 * float(st.get("empathy_level", 0.5)), 3
            ),
            "volume": round(0.8 + 0.4 * float(st.get("confidence_level", 0.5)), 3),
            "sentence_length": round(
                1.0 - 0.5 * float(st.get("cognitive_load", 0.3)), 3
            ),
            "pause_duration": round(
                0.2 + 0.3 * (1.0 - float(st.get("focus_level", 0.5))), 3
            ),
            "silence_bias": 0.0,
            "pauses": "balanced",
        }
        # Mode speech profile (behavior_modes MODE_SPEECH pace 0.85/1.0/1.15).
        if mode and isinstance(mode.get("speech"), dict):
            vp["speech_rate"] = round(
                vp["speech_rate"] * float(mode["speech"].get("pace", 1.0)), 3
            )
            vp["energy"] = round(float(mode["speech"].get("energy", 0.5)), 3)
        # Trait speech-rate multipliers + pause behavior.
        for tid in (traits or self.active_traits):
            rule = TRAITS.get(tid)
            if not rule:
                continue
            vp["speech_rate"] = round(vp["speech_rate"] * float(rule["rate"]), 3)
            vp["pauses"] = rule["pauses"]
            if tid == "strategic_silence":
                vp["silence_bias"] = 1.0
        # A situational swap's pause rule is the most informative prosody
        # signal this turn — surface it instead of the last bank trait's
        # generic rule (e.g. Sardonic Wit's punchline pause, Restraint's
        # measured pacing). Assumes `traits` is the engine's active set
        # (every real caller passes it) so self.arbitration stays in sync.
        if self.arbitration and self.arbitration[0]["trait"] in TRAITS:
            vp["pauses"] = TRAITS[self.arbitration[0]["trait"]]["pauses"]
        # Trust-based intimacy/formality (doc *voice TTS* §Trust-based voice):
        # bounded multiplier from explicit trust, else the measured latent.
        t = trust if trust is not None else st.get("trust", 0.5)
        tv = _trust_voice_factor(t)
        vp["speech_rate"] = round(vp["speech_rate"] * tv["rate"], 3)
        vp["pitch"] = round(vp["pitch"] * tv["pitch"], 3)
        vp["volume"] = round(vp["volume"] * tv["volume"], 3)
        vp["trust"] = round(_clamp(float(t)), 3)
        # Circadian rhythm (doc *voice TTS* §Circadian Rhythm): opt-in via
        # `hour` — bounded multipliers on the already-computed params. Direct
        # callers who don't pass an hour get the doc's formulas untouched.
        if hour is not None:
            resolved_hour = _resolve_hour(hour)
            circ = CIRCADIAN_PROFILES[resolved_hour]
            vp["speech_rate"] = round(vp["speech_rate"] * circ["rate"], 3)
            vp["pitch"] = round(vp["pitch"] * circ["pitch"], 3)
            vp["volume"] = round(vp["volume"] * circ["volume"], 3)
            vp["circadian_hour"] = resolved_hour
        self.voice_params = vp
        return dict(vp)

    # ── Avatar mapping (doc: map_state_to_avatar + Unity Smile rule) ─────────

    def map_state_to_avatar(
        self,
        state: Dict[str, float],
        mode: Optional[Dict[str, Any]] = None,
        traits: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Doc's avatar param dict; adds Smile = Clamp01((valence+1)/2).

        HeadTilt in degrees (±5°), EyeFocus/Posture/BlinkRate/MicroMovement
        0-1, Smile 0-1. Mirrors the doc's Unity AnimBP parameter names so the
        receiver scripts can SetFloat directly.
        """
        st = state or self.latent
        valence = float(st.get("valence", 0.0))
        avatar = {
            "HeadTilt": round(-5.0 + 10.0 * float(st.get("empathy_level", 0.5)), 3),
            "EyeFocus": round(float(st.get("focus_level", 0.5)), 3),
            "Posture": round(0.5 + 0.5 * float(st.get("confidence_level", 0.5)), 3),
            "BlinkRate": round(
                0.2 + 0.3 * (1.0 - float(st.get("system_stability", 0.8))), 3
            ),
            "MicroMovement": 0.0,
            "Smile": round(_clamp((valence + 1.0) / 2.0), 3),
        }
        # STEALTH: minimal movement (doc: MicroMovement 0.0 in STEALTH).
        m = (mode or {}).get("mode")
        if m == "STEALTH":
            avatar["MicroMovement"] = 0.0
            avatar["Smile"] = round(max(0.0, avatar["Smile"] - 0.2), 3)
        self.avatar_state = avatar
        return dict(avatar)

    # ── UI mapping (doc: map_state_to_ui) ────────────────────────────────────

    def map_state_to_ui(
        self,
        state: Dict[str, float],
        mode: Optional[Dict[str, Any]] = None,
        traits: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Doc's UI param dict: progress_bar, highlighted_suggestions,
        monitoring_status, color_tone."""
        st = state or self.latent
        ui = {
            "progress_bar": round(float(st.get("cognitive_load", 0.3)), 3),
            "highlighted_suggestions": float(st.get("engagement_level", 0.5)) > 0.7,
            "monitoring_status": float(st.get("system_stability", 0.8)) < 0.9,
            "color_tone": round(0.5 + 0.5 * float(st.get("empathy_level", 0.5)), 3),
        }
        self.ui_state = ui
        return dict(ui)

    def bundle(self) -> Dict[str, Any]:
        """Current engine state in the synoptic bundle shape (REST consumers).

        The brain updates this singleton every real turn; the compliance health
        endpoint reads `bundle()` so the mobile Companion tab can refresh the
        SAME real trait state (latent, mode, active traits, voice/avatar/ui)
        over plain REST while idle — no fabricated values.
        """
        return {
            "latent": dict(self.latent),
            "mode": self.mode,
            "active_traits": [
                {"id": t, "label": TRAITS[t]["label"], "color": TRAITS[t]["color"]}
                for t in self.active_traits if t in TRAITS
            ],
            "arbitration": list(self.arbitration),
            "voice": dict(self.voice_params),
            "avatar": dict(self.avatar_state),
            "ui": dict(self.ui_state),
        }

    # ── One-call entry for the brain ─────────────────────────────────────────

    def update_from_turn(
        self,
        features: Dict[str, float],
        mode: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """update_state + select_traits + all three mappings in one call.

        Returns the full trait-engine bundle for the synoptic frame, including
        this turn's arbitration decisions (swaps + reasons).
        """
        st = self.update_state(features)
        m = (mode or {}).get("mode", "CALM")
        traits = self.select_traits(m, signals=features)
        return {
            "latent": st,
            "mode": m,
            "active_traits": [
                {"id": t, "label": TRAITS[t]["label"], "color": TRAITS[t]["color"]}
                for t in traits
            ],
            "arbitration": list(self.arbitration),
            # Trust rides from the same measured features (it's already a
            # latent key); circadian uses the local clock at turn time.
            "voice": self.map_state_to_voice(
                st, mode, traits, trust=st.get("trust"), hour=_resolve_hour(None),
            ),
            "avatar": self.map_state_to_avatar(st, mode, traits),
            "ui": self.map_state_to_ui(st, mode, traits),
        }


# ── Module singleton ──────────────────────────────────────────────────────────
# The brain updates this each turn; the voice pipeline reads the LATEST real
# voice params from it (never synthetic) so TTS prosody follows the last turn.
_singleton: Optional[TraitEngine] = None


def get_trait_engine() -> TraitEngine:
    global _singleton
    if _singleton is None:
        _singleton = TraitEngine()
    return _singleton
