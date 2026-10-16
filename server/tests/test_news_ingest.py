"""
News ingest + injection tests (Track D — partials plan).

Covers the formal `news.alert` contract at /api/signals/ingest (the path
pulse-news' aigirl_bridge actually posts to), the typed news feed it feeds, and
the two real consumers: BrainV2's [NEWS] context and the proactive engine's
news trigger. Every read is from genuinely ingested data — the feed is bounded
and never synthesised.

Run: python -m pytest server/tests/test_news_ingest.py -v
"""

import asyncio
import time

import pytest
from fastapi import HTTPException

import server.infrastructure.signal_bus as infra
import server.systems.signal_bus as sysbus
from server.infrastructure.signal_bus import get_signal_bus
from server.routers.signals import ExternalSignal, ingest_external_signal


@pytest.fixture
def fresh_news():
    """Clean the ingest singleton + the news ring so tests don't leak state."""
    infra._ingest_bus = None
    sysbus.news_alerts.clear()
    yield
    infra._ingest_bus = None
    sysbus.news_alerts.clear()


def _post(sig: dict):
    model = ExternalSignal(**sig)
    return asyncio.run(ingest_external_signal(model, get_signal_bus()))


# ── Endpoint contract ────────────────────────────────────────────────────────

def test_valid_news_alert_is_stored_and_reaches_feed(fresh_news, isolated_db):
    res = _post({
        "type": "news.alert",
        "severity": "high",
        "source": {"system": "pulse-news"},
        "payload": {
            "headline": "Mars rover finds subsurface water",
            "summary": "Ice confirmed near the equator",
            "importance": 0.9,
            "category": "science",
            "topics": ["space", "nasa"],
        },
    })
    assert res["ok"] is True
    assert res["type"] == "news.alert"

    alerts = sysbus.recent_news_alerts()
    assert len(alerts) == 1
    assert alerts[0]["headline"] == "Mars rover finds subsurface water"
    assert alerts[0]["importance"] == pytest.approx(0.9)
    assert alerts[0]["topics"] == ["space", "nasa"]


def test_news_alert_missing_headline_is_422(fresh_news, isolated_db):
    with pytest.raises(HTTPException) as ei:
        _post({"type": "news.alert", "payload": {"summary": "no headline here"}})
    assert ei.value.status_code == 422
    assert sysbus.recent_news_alerts() == []


def test_news_alert_importance_out_of_range_is_422(fresh_news, isolated_db):
    with pytest.raises(HTTPException) as ei:
        _post({"type": "news.alert", "payload": {"headline": "x", "importance": 5.0}})
    assert ei.value.status_code == 422
    assert sysbus.recent_news_alerts() == []


def test_legacy_system_signal_still_accepted(fresh_news, isolated_db):
    """Back-compat: non-news payloads pass through unchanged."""
    res = _post({"type": "system", "payload": {"title": "hello"}})
    assert res["ok"] is True
    assert sysbus.recent_news_alerts() == []


# ── Feed semantics ───────────────────────────────────────────────────────────

def test_record_news_alert_requires_headline(fresh_news):
    entry = sysbus.record_news_alert({"headline": "   ", "importance": 0.9})
    assert entry["headline"] == ""
    assert len(sysbus.news_alerts) == 0


def test_recent_news_filters_by_importance(fresh_news):
    now = time.time()
    sysbus.record_news_alert({"headline": "low", "importance": 0.2, "ts": now})
    sysbus.record_news_alert({"headline": "high", "importance": 0.9, "ts": now + 1})
    out = sysbus.recent_news_alerts(min_importance=0.6)
    assert [a["headline"] for a in out] == ["high"]


def test_recent_news_filters_by_age_and_orders_newest_first(fresh_news):
    now = time.time()
    # a stale row dropped straight into the ring with an old received_at
    sysbus.news_alerts.append({
        "headline": "stale", "importance": 0.9,
        "ts": now - 7200, "received_at": now - 7200,
    })
    sysbus.record_news_alert({"headline": "older-fresh", "importance": 0.9, "ts": now - 10})
    sysbus.record_news_alert({"headline": "newer-fresh", "importance": 0.9, "ts": now - 1})
    out = sysbus.recent_news_alerts(max_age_seconds=3600)
    assert [a["headline"] for a in out] == ["newer-fresh", "older-fresh"]


# ── BrainV2 [NEWS] injection ─────────────────────────────────────────────────

def test_brain_news_context_empty_when_no_alerts(fresh_news):
    from server.systems.brain_v2 import BrainV2
    assert BrainV2._build_news_context(object()) == ""


def test_brain_news_context_includes_real_headline(fresh_news):
    from server.systems.brain_v2 import BrainV2
    sysbus.record_news_alert({
        "headline": "Central bank holds rates",
        "summary": "No change this quarter",
        "importance": 0.8,
        "category": "finance",
        "topics": ["economy"],
    })
    ctx = BrainV2._build_news_context(object())
    assert "Central bank holds rates" in ctx
    assert "finance" in ctx


# ── Proactive news trigger ───────────────────────────────────────────────────

def _patch_profile(monkeypatch, fav_topics):
    class _Profile:
        pass

    profile = _Profile()
    profile.fav_topics = fav_topics

    class _System:
        def get_profile(self, _uid):
            return profile

    monkeypatch.setattr(
        "server.systems.user_profile_system.get_user_profile_system",
        lambda: _System(),
    )


def test_proactive_news_fires_for_favorite_topic(fresh_news, monkeypatch):
    from server.systems.proactive.engine import ProactiveAIEngine
    _patch_profile(monkeypatch, {"space": 1.0})
    sysbus.record_news_alert({
        "headline": "Mars rover finds water",
        "importance": 0.9,
        "category": "science",
        "topics": ["space"],
    })
    eng = ProactiveAIEngine("u1")
    trigger = eng.evaluate({}, trust=0.5, session_active=True, extra={})
    assert trigger is not None
    assert trigger["type"] == "news"
    assert "Mars rover finds water" in trigger["message_hint"]
    assert trigger["payload"]["headline"] == "Mars rover finds water"


def test_proactive_news_silent_for_non_favorite_topic(fresh_news, monkeypatch):
    from server.systems.proactive.engine import ProactiveAIEngine
    _patch_profile(monkeypatch, {"sports": 1.0})
    sysbus.record_news_alert({
        "headline": "Mars rover finds water",
        "importance": 0.9,
        "category": "science",
        "topics": ["space"],
    })
    eng = ProactiveAIEngine("u1")
    assert eng.evaluate({}, trust=0.5, session_active=True, extra={}) is None


def test_proactive_news_silent_when_feed_empty(fresh_news, monkeypatch):
    from server.systems.proactive.engine import ProactiveAIEngine
    _patch_profile(monkeypatch, {"space": 1.0})
    eng = ProactiveAIEngine("u1")
    assert eng.evaluate({}, trust=0.5, session_active=True, extra={}) is None
