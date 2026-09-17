"""
Tests for Long-Term Trust Decay on Absence.

Covers:
- Exponential decay formula
- Grace period (no decay for first 3 days)
- Baseline drift (decays toward 0.5, not zero)
- Return reinforcement
- Absence categories and greeting styles
- Edge cases (first interaction, zero absence, very long absence)
"""

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.systems.trust_system import TrustSystem


class FakeRedis:
    """In-memory Redis mock for isolated trust decay testing."""
    def __init__(self, store, ts_store):
        self._store = store
        self._ts = ts_store

    def get_trust_score(self, uid):
        return self._store.get(uid)

    def set_trust_score(self, uid, score):
        self._store[uid] = score

    def get(self, key):
        return self._ts.get(key)

    def set(self, key, val):
        self._ts[key] = val


class TestTrustDecayFormula:
    """Core decay math: trust drifts toward baseline over time."""

    def setup_method(self):
        self.ts = TrustSystem()
        self._store = {}
        self._ts = {}
        self.ts.redis = FakeRedis(self._store, self._ts)

    def test_no_decay_within_grace_period(self):
        self._store["u1"] = 0.8
        self._ts["trust:last_interaction:u1"] = str(time.time() - 2 * 86400)
        assert self.ts.get_trust_score("u1") == 0.8

    def test_decay_after_grace_period(self):
        self._store["u1"] = 0.8
        self._ts["trust:last_interaction:u1"] = str(time.time() - 13 * 86400)
        trust = self.ts.get_trust_score("u1")
        expected = 0.5 + (0.8 - 0.5) * (1 - 0.02) ** 10
        assert abs(trust - expected) < 0.001

    def test_decay_toward_baseline_not_zero(self):
        self._store["u1"] = 0.9
        self._ts["trust:last_interaction:u1"] = str(time.time() - 30 * 86400)
        trust = self.ts.get_trust_score("u1")
        assert trust > 0.5
        expected = 0.5 + (0.9 - 0.5) * (1 - 0.02) ** 27
        assert abs(trust - expected) < 0.002

    def test_low_trust_decays_upward_toward_baseline(self):
        self._store["u1"] = 0.2
        self._ts["trust:last_interaction:u1"] = str(time.time() - 30 * 86400)
        trust = self.ts.get_trust_score("u1")
        assert 0.2 < trust < 0.5
        expected = 0.5 + (0.2 - 0.5) * (1 - 0.02) ** 27
        assert abs(trust - expected) < 0.002

    def test_very_long_absence_approaches_baseline(self):
        self._store["u1"] = 0.95
        self._ts["trust:last_interaction:u1"] = str(time.time() - 180 * 86400)
        trust = self.ts.get_trust_score("u1")
        assert abs(trust - 0.5) < 0.05

    def test_baseline_trust_no_decay(self):
        self._store["u1"] = 0.5
        self._ts["trust:last_interaction:u1"] = str(time.time() - 100 * 86400)
        assert self.ts.get_trust_score("u1") == 0.5


class TestTrustDecayGracePeriod:

    def setup_method(self):
        self.ts = TrustSystem()
        self._store = {}
        self._ts = {}
        self.ts.redis = FakeRedis(self._store, self._ts)

    def test_exactly_grace_period_no_decay(self):
        self._store["u1"] = 0.7
        self._ts["trust:last_interaction:u1"] = str(time.time() - 3 * 86400)
        assert self.ts.get_trust_score("u1") == 0.7

    def test_one_day_beyond_grace_starts_decaying(self):
        self._store["u1"] = 0.7
        self._ts["trust:last_interaction:u1"] = str(time.time() - 4 * 86400)
        trust = self.ts.get_trust_score("u1")
        expected = 0.5 + (0.7 - 0.5) * (1 - 0.02) ** 1
        assert abs(trust - expected) < 0.001


class TestTrustDecayFirstInteraction:

    def setup_method(self):
        self.ts = TrustSystem()
        self._store = {}
        self._ts = {}
        self.ts.redis = FakeRedis(self._store, self._ts)

    def test_first_interaction_no_decay(self):
        self._store["new_user"] = 0.5
        trust = self.ts.get_trust_score("new_user")
        assert trust == 0.5
        assert "trust:last_interaction:new_user" in self._ts


