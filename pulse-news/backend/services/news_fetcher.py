from __future__ import annotations

import logging
import os
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
import requests.auth
from dotenv import load_dotenv

from db import content_hash, db_cursor  # type: ignore

load_dotenv()
logger = logging.getLogger("pulse.fetcher")

NEWS_API_KEY = os.getenv("NEWSAPI_KEY", "")
SERPAPI_KEY = os.getenv("SERPAPI_KEY", "")
CURRENT_NEWS_API = os.getenv("CURRENT_NEWS_API", "")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "pulse-news/1.0")
GDELT_BASE = os.getenv("GDELT_BASE_URL", "https://api.gdeltproject.org/api/v2/doc/doc")

PULSE_SUBREDDITS = (os.getenv("PULSE_SUBREDDITS") or "worldnews,technology,news,economy").split(",")
PULSE_NEWSAPI_CATEGORIES = (os.getenv("PULSE_NEWSAPI_CATEGORIES") or "general,technology,business").split(",")


def _make_article(
    source_id: str,
    title: str,
    url: str,
    description: Optional[str],
    content: Optional[str],
    author: Optional[str],
    published_at: Optional[str],
    region_tag: Optional[str] = None,
    region_tags: Optional[list[str]] = None,
) -> Dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "source_id": source_id,
        "title": title.strip(),
        "url": url.strip(),
        "description": (description or "").strip(),
        "content": (content or "").strip(),
        "author": author,
        "published_at": published_at,
        "content_hash": content_hash(title, description or ""),
        "region_tag": region_tag or "global",
        "region_tags": region_tags or ["global"],
    }


def _fetch_newsapi(category: str = "general", page_size: int = 20) -> List[Dict[str, Any]]:
    if not NEWS_API_KEY:
        return []
    url = "https://newsapi.org/v2/top-headlines"
    params = {"category": category, "language": "en", "pageSize": page_size, "apiKey": NEWS_API_KEY}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error(f"[NewsAPI] Failed: {exc}")
        return []
    articles = []
    for a in data.get("articles", []):
        if not a.get("title") or not a.get("url"):
            continue
        articles.append(_make_article(
            source_id="newsapi-top", title=a["title"], url=a["url"],
            description=a.get("description"), content=a.get("content"),
            author=a.get("author"), published_at=a.get("publishedAt"),
        ))
    return articles


def _fetch_serpapi_google_news() -> List[Dict[str, Any]]:
    if not SERPAPI_KEY:
        return []
    url = "https://serpapi.com/search.json"
    params = {"engine": "google_news", "gl": "us", "hl": "en", "api_key": SERPAPI_KEY}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error(f"[SerpApi] Failed: {exc}")
        return []
    articles = []
    for a in data.get("news_results", []):
        if not a.get("title") or not a.get("link"):
            continue
        source = a.get("source")
        source_name = source.get("name") if isinstance(source, dict) else source
        articles.append(_make_article(
            source_id="serpapi-google-news", title=a["title"], url=a["link"],
            description=a.get("snippet"), content=None,
            author=source_name, published_at=a.get("date"),
        ))
    return articles


