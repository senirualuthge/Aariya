"""Tests for the trust input of `ContradictionDetector`.

Wave‑2 G3: `process_turn` previously fed a *fabricated* trust of 1.0 into
`calculate_trust_decay` ("Placeholder trust"). It now takes the real trust and
the decay delta is floored so an applied decay can never push trust below zero.
"""

import pytest

from server.systems import contradiction_detector as cd_mod


class _FakeRedis:
    """In-memory stand-in for the contradiction-EMA cache."""

    def __init__(self):
        self.store = {}

    def get_contradiction_history(self, user_id):
        return self.store.get(user_id)

    def set_contradiction_history(self, user_id, ema):
        self.store[user_id] = float(ema)


class _FakeDB:
    def execute_update(self, *args, **kwargs):  # noqa: ARG002
        return None


@pytest.fixture()
def detector(monkeypatch):
    """A detector wired to in-memory stores (no Redis/Postgres needed)."""
    monkeypatch.setattr(cd_mod, "get_postgres", lambda: _FakeDB())
    monkeypatch.setattr(cd_mod, "get_redis", lambda: _FakeRedis())
    return cd_mod.ContradictionDetector()


def test_trust_decay_uses_current_trust_as_floor(detector):
    # Healthy trust → the full formula (-lambda * C_history).
    assert detector.calculate_trust_decay(0.9, 1.0) == pytest.approx(-0.03)
    # Near-zero trust → floored, so the applied decay can't go below 0.
    assert detector.calculate_trust_decay(0.005, 1.0) == pytest.approx(-0.005)
    # No contradiction → no decay regardless of trust.
    assert detector.calculate_trust_decay(0.0, 0.0) == 0.0


def test_process_turn_threads_real_trust(detector):
    kwargs = dict(
        user_id="u1",
        session_id="s1",
        turn_number=1,
        face_emotion={"valence": 0.9, "arousal": 0.1},
        voice_emotion={"valence": -0.9, "arousal": 0.9},
        text_sentiment=0.8,
        confidences={"face": 0.9, "voice": 0.9, "text": 0.9},
    )

    # beta=1.0 so the turn's contradiction score becomes the EMA immediately,
    # which is large enough for the trust floor to bite.
    low = cd_mod.ContradictionDetector(beta=1.0).process_turn(trust=0.001, **kwargs)
    assert low["contradiction_ema"] > 0.3
    # A near-zero trust floors the decay pressure at -trust.
    assert low["trust_decay_pressure"] == pytest.approx(-0.001)

    # With healthy trust the full formula applies.
    high = cd_mod.ContradictionDetector(beta=1.0).process_turn(trust=0.9, **kwargs)
    assert high["trust_decay_pressure"] == pytest.approx(
        -detector.lambda_decay * high["contradiction_ema"]
    )


def test_process_turn_defaults_to_full_trust(detector):
    """Omitting `trust` keeps the historical behaviour (full trust)."""
    result = detector.process_turn(
        user_id="u2",
        session_id="s2",
        turn_number=1,
        face_emotion={"valence": 0.5, "arousal": 0.0},
        voice_emotion={"valence": -0.5, "arousal": 0.0},
        text_sentiment=0.5,
        confidences={"face": 0.5, "voice": 0.5, "text": 0.5},
    )
    assert result["trust_decay_pressure"] == pytest.approx(
        -detector.lambda_decay * result["contradiction_ema"]
    )
