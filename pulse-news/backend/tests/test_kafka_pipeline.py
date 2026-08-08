import pytest
from kafka_pipeline import KafkaManager, TOPICS


class TestKafkaManager:
    @pytest.fixture
    def km(self):
        m = KafkaManager()
        m.is_connected = False  # don't actually connect
        return m

    def test_topics_defined(self):
        assert "raw" in TOPICS
        assert "cleaned" in TOPICS
        assert "chunks" in TOPICS
        assert "nlu_entities" in TOPICS
        assert "nlu_topics" in TOPICS
        assert "embedding" in TOPICS
        assert "trend_signals" in TOPICS
        assert "trend_snapshots" in TOPICS
        assert "trend_predictions" in TOPICS
        assert "alerts" in TOPICS
        assert "user_events" in TOPICS
        assert "dlq" in TOPICS

    def test_publish_noop_when_disconnected(self, km):
        import asyncio
        asyncio.run(km.publish("test", {}))
        # Should not raise

    def test_publish_raw_article_noop_when_disconnected(self, km):
        import asyncio
        asyncio.run(km.publish_raw_article({"id": "1"}))
        # Should not raise

    def test_publish_alert_noop_when_disconnected(self, km):
        import asyncio
        asyncio.run(km.publish_alert({"id": "1"}))
        # Should not raise

    def test_publish_user_event_noop_when_disconnected(self, km):
        import asyncio
        asyncio.run(km.publish_user_event({"user_id": "test", "event_type": "click"}))
        # Should not raise

    def test_publish_trend_signal_noop_when_disconnected(self, km):
        import asyncio
        asyncio.run(km.publish_trend_signal({"category": "tech"}))
        # Should not raise
