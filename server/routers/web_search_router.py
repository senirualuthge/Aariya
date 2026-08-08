"""
web_search_router.py
────────────────────
FastAPI router exposing web search to the React frontend.

Endpoints:
  GET /api/web-search?q=...&num=5 — web search via WebIntelligence
                                    (provider priority: Bing > SerpAPI > Serper > mock)

The provider is reported in the response so the frontend can distinguish real
results from the mock fallback (a "mock" provider means no search API key is
configured server-side).

Mount in main.py:
  from server.routers.web_search_router import router as web_search_router
  app.include_router(web_search_router)
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from server.systems.agent.config import config
from server.systems.agent.web_intelligence import web_intel

logger = logging.getLogger("aariya.web_search")
router = APIRouter(prefix="/api/web-search", tags=["Web Search"])

MAX_RESULTS = 10


def _active_provider() -> str:
    """
    Report which provider WebIntelligence.search() will use.

    Mirrors the priority chain in WebIntelligence.search() (Bing > SerpAPI >
    Serper > mock) so the frontend knows whether results are real.
    """
    if config.BING_API_KEY:
        return "bing"
    if config.SERPAPI_KEY:
        return "serpapi"
    if getattr(config, "SERPER_API_KEY", None):
        return "serper"
    return "mock"


@router.get("")
async def web_search(q: str, num: int = MAX_RESULTS):
    """
    Search the web for `q`.

    Returns:
        { "query": str, "provider": str, "results": [{title, url, snippet}] }
    """
    q = (q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="'q' query parameter is required")
    # Cap query length so a long/malicious query can't inflate a provider call.
    q = q[:500]

    num = max(1, min(num, MAX_RESULTS))
    provider = _active_provider()

    # WebIntelligence uses blocking `requests` — never block the event loop.
    results = await asyncio.get_event_loop().run_in_executor(
        None, lambda: web_intel.search(q, num)
    )

    logger.info(
        "[web-search] q=%r provider=%s results=%d", q, provider, len(results)
    )
    return {"query": q, "provider": provider, "results": results}
