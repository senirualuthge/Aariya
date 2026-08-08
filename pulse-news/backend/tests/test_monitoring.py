import time
import pytest
from services.monitoring import PulseMetrics, metrics, track_latency


class TestPulseMetrics:
    @pytest.fixture
    def pm(self):
        return PulseMetrics()

    def test_inc_counter(self, pm):
        pm.inc("test.counter")
        assert pm._counters["test.counter"] == 1
        pm.inc("test.counter", 3)
        assert pm._counters["test.counter"] == 4

    def test_gauge(self, pm):
        pm.gauge("memory_mb", 256.0)
        assert pm._gauges["memory_mb"] == 256.0

    def test_record_latency(self, pm):
        pm.record_latency("db.query", 0.05)
        pm.record_latency("db.query", 0.10)
        assert len(pm._latencies["db.query"]) == 2

    def test_record_error(self, pm):
        pm.record_error("db.connection")
        assert pm._errors["db.connection"] == 1
        assert pm._counters["errors.db.connection"] == 1

    def test_snapshot_structure(self, pm):
        pm.inc("articles.fetched", 10)
        pm.record_latency("ai.enrich", 0.5)
        snap = pm.snapshot()
        assert "uptime_seconds" in snap
        assert "counters" in snap
        assert snap["counters"]["articles.fetched"] == 10
        assert "latencies" in snap
        assert "ai.enrich" in snap["latencies"]
        assert snap["latencies"]["ai.enrich"]["avg"] == 0.5
        assert "timestamp" in snap


def test_track_latency_decorator():
    pm = PulseMetrics()

    @track_latency("test.fn")
    def my_fn():
        time.sleep(0.01)
        return 42

    result = my_fn()
    assert result == 42
    # The global metrics object has the latency, not pm — but test that decorator works
    assert "calls.test.fn" in metrics._counters

    metrics._counters.clear()
    metrics._latencies.clear()
