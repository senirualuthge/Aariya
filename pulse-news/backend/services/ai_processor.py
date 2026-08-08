"""
ai_processor.py — OpenRouter-powered article enrichment.

Takes a raw article dict and returns it enriched with:
  - summary (1-2 sentences)
  - importance (1-10)
  - category (tech / economy / global / security / other)
  - is_risk (bool)
  - key_entities (list of strings)

Uses OpenAI-compatible client pointed at OpenRouter.
Reads model from PULSE_CHAT_MODEL env var (defaults to poolside/laguna-xs.2:free).
Always uses json.loads() — never eval().
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from openai import OpenAI
from dotenv import load_dotenv

from db import db_cursor  # type: ignore

load_dotenv()
logger = logging.getLogger("pulse.ai")

_client: Optional[OpenAI] = None

# Throttle: free tier = 16 req/min → max 4 concurrent + 0.8s spacing keeps us safe
_SEMAPHORE: Optional[asyncio.Semaphore] = None
_REQ_DELAY = 0.8  # seconds between requests

_VALID_CATEGORIES = {"tech", "economy", "global", "security", "other"}


def _get_semaphore() -> asyncio.Semaphore:
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(4)
    return _SEMAPHORE


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        _client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
    return _client


def _get_model() -> str:
    return os.getenv("PULSE_CHAT_MODEL", "poolside/laguna-xs.2:free")


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a professional news intelligence analyst.
Analyze the given news article and return ONLY a valid JSON object with these exact keys:
- summary: string (1-2 concise sentences explaining what happened and why it matters)
- importance: integer 1-10 (10 = historic global event, 7+ = breaking major news, 4-6 = notable, 1-3 = minor)
- category: string, one of: "tech", "economy", "global", "security", "other"
- is_risk: boolean (true if involves threats, crashes, conflicts, disasters, or major disruptions)
- key_entities: array of strings (up to 5 key people, organizations, or locations involved)

Be strict. Do not add extra fields. Return only the JSON object."""


# ── Core enrichment function ─────────────────────────────────────────────────

def enrich_article(article: Dict[str, Any]) -> Dict[str, Any]:
    """
    Call cloud LLM to classify and summarize a single article.
    Returns the original article dict with AI fields merged in.
    Failures return the article unchanged with a default importance.
    """
    title       = article.get("title", "")
    description = article.get("description", "")
    content     = (article.get("content", "") or "")[:800]  # cap tokens

    user_msg = f"""Title: {title}
Description: {description}
Content snippet: {content}"""

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            resp = _get_client().chat.completions.create(
                model=_get_model(),
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                max_tokens=300,
                temperature=0.2,
            )
            raw = resp.choices[0].message.content or "{}"

            # Strip markdown code fences if present
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]

            parsed: Dict[str, Any] = json.loads(raw.strip())

            # Validate and clamp importance
            importance = parsed.get("importance")
            if not isinstance(importance, int):
                importance = None
            elif importance < 1 or importance > 10:
                importance = max(1, min(10, importance))

            # Validate category against DB constraint
            raw_category = parsed.get("category", "other")
            category = raw_category if raw_category in _VALID_CATEGORIES else "other"

            return {
                **article,
                "summary":      str(parsed.get("summary", ""))[:500],
                "importance":   importance,
                "category":     category,
                "is_risk":      bool(parsed.get("is_risk", False)),
                "key_entities": parsed.get("key_entities", []),
            }

        except json.JSONDecodeError as exc:
            logger.warning(f"[AI] JSON parse error for '{title[:50]}': {exc}")
            break  # No point retrying a parse error
        except Exception as exc:
            err_str = str(exc)
            if "429" in err_str and attempt < max_retries:
                wait = 60  # Wait a full minute when rate-limited
                logger.warning(f"[AI] 429 rate-limited, waiting {wait}s before retry (attempt {attempt+1})")
                time.sleep(wait)
                continue
            logger.error(f"[AI] Enrichment failed for '{title[:50]}': {exc}")
            break

    # Fallback if AI fails — use valid category 'other' (not 'general')
    logger.warning(f"[AI] Falling back to default enrichment for '{title[:50]}'")
    return {
        **article,
        "summary":      description[:500] if description else title,
        "importance":   5,
        "category":     "other",  # 'general' is not a valid DB enum value
        "is_risk":      False,
        "key_entities": [],
    }


async def enrich_batch(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Enrich articles in serial chunks to stay within OpenRouter's free rate limit
    (16 requests/minute). Chunks of 8 are processed concurrently (semaphore-guarded),
    then we wait 65s before the next chunk so the window resets.
    """
    if not articles:
        return []

    CHUNK_SIZE = 8
    sem = _get_semaphore()
    results: List[Dict[str, Any]] = []

    async def process_one(article: Dict[str, Any]) -> Dict[str, Any]:
        async with sem:
            enriched = await asyncio.to_thread(enrich_article, article)
            await asyncio.to_thread(_persist_enrichment, enriched)
            return enriched

    for i in range(0, len(articles), CHUNK_SIZE):
        chunk = articles[i:i + CHUNK_SIZE]
        chunk_results = await asyncio.gather(*(process_one(a) for a in chunk))
        results.extend(chunk_results)
        logger.info(f"[AI] Enriched chunk {i // CHUNK_SIZE + 1}: {len(chunk_results)} articles")

        # Wait for rate-limit window to reset before next chunk (skip after last chunk)
        if i + CHUNK_SIZE < len(articles):
            logger.info("[AI] Rate-limit pause: waiting 65s before next chunk…")
            await asyncio.sleep(65)

    logger.info(f"[AI] Enriched {len(results)} articles total")
    return results



# ── DB write-back ─────────────────────────────────────────────────────────────

def _persist_enrichment(article: Dict[str, Any]) -> None:
    """Update the articles row with AI-generated fields. No-op if fields missing."""
    if not article.get("importance"):
        return
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                UPDATE articles SET
                    summary      = %(summary)s,
                    importance   = %(importance)s,
                    category     = %(category)s,
                    is_risk      = %(is_risk)s,
                    key_entities = %(key_entities)s
                WHERE content_hash = %(content_hash)s
                """,
                {
                    "summary":      article.get("summary"),
                    "importance":   article.get("importance"),
                    "category":     article.get("category", "other"),
                    "is_risk":      article.get("is_risk", False),
                    "key_entities": article.get("key_entities", []),
                    "content_hash": article.get("content_hash"),
                },
            )
    except Exception as exc:
        logger.debug(f"[AI] Persist failed ({article.get('id')}): {exc}")