def _fetch_gdelt(max_records: int = 15) -> List[Dict[str, Any]]:
    params = {"query": "sourcelang:english", "mode": "ArtList",
              "maxrecords": max_records, "format": "json", "timespan": "15min"}
    try:
        resp = requests.get(GDELT_BASE, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error(f"[GDELT] Failed: {exc}")
        return []
    articles = []
    for a in data.get("articles", []):
        if not a.get("title") or not a.get("url"):
            continue
        articles.append(_make_article(
            source_id="gdelt-gkg", title=a.get("title", ""), url=a.get("url", ""),
            description=a.get("seendescription"), content=None,
            author=a.get("domain"), published_at=a.get("seendate"),
        ))
    return articles


def _fetch_currentsapi() -> List[Dict[str, Any]]:
    if not CURRENT_NEWS_API:
        return []
    url = "https://api.currentsapi.services/v1/latest-news"
    params = {"language": "en", "apiKey": CURRENT_NEWS_API}
    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error(f"[CurrentsAPI] Failed: {exc}")
        return []
    articles = []
    for a in data.get("news", []):
        if not a.get("title") or not a.get("url"):
            continue
        articles.append(_make_article(
            source_id="currentsapi", title=a["title"], url=a["url"],
            description=a.get("description"), content=None,
            author=a.get("author"), published_at=a.get("published"),
        ))
    return articles


def _fetch_rss_feeds() -> List[Dict[str, Any]]:
    feeds = [
        ("rss-google-alerts", "https://feeds.feedburner.com/googlenews/IMk"),
        ("rss-hacker-news", "https://hnrss.org/frontpage"),
        ("rss-reuters", "https://www.reutersagency.com/feed/"),
        ("rss-bbc", "https://feeds.bbci.co.uk/news/rss.xml"),
    ]
    articles = []
    for source_id, feed_url in feeds:
        try:
            resp = requests.get(feed_url, timeout=10, headers={"User-Agent": "pulse-news/1.0"})
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.iter("item"):
                title_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                pub_el = item.find("pubDate")
                if title_el is None or title_el.text is None:
                    continue
                if link_el is None or link_el.text is None:
                    continue
                articles.append(_make_article(
                    source_id=source_id, title=title_el.text, url=link_el.text,
                    description=desc_el.text if desc_el is not None else None,
                    content=None, author=None,
                    published_at=pub_el.text if pub_el is not None else None,
                ))
        except Exception as exc:
            logger.debug(f"[RSS] {source_id} failed: {exc}")
    if articles:
        logger.info(f"[RSS] Fetched {len(articles)} articles from {len(feeds)} feeds")
    return articles


def _fetch_twitter() -> List[Dict[str, Any]]:
    if not TWITTER_BEARER_TOKEN:
        return []
    url = "https://api.twitter.com/2/tweets/search/recent"
    params = {
        "query": "breaking news -is:retweet lang:en",
        "max_results": 10,
        "tweet.fields": "created_at,author_id,public_metrics",
    }
    headers = {"Authorization": f"Bearer {TWITTER_BEARER_TOKEN}"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug(f"[Twitter] Failed: {exc}")
        return []
    articles = []
    for t in data.get("data", []):
        articles.append(_make_article(
            source_id="twitter-breaking", title=t.get("text", "")[:200],
            url=f"https://twitter.com/i/web/status/{t['id']}",
            description=t.get("text"), content=None,
            author=t.get("author_id"), published_at=t.get("created_at"),
        ))
    if articles:
        logger.info(f"[Twitter] Fetched {len(articles)} tweets")
    return articles


def _fetch_reddit() -> List[Dict[str, Any]]:
    if not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET:
        return []
    auth = requests.auth.HTTPBasicAuth(REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET)
    data = {"grant_type": "client_credentials"}
    headers = {"User-Agent": REDDIT_USER_AGENT}
    try:
        token_resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=auth, data=data, headers=headers, timeout=10,
        )
        token_resp.raise_for_status()
        token = token_resp.json().get("access_token", "")
        if not token:
            return []
        headers["Authorization"] = f"bearer {token}"
        articles = []
        for sub in PULSE_SUBREDDITS:
            resp = requests.get(
                f"https://oauth.reddit.com/r/{sub}/hot",
                headers=headers, params={"limit": 5}, timeout=10,
            )
            resp.raise_for_status()
            for post in resp.json().get("data", {}).get("children", []):
                p = post.get("data", {})
                if not p.get("title") or p.get("domain") == "self." + sub:
                    continue
                articles.append(_make_article(
                    source_id=f"reddit-{sub}", title=p["title"],
                    url=p.get("url") or f"https://reddit.com{p.get('permalink', '')}",
                    description=p.get("selftext"), content=None,
                    author=p.get("author"), published_at=str(p.get("created_utc", "")),
                ))
        if articles:
            logger.info(f"[Reddit] Fetched {len(articles)} posts")
        return articles
    except Exception as exc:
        logger.debug(f"[Reddit] Failed: {exc}")
        return []


def _upsert_articles(articles: List[Dict[str, Any]]) -> int:
    inserted = 0
    for a in articles:
        try:
            with db_cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO articles
                        (id, source_id, title, url, description, content,
                         author, published_at, content_hash, region_tag,
                         region_tags)
                    VALUES
                        (%(id)s, %(source_id)s, %(title)s, %(url)s,
                         %(description)s, %(content)s, %(author)s,
                         %(published_at)s, %(content_hash)s, %(region_tag)s,
                         %(region_tags)s)
                    ON CONFLICT (content_hash) DO NOTHING
                    """,
                    a,
                )
                if cur.rowcount:
                    inserted += 1
        except Exception as exc:
            logger.debug(f"[DB] Upsert skipped ({a['url'][:60]}): {exc}")
    return inserted


def fetch_all_news() -> List[Dict[str, Any]]:
    raw: List[Dict[str, Any]] = []

    raw.extend(_fetch_serpapi_google_news())
    raw.extend(_fetch_rss_feeds())
    raw.extend(_fetch_reddit())
    raw.extend(_fetch_twitter())
    for cat in PULSE_NEWSAPI_CATEGORIES:
        raw.extend(_fetch_newsapi(category=cat.strip(), page_size=15))
    raw.extend(_fetch_gdelt(max_records=20))
    raw.extend(_fetch_currentsapi())

    seen_hashes: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for a in raw:
        h = a["content_hash"]
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique.append(a)

    inserted = _upsert_articles(unique)
    logger.info(f"[Fetcher] {len(unique)} unique from {len(raw)} raw → {inserted} new stored")
    return unique


def get_recent_articles(limit: int = 50, category: Optional[str] = None, region: Optional[str] = None) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        filters = []
        params: list = []
        if category:
            filters.append("category = %s")
            params.append(category)
        if region and region != "global":
            filters.append("region_tag = %s")
            params.append(region)
        where = " AND ".join(filters) if filters else "TRUE"
        cur.execute(
            f"SELECT * FROM articles WHERE {where} ORDER BY ingested_at DESC LIMIT %s",
            params + [limit],
        )
        return [dict(row) for row in cur.fetchall()]
