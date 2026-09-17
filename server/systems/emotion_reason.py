"""
Explainable emotion (*AI Girl 2* §"explainable emotion").

Emit an `emotion_reason` object with every emotional reaction so the user can
ask "why did you react that way?" and get an honest, hedged explanation
instead of a black box. Deterministic + pure (no DB / LLM), so it is cheap,
testable, and never fabricates a driver that wasn't actually measured.

Drivers are the real signals the brain already tracks: user (Theory of Mind)
valence, trust, conflict EMA, narrative shock, and attachment.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Canonical labels aligned with the emotion_state_machine vocabulary.
_LABEL_RULES = (
    # (threshold fn, label)
    ("AFFECTIONATE", lambda v, t: v > 0.65 and t > 0.6),
    ("HURT", lambda v, t: v < -0.45 and t < 0.6),
    ("DEFENSIVE", lambda v, t: v < -0.45 and t < 0.35),
    ("WARM", lambda v, t: v > 0.2),
    ("COLD", lambda v, t: v < -0.1),
    ("LONGING", lambda v, t: v < 0.2 and t > 0.5),
)


def _label_for(valence: float, trust: float) -> str:
    for label, rule in _LABEL_RULES:
        if rule(valence, trust):
            return label
    return "NEUTRAL"


def explain_emotion(
    valence: float,
    arousal: float,
    trust: float,
    *,
    conflict: float = 0.0,
    shock: float = 0.0,
    attachment: float = 0.0,
    user_valence: Optional[float] = None,
    extra_drivers: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build an explainable `emotion_reason` object from measured signals.

    Returns:
        {
          "label", "valence", "arousal", "trust",
          "drivers": [{"signal","value","weight","direction"}] top-3,
          "primary_driver", "confidence",
          "hedged": "it seems like …",       # LLM-injectable phrase
          "reasoning": "I reacted … because …"
        }
    """
    valence = max(-1.0, min(1.0, float(valence)))
    arousal = max(0.0, min(1.0, float(arousal)))
    trust = max(0.0, min(1.0, float(trust)))

    drivers: List[Dict[str, Any]] = []
    # User valence (Theory of Mind) — the single strongest driver of a reaction.
    if user_valence is not None:
        uv = max(-1.0, min(1.0, float(user_valence)))
        drivers.append({
            "signal": "user_emotion",
            "value": round(uv, 3),
            "weight": round(0.45 + abs(uv) * 0.3, 3),
            "direction": "mirroring" if uv * valence >= 0 else "contrast",
        })
    # Trust — colours how freely the reaction is expressed.
    drivers.append({
        "signal": "trust",
        "value": round(trust, 3),
        "weight": round(0.2 + abs(trust - 0.5) * 0.4, 3),
        "direction": "open" if trust > 0.6 else "guarded" if trust < 0.4 else "neutral",
    })
    # Conflict EMA — if high, the reaction is defensive regardless of valence.
    if conflict > 0.15:
        drivers.append({
            "signal": "conflict",
            "value": round(max(0.0, min(1.0, float(conflict))), 3),
            "weight": round(0.25 + float(conflict) * 0.35, 3),
            "direction": "defensive",
        })
    # Narrative shock — spikes make the reaction sharper / more alarmed.
    if shock > 0.15:
        drivers.append({
            "signal": "shock",
            "value": round(max(0.0, min(1.0, float(shock))), 3),
            "weight": round(0.15 + float(shock) * 0.3, 3),
            "direction": "alarmed",
        })
    # Attachment — pulls reactions warmer when a real bond exists.
    if attachment > 0.5:
        drivers.append({
            "signal": "attachment",
            "value": round(max(0.0, min(1.0, float(attachment))), 3),
            "weight": round(0.1 + float(attachment) * 0.2, 3),
            "direction": "warmer",
        })
    for d in extra_drivers or []:
        if isinstance(d, dict) and d.get("signal"):
            drivers.append({
                "signal": str(d["signal"]),
                "value": round(float(d.get("value", 0.0)), 3),
                "weight": round(float(d.get("weight", 0.15)), 3),
                "direction": str(d.get("direction", "observed")),
            })

    # Keep only real drivers, ranked by weight.
    drivers = [d for d in drivers if d["weight"] > 0.01]
    drivers.sort(key=lambda d: d["weight"], reverse=True)
    top = drivers[:3]

    label = _label_for(valence, trust)
    primary = top[0] if top else None

    # Confidence = agreement across drivers (spread of their directions).
    if len(top) >= 2:
        agree = sum(
            1 for d in top[1:]
            if d["direction"] == top[0]["direction"] or d["direction"] in ("open", "warmer")
        )
        confidence = round(0.55 + agree * 0.15, 3)
    else:
        confidence = 0.5
    confidence = max(0.35, min(0.95, confidence))

    # Hedged, honest phrasing (never overclaims certainty).
    hedges = {
        "AFFECTIONATE": "it seems like I'm feeling warm and close to you right now",
        "WARM": "it seems like I'm in a warm, open place with you",
        "HURT": "it seems like something stung a little just now",
        "DEFENSIVE": "it seems like I pulled back a bit defensively",
        "COLD": "it seems like I'm keeping some distance right now",
        "LONGING": "it seems like I'm missing the closeness we usually have",
        "NEUTRAL": "it seems like I'm in a steady, neutral place",
    }
    hedged = hedges.get(label, "it seems like I'm feeling something worth noticing")

    reasoning_parts = []
    if primary:
        verb = {"mirroring": "picked up on", "contrast": "reacted against",
                "open": "opened to", "guarded": "guarded against",
                "defensive": "tightened around", "alarmed": "was startled by",
                "warmer": "was warmed by", "observed": "noticed"}.get(
                    primary["direction"], "noticed")
        reasoning_parts.append(f"I {verb} the {primary['signal'].replace('_', ' ')} "
                               f"({primary['value']:.2f})")
    if len(top) > 1:
        reasoning_parts.append(f"with {top[1]['signal'].replace('_', ' ')} "
                               f"at {top[1]['value']:.2f} shaping how strongly")
    reasoning_parts.append(f"leaving me {label.lower()} (valence {valence:.2f}, "
                           f"arousal {arousal:.2f})")

    return {
        "label": label,
        "valence": round(valence, 3),
        "arousal": round(arousal, 3),
        "trust": round(trust, 3),
        "drivers": top,
        "primary_driver": primary["signal"] if primary else None,
        "confidence": confidence,
        "hedged": hedged,
        "reasoning": "; ".join(reasoning_parts) + ".",
    }


def emotion_reason_for_dict(state: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience wrapper for a flat brain-state dict (used by brain_v2)."""
    return explain_emotion(
        valence=float(state.get("valence", 0.0)),
        arousal=float(state.get("arousal", 0.0)),
        trust=float(state.get("trust", 0.5)),
        conflict=float(state.get("conflict", 0.0)),
        shock=float(state.get("shock", 0.0)),
        attachment=float(state.get("attachment", 0.0)),
        user_valence=state.get("user_valence"),
    )