class TestRecordInteraction:

    def setup_method(self):
        self.ts = TrustSystem()
        self._store = {}
        self._ts = {}
        self.ts.redis = FakeRedis(self._store, self._ts)

    def test_first_interaction(self):
        self._store["u1"] = 0.5
        result = self.ts.record_interaction("u1")
        assert result["days_absent"] == 0.0
        assert result["absence_category"] == "none"
        assert result["greeting_style"] == "normal"
        assert result["decay_applied"] is False

    def test_brief_absence(self):
        self._store["u1"] = 0.7
        self._ts["trust:last_interaction:u1"] = str(time.time() - 1 * 86400)
        result = self.ts.record_interaction("u1")
        assert result["absence_category"] == "brief"
        assert result["greeting_style"] == "normal"
        assert result["decay_applied"] is False

    def test_moderate_absence(self):
        self._store["u1"] = 0.7
        self._ts["trust:last_interaction:u1"] = str(time.time() - 5 * 86400)
        result = self.ts.record_interaction("u1")
        assert result["absence_category"] == "moderate"

    def test_long_absence_low_trust_cautious(self):
        self._store["u1"] = 0.3
        self._ts["trust:last_interaction:u1"] = str(time.time() - 14 * 86400)
        result = self.ts.record_interaction("u1")
        assert result["absence_category"] == "long"
        assert result["greeting_style"] == "cautious_welcome"
        assert result["decay_applied"] is True

    def test_long_absence_high_trust_warm(self):
        self._store["u1"] = 0.85
        self._ts["trust:last_interaction:u1"] = str(time.time() - 14 * 86400)
        result = self.ts.record_interaction("u1")
        assert result["absence_category"] == "long"
        assert result["greeting_style"] == "warm_familiar"
        assert result["decay_applied"] is True

    def test_extended_absence_polite(self):
        self._store["u1"] = 0.55
        self._ts["trust:last_interaction:u1"] = str(time.time() - 40 * 86400)
        result = self.ts.record_interaction("u1")
        assert result["absence_category"] == "extended"
        assert result["greeting_style"] == "polite_welcome"

    def test_return_reinforcement(self):
        self._store["u1"] = 0.7
        self._ts["trust:last_interaction:u1"] = str(time.time() - 14 * 86400)
        result = self.ts.record_interaction("u1")
        decayed = result["trust_after_decay"]
        stored = self._store.get("u1")
        # After reinforcement, stored should be decayed + 0.02 (capped at 1.0)
        assert abs(stored - (decayed + 0.02)) < 0.001 or stored == 1.0

    def test_reinforcement_caps_at_1(self):
        self._store["u1"] = 0.99
        self._ts["trust:last_interaction:u1"] = str(time.time() - 4 * 86400)
        result = self.ts.record_interaction("u1")
        assert self._store.get("u1") <= 1.0

    def test_reinforcement_only_after_grace_period(self):
        self._store["u1"] = 0.7
        self._ts["trust:last_interaction:u1"] = str(time.time() - 2 * 86400)
        result = self.ts.record_interaction("u1")
        assert result["decay_applied"] is False
        assert result["greeting_style"] == "normal"

    def test_absence_categories_boundary(self):
        """Test boundaries: int(days) determines category."""
        self._store["u1"] = 0.5

        # 1 day = brief
        self._ts["trust:last_interaction:u1"] = str(time.time() - 1 * 86400)
        assert self.ts.record_interaction("u1")["absence_category"] == "brief"

        # 2 days = brief
        self._ts["trust:last_interaction:u1"] = str(time.time() - 2 * 86400)
        assert self.ts.record_interaction("u1")["absence_category"] == "brief"

        # 3 days = moderate
        self._ts["trust:last_interaction:u1"] = str(time.time() - 3 * 86400)
        assert self.ts.record_interaction("u1")["absence_category"] == "moderate"

        # 4 days = moderate
        self._ts["trust:last_interaction:u1"] = str(time.time() - 4 * 86400)
        assert self.ts.record_interaction("u1")["absence_category"] == "moderate"

        # 7 days = long
        self._ts["trust:last_interaction:u1"] = str(time.time() - 7 * 86400)
        assert self.ts.record_interaction("u1")["absence_category"] == "long"

        # 8 days = long
        self._ts["trust:last_interaction:u1"] = str(time.time() - 8 * 86400)
        assert self.ts.record_interaction("u1")["absence_category"] == "long"

        # 30 days = extended
        self._ts["trust:last_interaction:u1"] = str(time.time() - 30 * 86400)
        assert self.ts.record_interaction("u1")["absence_category"] == "extended"

        # 31 days = extended
        self._ts["trust:last_interaction:u1"] = str(time.time() - 31 * 86400)
        assert self.ts.record_interaction("u1")["absence_category"] == "extended"
