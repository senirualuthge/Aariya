"""Regression test for the /ws/mobile state.update serialization fix.

BrainState.timestamp is a timezone-aware datetime. The mobile handler used
`json.dumps(state.model_dump())`, which raised "Object of type datetime is not
JSON serializable" right after ai_response — so the Flutter orb never received
its state.update frames. `model_dump(mode="json")` (used in main.py, the
SessionManager broadcast, and the autonomy daemon snapshot) must stay
JSON-serializable.
"""

import json

from server.protocol import BrainState


def test_brain_state_json_dump_roundtrip():
    state = BrainState(valence=0.8, arousal=0.6, current_mode="focus")
    payload = state.model_dump(mode="json")

    # json.dumps must not raise on the datetime timestamp.
    encoded = json.dumps({"type": "state.update", "state": payload})
    assert encoded

    decoded = json.loads(encoded)["state"]
    assert decoded["valence"] == 0.8
    assert decoded["arousal"] == 0.6
    assert decoded["current_mode"] == "focus"
    # timestamp is serialized to an ISO string, not a datetime object.
    assert isinstance(decoded["timestamp"], str)
    assert "T" in decoded["timestamp"]


def test_brain_state_emotion_field_roundtrips():
    """The discrete emotion label must survive the wire (state.update)."""
    state = BrainState(valence=0.8, arousal=0.6, emotion="joy")
    payload = state.model_dump(mode="json")
    assert payload["emotion"] == "joy"
    assert json.loads(json.dumps({"state": payload}))["state"]["emotion"] == "joy"

    # Default stays neutral so existing consumers see no regression.
    assert BrainState().emotion == "neutral"


def test_expression_to_emotion_mapping_covers_orb_palette():
    """Every expression BrainV2 can emit must map to a label the Flutter orb
    tints on (joy→gold, calm→cyan, sadness, fear, neutral)."""
    from server.systems.brain_v2 import EXPRESSION_TO_EMOTION

    assert EXPRESSION_TO_EMOTION["joy"] == "joy"
    assert EXPRESSION_TO_EMOTION["smile"] == "calm"
    assert EXPRESSION_TO_EMOTION["concern"] == "fear"
    assert EXPRESSION_TO_EMOTION["sad"] == "sadness"
    assert EXPRESSION_TO_EMOTION["neutral"] == "neutral"
    # Unknown expressions degrade to neutral rather than crashing.
    assert EXPRESSION_TO_EMOTION.get("mystery", "neutral") == "neutral"


def test_brain_state_json_dump_handles_nested_blocks():
    state = BrainState(
        valence=-0.5,
        arousal=0.9,
        security={"last_scan": "2026-08-08T00:00:00Z", "risk": "high"},
        planetary=[{"name": "venus", "weight": 0.4}],
    )
    encoded = json.dumps({"state": state.model_dump(mode="json")})
    assert json.loads(encoded)["state"]["security"]["risk"] == "high"
