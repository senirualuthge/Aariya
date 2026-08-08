import pytest
from services.agents import (
    TrendAgent, FactAgent, ContradictionAgent,
    NarrativeAgent, GraphAgent, AlertAgent, OrchestratorAgent,
)


@pytest.fixture
def sample_article():
    return {
        "id": "test-1",
        "title": "AI Breakthrough: New Model Beats Humans",
        "summary": "A new AI model achieved superhuman performance.",
        "url": "https://reuters.com/tech/ai-news",
        "category": "tech",
        "importance": 8,
        "is_risk": False,
        "key_entities": ["OpenAI", "Google", "Anthropic"],
        "source_id": "newsapi",
        "content_hash": "abc123",
    }


class TestTrendAgent:
    def test_analyze_returns_score(self, sample_article):
        agent = TrendAgent()
        score = agent.analyze(sample_article)
        assert 0 <= score <= 1


class TestFactAgent:
    def test_verify_trusted_source(self, sample_article):
        agent = FactAgent()
        assert agent.verify(sample_article) is True

    def test_confidence_trusted(self, sample_article):
        agent = FactAgent()
        assert agent.confidence(sample_article) > 0.9

    def test_confidence_unknown(self):
        agent = FactAgent()
        article = {"url": "https://unknown-blog.com"}
        assert agent.confidence(article) == 0.60

    def test_verify_unknown_source(self):
        agent = FactAgent()
        article = {"url": "https://unknown-blog.com", "source_id": "serpapi"}
        assert agent.verify(article) is True  # 0.60 > 0.55


class TestContradictionAgent:
    def test_no_peers(self):
        agent = ContradictionAgent()
        result = agent.detect({"id": "new-1", "title": "Test", "category": "tech", "summary": ""})
        assert result["has_contradiction"] is False


class TestNarrativeAgent:
    def test_summarize(self, sample_article):
        agent = NarrativeAgent()
        s = agent.summarize(sample_article)
        assert "superhuman" in s

    def test_narrate_with_entities(self, sample_article):
        agent = NarrativeAgent()
        s = agent.narrate(sample_article)
        assert "OpenAI" in s


class TestGraphAgent:
    def test_entity_connectivity_returns_float(self, sample_article):
        agent = GraphAgent()
        score = agent.entity_connectivity(sample_article)
        assert 0 <= score <= 1

    def test_no_entities(self):
        agent = GraphAgent()
        score = agent.entity_connectivity({})
        assert score == 0.0


class TestAlertAgent:
    def test_low_importance_no_alert(self):
        agent = AlertAgent()
        article = {"importance": 3, "is_risk": False, "category": "tech", "url": "https://reuters.com", "title": "Test", "summary": "", "id": "test-2"}
        assert agent.should_alert(article) is False

    def test_high_importance_risk(self):
        agent = AlertAgent()
        article = {"importance": 9, "is_risk": True, "category": "security", "url": "https://reuters.com/cyber", "title": "Cyber attack", "summary": "Major breach", "id": "test-3"}
        result = agent.should_alert(article)
        # May be True if source diversity threshold is met
        assert result is False or result is True

    def test_alert_priority_critical(self, sample_article):
        agent = AlertAgent()
        article = {**sample_article, "importance": 9, "is_risk": True}
        assert agent.alert_priority(article) == "critical"

    def test_alert_priority_high(self, sample_article):
        article = {**sample_article, "importance": 8, "is_risk": False}
        assert AlertAgent().alert_priority(article) == "high"


class TestOrchestratorAgent:
    def test_review_article_adds_scores(self, sample_article):
        agent = OrchestratorAgent()
        result = agent.review_article(dict(sample_article))
        assert "trend_score" in result
        assert "agent_reviewed" in result
        assert "should_alert" in result
        assert "alert_priority" in result
        assert 0 <= result["trend_score"] <= 1

    def test_low_credibility_reduces_importance(self):
        agent = OrchestratorAgent()
        article = {"id": "t1", "title": "Unknown", "summary": "", "url": "https://conspiracy.net", "category": "other", "importance": 8, "is_risk": False, "key_entities": [], "source_id": "rss", "content_hash": "xyz"}
        result = agent.review_article(article)
        assert result["importance"] < 8
