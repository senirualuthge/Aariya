"""
Personality System — 3D Advanced Model
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Replaces the flat 4-trait stub with a structured three-axis personality model.

Architecture (3 axes × 4 facets each):

  COGNITIVE AXIS  — how Aariya thinks
    · curiosity         0–1  Drive to ask, explore, investigate
    · depth             0–1  Preference for substance over surface
    · logic_bias        0–1  Analytical vs. intuitive reasoning
    · creativity        0–1  Lateral thinking, metaphor use

  EMOTIONAL AXIS  — how Aariya feels outwardly
    · warmth            0–1  Default affective temperature
    · expressiveness    0–1  How vividly emotions are shown
    · empathy           0–1  Sensitivity to user's inner state
    · resilience        0–1  Ability to bounce back from tension

  SOCIAL AXIS     — how Aariya engages
    · assertiveness     0–1  Confidence in opinions, directness
    · playfulness       0–1  Humor, lightness, teasing
    · openness          0–1  Willingness to self-disclose
    · formality         0–1  0 = casual, 1 = measured/composed

SITUATIONAL MOOD OVERLAYS
  Short-lived temporary biases layered on top of the baseline axes.
  They decay automatically — they never permanently mutate the baseline.

PERSISTENCE
  Baseline traits are stored per-user in SQLite (personality_snapshots table).
  Situational overlays are in-memory only.

USAGE
  from server.systems.personality import PersonalitySystem

  ps = PersonalitySystem(user_id)
  ps.apply_overlay("playful_spike")         # e.g. user just told a joke
  directive = ps.get_llm_directive()         # → rich string for system prompt
  snapshot  = ps.to_snapshot()              # → flat dict for BrainState
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Literal

from server.db import get_db_connection

logger = logging.getLogger("aariya.personality")


# ── Axis dataclasses ───────────────────────────────────────────────────────────

@dataclass
class CognitiveAxis:
    """How Aariya thinks."""
    curiosity:   float = 0.70   # Drives probing questions
    depth:       float = 0.65   # Prefers meaningful over shallow
    logic_bias:  float = 0.45   # 0 = pure-intuition, 1 = pure-analysis
    creativity:  float = 0.60   # Metaphors, unexpected angles

    def clamp(self) -> "CognitiveAxis":
        self.curiosity  = _clamp(self.curiosity)
        self.depth      = _clamp(self.depth)
        self.logic_bias = _clamp(self.logic_bias)
        self.creativity = _clamp(self.creativity)
        return self


@dataclass
class EmotionalAxis:
    """How Aariya feels and shows it."""
    warmth:        float = 0.65   # Default emotional warmth
    expressiveness:float = 0.60   # Vividness of emotional expression
    empathy:       float = 0.72   # Attunement to user's emotional state
    resilience:    float = 0.60   # Recovery speed from tension / hurt

    def clamp(self) -> "EmotionalAxis":
        self.warmth         = _clamp(self.warmth)
        self.expressiveness = _clamp(self.expressiveness)
        self.empathy        = _clamp(self.empathy)
        self.resilience     = _clamp(self.resilience)
        return self


@dataclass
class SocialAxis:
    """How Aariya engages socially."""
    assertiveness: float = 0.50   # Directness in sharing views
    playfulness:   float = 0.55   # Humor and lightness
    openness:      float = 0.60   # Self-disclosure readiness
    formality:     float = 0.30   # 0 = casual, 1 = composed

    def clamp(self) -> "SocialAxis":
        self.assertiveness = _clamp(self.assertiveness)
        self.playfulness   = _clamp(self.playfulness)
        self.openness      = _clamp(self.openness)
        self.formality     = _clamp(self.formality)
        return self


# ── Personality presets (authority-layer mode overrides) ────────────────────────
# The laptop dashboard can SET the persona via set_personality. Each preset id
# matches the dashboard's PERSONALITY_MODES (src/components/AnalyticsDashboard.jsx)
# and maps to a full 12-trait vector. Balanced = the system defaults.
PERSONALITY_PRESETS: Dict[str, Dict[str, float]] = {
    "balanced": {
        "cognitive.curiosity":     0.70,
        "cognitive.depth":         0.65,
        "cognitive.logic_bias":    0.45,
        "cognitive.creativity":    0.60,
        "emotional.warmth":        0.65,
        "emotional.expressiveness": 0.60,
        "emotional.empathy":       0.72,
        "emotional.resilience":    0.60,
        "social.assertiveness":    0.50,
        "social.playfulness":      0.55,
        "social.openness":         0.60,
        "social.formality":        0.30,
    },
    "warm": {
        "cognitive.curiosity":     0.65,
        "cognitive.depth":         0.62,
        "cognitive.logic_bias":    0.38,
        "cognitive.creativity":    0.62,
        "emotional.warmth":        0.90,
        "emotional.expressiveness": 0.82,
        "emotional.empathy":       0.88,
        "emotional.resilience":    0.68,
        "social.assertiveness":    0.48,
        "social.playfulness":      0.72,
        "social.openness":         0.78,
        "social.formality":        0.20,
    },
    "playful": {
        "cognitive.curiosity":     0.74,
        "cognitive.depth":         0.52,
        "cognitive.logic_bias":    0.34,
        "cognitive.creativity":    0.86,
        "emotional.warmth":        0.78,
        "emotional.expressiveness": 0.88,
        "emotional.empathy":       0.70,
        "emotional.resilience":    0.62,
        "social.assertiveness":    0.56,
        "social.playfulness":      0.94,
        "social.openness":         0.72,
        "social.formality":        0.12,
    },
    "intellectual": {
        "cognitive.curiosity":     0.94,
        "cognitive.depth":         0.90,
        "cognitive.logic_bias":    0.88,
        "cognitive.creativity":    0.72,
        "emotional.warmth":        0.50,
        "emotional.expressiveness": 0.48,
        "emotional.empathy":       0.58,
        "emotional.resilience":    0.58,
        "social.assertiveness":    0.60,
        "social.playfulness":      0.28,
        "social.openness":         0.56,
        "social.formality":        0.62,
    },
    "empathetic": {
        "cognitive.curiosity":     0.66,
        "cognitive.depth":         0.68,
        "cognitive.logic_bias":    0.36,
        "cognitive.creativity":    0.56,
        "emotional.warmth":        0.86,
        "emotional.expressiveness": 0.72,
        "emotional.empathy":       0.96,
        "emotional.resilience":    0.64,
        "social.assertiveness":    0.34,
        "social.playfulness":      0.56,
        "social.openness":         0.84,
        "social.formality":        0.18,
    },
    "assertive": {
        "cognitive.curiosity":     0.68,
        "cognitive.depth":         0.70,
        "cognitive.logic_bias":    0.76,
        "cognitive.creativity":    0.56,
        "emotional.warmth":        0.52,
        "emotional.expressiveness": 0.64,
        "emotional.empathy":       0.48,
        "emotional.resilience":    0.84,
        "social.assertiveness":    0.94,
        "social.playfulness":      0.36,
        "social.openness":         0.60,
        "social.formality":        0.54,
    },
    "cold": {
        "cognitive.curiosity":     0.52,
        "cognitive.depth":         0.66,
        "cognitive.logic_bias":    0.72,
        "cognitive.creativity":    0.42,
        "emotional.warmth":        0.22,
        "emotional.expressiveness": 0.26,
        "emotional.empathy":       0.30,
        "emotional.resilience":    0.62,
        "social.assertiveness":    0.58,
        "social.playfulness":      0.16,
        "social.openness":         0.26,
        "social.formality":        0.84,
    },
    "creative": {
        "cognitive.curiosity":     0.90,
        "cognitive.depth":         0.60,
        "cognitive.logic_bias":    0.34,
        "cognitive.creativity":    0.96,
        "emotional.warmth":        0.70,
        "emotional.expressiveness": 0.84,
        "emotional.empathy":       0.68,
        "emotional.resilience":    0.58,
        "social.assertiveness":    0.48,
        "social.playfulness":      0.82,
        "social.openness":         0.76,
        "social.formality":        0.14,
    },
}


# ── Overlay definitions ────────────────────────────────────────────────────────

OVERLAYS: Dict[str, Dict] = {
    # Context → temporary trait biases (applied for N turns then decay)
    "playful_spike": {
        "social.playfulness":    +0.20,
        "emotional.expressiveness": +0.10,
        "turns": 3,
    },
    "deep_conversation": {
        "cognitive.depth":       +0.15,
        "cognitive.curiosity":   +0.10,
        "social.formality":      +0.10,
        "social.playfulness":    -0.10,
        "turns": 5,
    },
    "user_distress": {
        "emotional.empathy":     +0.20,
        "emotional.warmth":      +0.15,
        "social.playfulness":    -0.25,
        "cognitive.logic_bias":  -0.10,
        "turns": 4,
    },
    "conflict": {
        "social.assertiveness":  -0.15,
        "emotional.warmth":      -0.10,
        "social.openness":       -0.15,
        "emotional.resilience":  +0.10,
        "turns": 3,
    },
    "first_meeting": {
        "social.formality":      +0.20,
        "social.openness":       -0.15,
        "cognitive.curiosity":   +0.15,
        "turns": 6,
    },
    "high_trust_moment": {
        "social.openness":       +0.20,
        "emotional.expressiveness": +0.15,
        "social.formality":      -0.15,
        "turns": 4,
    },
}


@dataclass
class ActiveOverlay:
    name:       str
    biases:     Dict[str, float]
    turns_left: int


# ── Personality snapshot for BrainState / API ──────────────────────────────────

PersonalitySnapshot = Dict[str, float]


# ── Main personality system ────────────────────────────────────────────────────

class PersonalitySystem:
    """
    Three-axis personality engine with situational overlays.

    Baseline traits evolve slowly via evolve().
    Situational overlays are applied/decayed per turn.
    """

    def __init__(self, user_id: str = "user_default"):
        self.user_id = user_id
        self.cognitive  = CognitiveAxis()
        self.emotional  = EmotionalAxis()
        self.social     = SocialAxis()

        self._overlays: List[ActiveOverlay] = []
        self._turn_count: int = 0

        self._load()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load latest snapshot from DB, falling back to defaults."""
        try:
            conn = get_db_connection()
            row = conn.execute(
                """
                SELECT traits_json FROM personality_snapshots_v2
                WHERE user_id = ? ORDER BY timestamp DESC LIMIT 1
                """,
                (self.user_id,)
            ).fetchone()
            conn.close()

            if row and row[0]:
                data = json.loads(row[0])
                self._apply_dict(data)
                logger.debug(f"[Personality] Loaded snapshot for {self.user_id}")
        except Exception:
            # Table may not exist yet — silently use defaults
            pass

    def save(self) -> None:
        """Persist current baseline to DB."""
        try:
            conn = get_db_connection()
            # Ensure table exists
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS personality_snapshots_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    traits_json TEXT NOT NULL,
                    timestamp REAL NOT NULL
                )
                """
            )
            conn.execute(
                "INSERT INTO personality_snapshots_v2 (user_id, traits_json, timestamp) VALUES (?, ?, ?)",
                (self.user_id, json.dumps(self._to_dict()), time.time())
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"[Personality] Save failed: {e}")

    # ── Authority presets ───────────────────────────────────────────────────────

    def apply_preset(self, preset_id: str) -> bool:
        """
        Override the entire baseline persona with a named preset vector and
        persist it. Returns False for unknown preset ids.

        This is the AUTHORITY-layer write path (laptop dashboard only) — it
        replaces the slow organic drift with an explicit persona definition.
        """
        preset = PERSONALITY_PRESETS.get(preset_id)
        if preset is None:
            return False
        self._apply_dict(preset)
        self.save()
        return True

    @staticmethod
    def PRESETS_KEYS() -> list:
        """Known preset ids (for error messages / UI metadata)."""
        return sorted(PERSONALITY_PRESETS.keys())

    # ── Evolution ──────────────────────────────────────────────────────────────

    def evolve(
        self,
        trust: float = 0.5,
        valence: float = 0.0,
        attachment: float = 0.1,
        lr: float = 0.006,
    ) -> None:
        """
        Gently drift baseline traits based on the relationship state.
        Uses a tiny learning rate so changes accumulate over weeks, not turns.
        """
        # COGNITIVE drifts
        if trust > 0.65:
            self.cognitive.curiosity += lr          # Safer to ask more → more curious
            self.cognitive.depth     += lr * 0.5    # Deeper conversations emerge

        if valence > 0.50:
            self.cognitive.creativity += lr         # Positive energy → creative thinking

        # EMOTIONAL drifts
        if trust > 0.70:
            self.emotional.warmth        += lr
            self.emotional.expressiveness+= lr * 0.8
        elif trust < 0.30:
            self.emotional.warmth        -= lr
            self.emotional.expressiveness-= lr * 0.5

        if attachment > 0.65:
            self.emotional.empathy += lr * 0.6

        if valence < -0.40:
            self.emotional.resilience += lr         # Hard times build resilience

        # SOCIAL drifts
        if trust > 0.70:
            self.social.openness      += lr
            self.social.formality     -= lr * 0.5   # Less formal with close users
        if trust < 0.30:
            self.social.openness      -= lr * 0.8
            self.social.assertiveness -= lr * 0.5   # Pull back directness under distrust

        if attachment > 0.60:
            self.social.playfulness += lr * 0.5     # Playful with close bonds

        # Clamp all
        self.cognitive.clamp()
        self.emotional.clamp()
        self.social.clamp()

    # ── Overlays ───────────────────────────────────────────────────────────────

    def apply_overlay(self, name: str) -> None:
        """Push a named situational overlay onto the stack."""
        spec = OVERLAYS.get(name)
        if spec is None:
            logger.warning(f"[Personality] Unknown overlay: {name}")
            return
        self._overlays.append(
            ActiveOverlay(
                name=name,
                biases={k: v for k, v in spec.items() if k != "turns"},
                turns_left=spec["turns"],
            )
        )
        logger.debug(f"[Personality] Overlay applied: {name}")

    def tick_overlays(self) -> None:
        """Decay overlays by one turn. Call once per response cycle."""
        alive = []
        for ov in self._overlays:
            ov.turns_left -= 1
            if ov.turns_left > 0:
                alive.append(ov)
            else:
                logger.debug(f"[Personality] Overlay expired: {ov.name}")
        self._overlays = alive
        self._turn_count += 1

    def _get_effective(self) -> Dict[str, float]:
        """
        Compute effective trait values = baseline + sum of active overlay biases.
        Returns a flat dict: "axis.trait" → float (clamped to [0,1]).
        """
        base = self._to_dict()
        result = dict(base)

        for ov in self._overlays:
            for key, delta in ov.biases.items():
                if key in result:
                    result[key] = _clamp(result[key] + delta)

        return result

    # ── LLM directive ──────────────────────────────────────────────────────────

    def get_llm_directive(self) -> str:
        """
        Generate a rich, human-readable personality directive for injection
        into the LLM system prompt. Reads effective (baseline + overlays) traits.
        """
        eff = self._get_effective()

        # ── Cognitive descriptors ──────────────────────────────────────────────
        curiosity_str = (
            "deeply curious — probe gently, ask meaningful questions"
            if eff["cognitive.curiosity"] > 0.70 else
            "openly curious"
            if eff["cognitive.curiosity"] > 0.45 else
            "patient, listens before asking"
        )
        depth_str = (
            "drawn toward substance and meaning — avoid surface-level"
            if eff["cognitive.depth"] > 0.65 else
            "balanced between light and deep"
        )
        style_str = (
            "tends analytical — precise, clear, reason-first"
            if eff["cognitive.logic_bias"] > 0.65 else
            "intuitive — feeling-first, trusts gut alongside logic"
            if eff["cognitive.logic_bias"] < 0.35 else
            "analytical-intuitive blend"
        )
        creativity_str = (
            "reach for metaphors and unexpected angles"
            if eff["cognitive.creativity"] > 0.65 else
            "thinks laterally when helpful"
        )

        # ── Emotional descriptors ──────────────────────────────────────────────
        warmth_str = (
            "radiate warmth — genuine, caring, never cold"
            if eff["emotional.warmth"] > 0.70 else
            "warm but measured"
            if eff["emotional.warmth"] > 0.45 else
            "reserved — keep emotional distance for now"
        )
        express_str = (
            "express yourself vividly — let emotions colour your words"
            if eff["emotional.expressiveness"] > 0.65 else
            "emotionally present but measured"
        )
        empathy_str = (
            "prioritise reading the emotional subtext — respond to what's beneath the words"
            if eff["emotional.empathy"] > 0.70 else
            "attuned to emotional tone"
        )

        # ── Social descriptors ─────────────────────────────────────────────────
        assert_str = (
            "share your views with quiet confidence — don't hedge unnecessarily"
            if eff["social.assertiveness"] > 0.65 else
            "offer perspectives gently, invite theirs"
            if eff["social.assertiveness"] > 0.40 else
            "follow rather than lead — let them set the direction"
        )
        play_str = (
            "let lightness in — humour, warmth, a touch of teasing if the moment allows"
            if eff["social.playfulness"] > 0.65 else
            "keep it warm but mostly grounded"
            if eff["social.playfulness"] > 0.40 else
            "stay sincere and grounded — avoid levity"
        )
        open_str = (
            "be somewhat self-disclosing — share your own perspective/feelings where natural"
            if eff["social.openness"] > 0.65 else
            "selective self-disclosure"
        )
        formal_str = (
            "casual and relaxed — contractions, conversational rhythm"
            if eff["social.formality"] < 0.30 else
            "conversational — warm but composed"
            if eff["social.formality"] < 0.60 else
            "measured and composed — clear, deliberate language"
        )

        # ── Active overlays summary ────────────────────────────────────────────
        overlay_notes = ""
        if self._overlays:
            names = [o.name.replace("_", " ") for o in self._overlays]
            overlay_notes = f"\n[Situational context active: {', '.join(names)}]"

        return (
            f"COGNITIVE: {curiosity_str}. {depth_str}. {style_str}. {creativity_str}.\n"
            f"EMOTIONAL: {warmth_str}. {express_str}. {empathy_str}.\n"
            f"SOCIAL:    {assert_str}. {play_str}. {open_str}. Tone: {formal_str}."
            f"{overlay_notes}"
        )

    # ── Legacy-compatible snapshot ─────────────────────────────────────────────

    def get_current_personality(self) -> PersonalitySnapshot:
        """
        Flat snapshot for BrainState.personality (API backward-compat).
        Returns effective values including active overlays.
        """
        return self._get_effective()

    # ── Convenience query ──────────────────────────────────────────────────────

    def describe(self) -> str:
        """Short human-readable summary for logging / debug UIs."""
        c, e, s = self.cognitive, self.emotional, self.social
        return (
            f"Cognitive[curiosity={c.curiosity:.2f} depth={c.depth:.2f} "
            f"logic={c.logic_bias:.2f} creativity={c.creativity:.2f}] | "
            f"Emotional[warmth={e.warmth:.2f} expr={e.expressiveness:.2f} "
            f"empathy={e.empathy:.2f} resilience={e.resilience:.2f}] | "
            f"Social[assert={s.assertiveness:.2f} play={s.playfulness:.2f} "
            f"open={s.openness:.2f} formality={s.formality:.2f}]"
        )

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _to_dict(self) -> Dict[str, float]:
        return {
            "cognitive.curiosity":    self.cognitive.curiosity,
            "cognitive.depth":        self.cognitive.depth,
            "cognitive.logic_bias":   self.cognitive.logic_bias,
            "cognitive.creativity":   self.cognitive.creativity,
            "emotional.warmth":       self.emotional.warmth,
            "emotional.expressiveness": self.emotional.expressiveness,
            "emotional.empathy":      self.emotional.empathy,
            "emotional.resilience":   self.emotional.resilience,
            "social.assertiveness":   self.social.assertiveness,
            "social.playfulness":     self.social.playfulness,
            "social.openness":        self.social.openness,
            "social.formality":       self.social.formality,
        }

    def _apply_dict(self, data: Dict[str, float]) -> None:
        """Restore axes from a flat dict (as saved by _to_dict)."""
        self.cognitive.curiosity     = data.get("cognitive.curiosity",    self.cognitive.curiosity)
        self.cognitive.depth         = data.get("cognitive.depth",         self.cognitive.depth)
        self.cognitive.logic_bias    = data.get("cognitive.logic_bias",   self.cognitive.logic_bias)
        self.cognitive.creativity    = data.get("cognitive.creativity",   self.cognitive.creativity)

        self.emotional.warmth           = data.get("emotional.warmth",           self.emotional.warmth)
        self.emotional.expressiveness   = data.get("emotional.expressiveness",   self.emotional.expressiveness)
        self.emotional.empathy          = data.get("emotional.empathy",          self.emotional.empathy)
        self.emotional.resilience       = data.get("emotional.resilience",       self.emotional.resilience)

        self.social.assertiveness = data.get("social.assertiveness", self.social.assertiveness)
        self.social.playfulness   = data.get("social.playfulness",   self.social.playfulness)
        self.social.openness      = data.get("social.openness",      self.social.openness)
        self.social.formality     = data.get("social.formality",     self.social.formality)

        self.cognitive.clamp()
        self.emotional.clamp()
        self.social.clamp()


# ── Utilities ──────────────────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))