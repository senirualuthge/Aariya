"""
Semantic file memory — persistent vector index over local documents.

Uses chromadb (embedded PersistentClient — no HTTP server, per the SECURITY
NOTE in requirements.txt) + sentence-transformers. Graceful no-op when either
dependency is absent so the rest of the server still boots.

The indexer is the `index_file`/`semantic_search` backend for the
LocalKnowledgeAgent and the LiveWatcher.
"""

import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger("aariya.file_memory_indexer")

try:
    from sentence_transformers import SentenceTransformer
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False

try:
    import chromadb
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False


class FileMemoryIndexer:
    def __init__(self, db_path: str = "./file_memory_db", model_name: str = "all-MiniLM-L6-v2"):
        self._ready = _ST_AVAILABLE and _CHROMA_AVAILABLE
        if not self._ready:
            logger.warning("[indexer] chromadb/sentence-transformers missing — indexing disabled")
            self.collection = None
            self.model = None
            return

        self.model = SentenceTransformer(model_name)
        self.client = chromadb.PersistentClient(path=db_path)
        self.collection = self.client.get_or_create_collection("filesystem_memory")

    def _embed(self, text: str) -> List[float]:
        return self.model.encode(text).tolist()  # type: ignore[union-attr]

    def index_file(self, path: str, text: str | None = None) -> bool:
        """Index a document's text under its path (upsert by id)."""
        if not self._ready:
            return False
        p = Path(path)
        if text is None:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return False
        if not text or not text.strip():
            return False
        try:
            embedding = self._embed(text)
            self.collection.upsert(  # type: ignore[union-attr]
                ids=[str(path)],
                documents=[text[:5000]],
                embeddings=[embedding],
                metadatas=[{"path": str(path), "filename": p.name}],
            )
            logger.info(f"[indexer] indexed {path}")
            return True
        except Exception as e:
            logger.warning(f"[indexer] failed {path}: {e}")
            return False

    def semantic_search(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        if not self._ready:
            return {"ids": [], "documents": [], "metadatas": []}
        emb = self._embed(query)
        try:
            return self.collection.query(query_embeddings=[emb], n_results=top_k)  # type: ignore[return-value]
        except Exception as e:
            logger.warning(f"[indexer] search failed: {e}")
            return {"ids": [], "documents": [], "metadatas": []}
