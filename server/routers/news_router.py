"""
news_router.py
──────────────
FastAPI router exposing live news to the React news panel.

Endpoints:
  GET /api/news               — ranked headline feed (pulse-news proxy → RSS fallback)
  GET /api/news/article?url=  — full article text extraction for the TTS reader
  GET /api/news/alerts        — high-importance breaking items (importance >= 7)

Mount in main.py:
  from server.routers.news_router import router as news_router
  app.include_router(news_router)
"""

from __future__ import annotations

import hashlib
import html as html_lib
import logging
import re
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Query

logger = logging.getLogger("aariya.news_router")
router = APIRouter(prefix="/api/news", tags=["News"])

PULSE_API = "http://127.0.0.1:8001/api/news"
REQUEST_TIMEOUT = 8.0
UA = "Aariya-NewsPanel/1.0"

# ── Live RSS sources (public, keyless) ────────────────────────────────────────
RSS_SOURCES = [
    ("breaking", "BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("tech", "BBC Tech", "https://feeds.bbci.co.uk/news/technology/rss.xml"),
    ("tech", "Hacker News", "https://hnrss.org/frontpage"),
    ("economy", "Reuters Markets", "https://feeds.reuters.com/reuters/businessNews"),
]

# Category boost — headline feed is ranked by a lightweight importance heuristic.
CATEGORY_BOOST = {"breaking": 1.6, "economy": 1.2, "tech": 1.1, "global": 1.0}
SOURCE_BOOST = {"BBC World": 1.3, "BBC Tech": 1.2, "Reuters": 1.2, "Hacker News": 0.9}
RISK_KEYWORDS = re.compile(
    r"\b(crash|collapse|war|attack|hack|breach|recall|fraud|lawsuit|shutdown|"
    r"disaster|emergency|evacuat|downgrade|recession|outage|leak|debt|bankrupt)"
    r"\b", re.IGNORECASE,
)


def _article_id(url: str) -> str:
    return hashlib.md5((url or "").encode()).hexdigest()[:12]


def _importance(title: str, description: str, category: str, source: str) -> int:
    text = f"{title} {description or ''}"
    score = 5.0
    score += CATEGORY_BOOST.get(category, 1.0)
    score += SOURCE_BOOST.get(source, 1.0)
    if RISK_KEYWORDS.search(text):
        score += 1.8
    return max(1, min(10, int(round(score))))


def _parse_published(pub_text: Optional[str]) -> Optional[str]:
    """Parse RSS pubDate → ISO. Best-effort; returns None on failure."""
    if not pub_text:
        return None
    try:
        ts = time.mktime(time.strptime(pub_text, "%a, %d %b %Y %H:%M:%S %z"))
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ts))
    except Exception:
        return None


# ── RSS ingestion (stdlib ElementTree, no extra deps) ─────────────────────────

