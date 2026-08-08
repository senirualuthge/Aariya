import pytest
from services.ranking import _recency_weight
from datetime import datetime, timezone, timedelta


class TestRecencyWeight:
    def test_recent_article(self):
        now_str = datetime.now(timezone.utc).isoformat()
        weight = _recency_weight(now_str)
        assert weight > 0.9

    def test_old_article(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        weight = _recency_weight(old)
        assert weight < 0.1

    def test_none_date(self):
        assert _recency_weight(None) == 0.5

    def test_invalid_date(self):
        assert _recency_weight("not-a-date") == 0.5
