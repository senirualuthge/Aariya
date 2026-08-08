import pytest
from unittest.mock import patch, MagicMock
from services.ml_pipeline import TrendForecaster, forecaster


@pytest.fixture
def forecaster_instance():
    f = TrendForecaster()
    f.is_loaded = True
    f._xgboost_model = None
    f._tft_model = None
    return f


class TestExtractFeatures:
    def test_basic_article(self, forecaster_instance):
        article = {"category": "tech", "importance": 8, "key_entities": ["AI", "Google"], "url": "https://reuters.com/foo", "engagement_score": 0.7, "sentiment": 0.3}
        features = forecaster_instance.extract_features(article, [])
        assert features["entity_count"] == 2
        assert features["source_credibility"] == 0.95
        assert 0 <= features["novelty_score"] <= 1

    def test_novelty_with_history(self, forecaster_instance):
        article = {"key_entities": ["AI", "OpenAI"]}
        history = [{"key_entities": ["AI", "Google"]}]
        novelty = forecaster_instance._compute_novelty(article, history)
        assert novelty == 0.5  # 1 of 2 entities known

    def test_source_credibility_unknown(self, forecaster_instance):
        assert forecaster_instance._source_credibility("https://unknown-site.com") == 0.60

    def test_source_credibility_trusted(self, forecaster_instance):
        assert forecaster_instance._source_credibility("https://reuters.com/article") == 0.95


class TestPredict:
    def test_heuristic_no_models(self, forecaster_instance):
        features = {"velocity_1h": 5, "velocity_24h": 15, "novelty_score": 0.7,
                     "source_credibility": 0.9, "entity_count": 3, "importance": 7,
                     "engagement_rate": 0.5, "source_diversity": 0.8, "burst_score": 0.6, "sentiment": 0.2}
        score = forecaster_instance.predict_importance(features)
        assert 0 <= score <= 1

    def test_breaking_probability(self, forecaster_instance):
        features = {"velocity_1h": 10, "velocity_24h": 30, "novelty_score": 0.9,
                     "source_credibility": 0.95, "entity_count": 5, "importance": 9,
                     "engagement_rate": 0.8, "source_diversity": 1.0, "burst_score": 0.9, "sentiment": -0.5}
        prob = forecaster_instance.predict_breaking_probability(features)
        assert 0 <= prob <= 1
        assert prob > 0.5  # high-importance article should have >50% breaking prob

    def test_low_breaking_probability(self, forecaster_instance):
        features = {"velocity_1h": 0, "velocity_24h": 1, "novelty_score": 0.1,
                     "source_credibility": 0.4, "entity_count": 0, "importance": 2,
                     "engagement_rate": 0.0, "source_diversity": 0.1, "burst_score": 0.0, "sentiment": 0.0}
        prob = forecaster_instance.predict_breaking_probability(features)
        assert 0 <= prob <= 1
        assert prob < 0.5


class TestHeuristic:
    def test_full_range(self, forecaster_instance):
        low = forecaster_instance._heuristic_predict({"velocity_1h": 0, "velocity_24h": 0, "novelty_score": 0, "source_credibility": 0, "entity_count": 0, "importance": 1, "engagement_rate": 0, "source_diversity": 0, "burst_score": 0, "sentiment": 0})
        high = forecaster_instance._heuristic_predict({"velocity_1h": 20, "velocity_24h": 50, "novelty_score": 1, "source_credibility": 1, "entity_count": 10, "importance": 10, "engagement_rate": 1, "source_diversity": 1, "burst_score": 1, "sentiment": 1})
        assert low < high
        assert 0 <= low <= 1
        assert 0 <= high <= 1
