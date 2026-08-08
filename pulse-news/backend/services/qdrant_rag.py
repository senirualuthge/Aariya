"""
qdrant_rag.py — Phase 5 Distributed Vector Search using Qdrant.

Replaces the local FAISS implementation for high-availability production RAG.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("pulse.qdrant")

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams, PointStruct
    _HAS_QDRANT = True
except ImportError:
    _HAS_QDRANT = False

from .rag import get_embedding

QDRANT_HOST = os.getenv("PULSE_QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("PULSE_QDRANT_PORT", "6333"))
COLLECTION_NAME = "pulse_news_articles"

class QdrantManager:
    def __init__(self):
        self.client = None
        self.is_ready = False

    def connect(self):
        if not _HAS_QDRANT:
            logger.warning("[Qdrant] qdrant-client not installed. Falling back to FAISS.")
            return

        try:
            self.client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
            
            # Ensure collection exists
            collections = self.client.get_collections().collections
            if not any(c.name == COLLECTION_NAME for c in collections):
                self.client.create_collection(
                    collection_name=COLLECTION_NAME,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )
            self.is_ready = True
            logger.info("[Qdrant] Connected and collection verified.")
        except Exception as exc:
            logger.error(f"[Qdrant] Connection failed: {exc}")

    def index_article(self, article: Dict[str, Any]):
        if not self.is_ready or self.client is None:
            return
            
        text = f"{article.get('title', '')}. {article.get('summary', '')}"
        if not text.strip():
            return
            
        emb = get_embedding(text)
        
        self.client.upsert(
            collection_name=COLLECTION_NAME,
            points=[
                PointStruct(
                    id=hash(article.get('id', text)) % (10 ** 8),
                    vector=emb,
                    payload={"title": article.get("title"), "summary": article.get("summary")}
                )
            ]
        )

    def search(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        if not self.is_ready or self.client is None:
            return []
            
        emb = get_embedding(query)
        hits = self.client.search(  # type: ignore
            collection_name=COLLECTION_NAME,
            query_vector=emb,
            limit=limit
        )
        return [hit.payload for hit in hits]

qdrant_db = QdrantManager()
