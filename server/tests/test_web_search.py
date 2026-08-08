"""Tests for the /api/web-search router (server/routers/web_search_router.py).

The endpoint funnels through WebIntelligence, which would hit the network —
these tests monkeypatch the search call so nothing leaves the machine.
"""

import asyncio

import pytest
from fastapi import HTTPException

from server.routers.web_search_router import _active_provider, web_search
from server.systems.agent.config import config


class _FakeWebIntel:
    """Canned results — records the query so clamping can be asserted."""

    def __init__(self, results):
        self._results = results
        self.last_query = None
        self.last_num = None

    def search(self, query, num_results=5):
        self.last_query = query
        self.last_num = num_results
        return self._results


SAMPLE_RESULTS = [
    {"title": "Example", "url": "https://example.com", "snippet": "A snippet."},
    {"title": "Second", "url": "https://example.com/2", "snippet": "More text."},
]


def test_web_search_returns_results(monkeypatch):
    fake = _FakeWebIntel(SAMPLE_RESULTS)
    monkeypatch.setattr("server.routers.web_search_router.web_intel", fake)
    # Hermetic: guarantee no search keys leak in from the developer's env.
    monkeypatch.setattr(config, "BING_API_KEY", None)
    monkeypatch.setattr(config, "SERPAPI_KEY", None)
    monkeypatch.setattr(config, "SERPER_API_KEY", None)

    payload = asyncio.run(web_search("hello world"))

    assert payload["query"] == "hello world"
    # No keys configured in tests → provider resolves to mock, but the results
    # (and the flag) still flow through so the frontend can decide what to show.
    assert payload["provider"] == "mock"
    assert payload["results"] == SAMPLE_RESULTS
    assert fake.last_query == "hello world"


def test_web_search_rejects_empty_query():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(web_search("   "))
    assert exc_info.value.status_code == 400


def test_web_search_clamps_num(monkeypatch):
    fake = _FakeWebIntel(SAMPLE_RESULTS)
    monkeypatch.setattr("server.routers.web_search_router.web_intel", fake)

    asyncio.run(web_search("q", num=100))   # clamped down to MAX_RESULTS
    assert fake.last_num == 10

    asyncio.run(web_search("q", num=0))     # clamped up to 1
    assert fake.last_num == 1


def test_active_provider_priority(monkeypatch):
    # Nothing configured → mock
    monkeypatch.setattr(config, "BING_API_KEY", None)
    monkeypatch.setattr(config, "SERPAPI_KEY", None)
    monkeypatch.setattr(config, "SERPER_API_KEY", None)
    assert _active_provider() == "mock"

    # Bing outranks the rest
    monkeypatch.setattr(config, "BING_API_KEY", "bing-key")
    assert _active_provider() == "bing"

    # SerpAPI outranks Serper
    monkeypatch.setattr(config, "BING_API_KEY", None)
    monkeypatch.setattr(config, "SERPAPI_KEY", "serpapi-key")
    monkeypatch.setattr(config, "SERPER_API_KEY", "serper-key")
    assert _active_provider() == "serpapi"

    # Serper alone (the previously-dead branch) now activates
    monkeypatch.setattr(config, "SERPAPI_KEY", None)
    assert _active_provider() == "serper"
