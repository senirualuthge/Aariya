"""
rag.py — Local FAISS-based Retrieval-Augmented Generation for Pulse AI News MVP.

Embeddings: Uses local sentence-transformers (all-MiniLM-L6-v2, 384-dim) — FREE, no API cost.
Generation: Uses OpenRouter free model via OPENROUTER_API_KEY env var.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
from openai import OpenAI

from db import db_cursor  # type: ignore

logger = logging.getLogger("pulse.rag")

_client: Optional[OpenAI] = None
_embedder = None
_index = None
_doc_map: Dict[int, Dict[str, Any]] = {}  # faiss index → article dict
_next_id = 0
_dim = 384  # all-MiniLM-L6-v2 dimension (local, free)


# ── Local embedding model ─────────────────────────────────────────────────────

def _get_embedder():
    """Lazy-load the local sentence-transformers model (downloaded once, cached)."""
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("[RAG] Loading local embedding model (all-MiniLM-L6-v2)...")
            _embedder = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("[RAG] Embedding model ready.")
        except Exception as exc:
            logger.error(f"[RAG] Failed to load embedding model: {exc}")
            _embedder = None
    return _embedder


# ── OpenRouter chat client ────────────────────────────────────────────────────

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        _client = OpenAI(api_key=api_key, base_url=base_url)
    return _client


def _get_chat_model() -> str:
    return os.getenv("PULSE_CHAT_MODEL", "poolside/laguna-xs.2:free")


# ── FAISS index ───────────────────────────────────────────────────────────────

def _get_index():
    global _index
    if _index is None:
        _index = faiss.IndexFlatL2(_dim)
    return _index


# ── Public API ────────────────────────────────────────────────────────────────

def get_embedding(text: str) -> List[float]:
    """Get a local embedding using sentence-transformers. Returns zero vector on failure."""
    embedder = _get_embedder()
    if embedder is None:
        return [0.0] * _dim
    try:
        emb = embedder.encode(text, normalize_embeddings=True)
        return emb.tolist()
    except Exception as exc:
        logger.error(f"[RAG] Local embedding failed: {exc}")
        return [0.0] * _dim


def index_article(article: Dict[str, Any]):
    """Add an article's title+summary to the FAISS index."""
    global _next_id

    text = f"{article.get('title', '')}. {article.get('summary', '')}"
    if not text.strip() or text == ". ":
        return

    emb = get_embedding(text)
    _get_index().add(np.array([emb], dtype=np.float32))  # type: ignore
    _doc_map[_next_id] = article
    _next_id += 1


def query_rag(query: str) -> str:
    """Retrieve the top-3 relevant articles and answer the query via cloud LLM."""
    if _next_id == 0:
        return "I haven't ingested any news yet. Please wait for the fetcher."

    emb = get_embedding(query)
    D, I = _get_index().search(np.array([emb], dtype=np.float32), k=3)  # type: ignore

    contexts = []
    for idx in I[0]:
        if idx in _doc_map:
            art = _doc_map[idx]
            contexts.append(f"- {art.get('title')}: {art.get('summary')}")

    context_str = "\n".join(contexts)
    sys_prompt = "You are Pulse AI, a news assistant. Answer the user's query using ONLY the provided recent news context."
    user_msg = f"Context:\n{context_str}\n\nQuery: {query}"

    try:
        resp = _get_client().chat.completions.create(
            model=_get_chat_model(),
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        return resp.choices[0].message.content or "No answer."
    except Exception as exc:
        logger.error(f"[RAG] Generation failed: {exc}")
        return "I'm having trouble analyzing the news right now."