def _rss_items(feed_url: str) -> List[Dict[str, Any]]:
    try:
        resp = httpx.get(feed_url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": UA}, follow_redirects=True)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        logger.debug("[News] RSS fetch failed %s: %s", feed_url, exc)
        return []
    items = []
    for item in root.iter("item"):
        def txt(tag: str) -> Optional[str]:
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else None
        title = txt("title")
        link = txt("link")
        if not title or not link:
            continue
        items.append({
            "id": _article_id(link),
            "title": html_lib.unescape(title),
            "url": link.strip(),
            "description": html_lib.unescape(txt("description") or "")[:500],
            "source": "BBC" if "bbc" in feed_url else "Hacker News" if "hnrss" in feed_url else "Reuters",
            "category": "breaking" if "world" in feed_url else "tech" if "hnrss" in feed_url or "technology" in feed_url else "economy",
            "published_at": _parse_published(txt("pubDate")),
        })
    return items


def _fallback_feed(limit: int) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    articles: List[Dict[str, Any]] = []
    for _cat, _src, url in RSS_SOURCES:
        for a in _rss_items(url):
            if a["id"] in seen:
                continue
            seen.add(a["id"])
            articles.append(a)
    for a in articles:
        a["importance"] = _importance(a["title"], a["description"], a["category"], a["source"])
        a["is_risk"] = bool(RISK_KEYWORDS.search(f"{a['title']} {a['description']}"))
        a["alert_priority"] = "critical" if a["importance"] >= 9 else "high" if a["importance"] >= 7 else "normal"
    articles.sort(key=lambda x: (x["importance"], x["published_at"] or ""), reverse=True)
    return articles[:limit]


# ── pulse-news proxy (preferred live source) ──────────────────────────────────

def _normalize_pulse_article(a: Dict[str, Any]) -> Dict[str, Any]:
    cat = a.get("category") or "global"
    if cat == "other":
        cat = "global"
    return {
        "id": a.get("id") or _article_id(a.get("url") or a.get("title") or ""),
        "title": a.get("title", "Untitled"),
        "url": a.get("url", ""),
        "description": a.get("summary") or a.get("description") or "",
        "source": a.get("source_name") or a.get("source_id") or "pulse-news",
        "category": cat,
        "published_at": a.get("published_at"),
        "importance": a.get("importance") or _importance(a.get("title", ""), a.get("summary", ""), cat, ""),
        "is_risk": bool(a.get("is_risk", False)),
        "alert_priority": a.get("alert_priority", "normal"),
    }


def _fetch_pulse_news(limit: int, category: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    try:
        params = {"limit": limit, "min_importance": 1}
        if category:
            params["category"] = category  # type: ignore[assignment]
        resp = httpx.get(PULSE_API, params=params, timeout=2.5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        rows = data.get("data") or []
        if not rows:
            return None
        return [_normalize_pulse_article(a) for a in rows if isinstance(a, dict)]
    except Exception as exc:
        logger.debug("[News] pulse-news proxy unavailable: %s", exc)
        return None


# ── Article text extraction (stdlib HTMLParser, no trafilatura needed) ────────

class _TextExtractor(HTMLParser):
    TAGS = {"p", "h1", "h2", "h3", "h4", "li", "blockquote"}

    def __init__(self) -> None:
        super().__init__()
        self.blocks: List[str] = []
        self._in_skip = 0
        self._in_block = False
        self._buf: List[str] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style", "nav", "footer", "aside"):
            self._in_skip += 1
        elif tag in self.TAGS and self._in_skip == 0:
            self._in_block = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "nav", "footer", "aside"):
            self._in_skip = max(0, self._in_skip - 1)
        elif tag in self.TAGS and self._in_skip == 0:
            text = " ".join("".join(self._buf).split()).strip()
            if text:
                self.blocks.append(text)
            self._in_block = False

    def handle_data(self, data: str) -> None:
        if self._in_block and self._in_skip == 0:
            self._buf.append(data)


def extract_article(url: str) -> Dict[str, Any]:
    try:
        resp = httpx.get(url, timeout=REQUEST_TIMEOUT, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
        }, follow_redirects=True)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and urlparse(url).path.endswith((".xml", ".pdf", ".png", ".jpg")):
            raise ValueError("Not an HTML page")
        parser = _TextExtractor()
        parser.feed(resp.text)
        blocks = parser.blocks
    except Exception as exc:
        logger.debug("[News] Article extraction failed %s: %s", url, exc)
        blocks = []

    return {"url": url, "blocks": blocks}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def get_news(
    limit: int = Query(30, ge=1, le=100),
    category: Optional[str] = Query(None),
):
    """Ranked headline feed. pulse-news backend preferred; RSS fallback if down."""
    articles = _fetch_pulse_news(limit, category)
    source = "pulse-news"
    if articles is None:
        articles = _fallback_feed(limit)
        source = "rss"
    if category and not articles:
        articles = [a for a in _fallback_feed(100) if a["category"] == category][:limit]
        source = "rss"
    return {"status": "ok", "source": source, "data": articles}


@router.get("/article")
async def get_article(url: str = Query(..., min_length=8)):
    """Full article text blocks for the reader + TTS."""
    return {"status": "ok", "data": extract_article(url)}


@router.get("/alerts")
async def get_alerts(limit: int = Query(10, ge=1, le=50)):
    """Breaking/high-importance items only."""
    articles = _fetch_pulse_news(limit * 3, None)
    if articles is None:
        articles = _fallback_feed(50)
    alerts = [a for a in articles if a.get("importance", 0) >= 7 or a.get("alert_priority") in ("critical", "high")]
    return {"status": "ok", "data": alerts[:limit]}
