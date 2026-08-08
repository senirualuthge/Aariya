"""
Obsidian vault search API — lets the chat UI and dashboards query Aariya's
two Obsidian vaults directly:

  GET /api/obsidian/search?q=<query>&vault=runtime|developer|all&k=5
      Semantic search over the indexed vault chunks (ChromaDB), filtered by
      the shared similarity floor so boilerplate noise is dropped.

  GET /api/obsidian/runtime/latest?limit=10
      Newest entries from the runtime vault's Logs/ dir. Read from disk (the
      authoritative source) so it includes notes written since the last sync —
      telemetry ticks, research turns, maintenance notes.

Both endpoints are best-effort: vault misconfiguration, ChromaDB failures and
unreadable files return empty results, never an error.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Query

from server.systems.rag.obsidian_indexer import (
    MEM_TYPE_DEVELOPER,
    MEM_TYPE_RUNTIME,
    SIMILARITY_FLOOR,
    get_obsidian_indexer,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/obsidian", tags=["obsidian"])


def _search_indexed(q: str, mem_type: Optional[str], k: int) -> List[dict]:
    """Semantic search scoped to one vault (None = both), noise-filtered."""
    try:
        results = get_obsidian_indexer().retrieve(q, k=k, mem_type=mem_type)
        return [
            {
                "source":     r.get("source"),
                "text":       r.get("text", ""),
                "similarity": r.get("similarity", 0.0),
            }
            for r in results
            if r.get("similarity", 0) > SIMILARITY_FLOOR
        ]
    except Exception as exc:
        logger.warning("Obsidian search failed: %s", exc)
        return []


@router.get("/search")
async def search_vault(
    q: str = Query(..., min_length=1, description="Search query"),
    vault: str = Query("runtime", description="runtime | developer | all"),
    k: int = Query(5, ge=1, le=20),
) -> dict:
    """Semantic search across one or both Obsidian vaults."""
    if vault == "runtime":
        hits = _search_indexed(q, MEM_TYPE_RUNTIME, k)
    elif vault == "developer":
        hits = _search_indexed(q, MEM_TYPE_DEVELOPER, k)
    else:
        hits = _search_indexed(q, None, k)
    return {"query": q, "vault": vault, "hits": hits}


@router.get("/runtime/latest")
async def runtime_latest(limit: int = Query(10, ge=1, le=50)) -> dict:
    """Newest runtime vault log entries, newest-first."""
    try:
        entries = get_obsidian_indexer().read_runtime_logs(limit)
    except Exception as exc:
        logger.warning("Runtime log read failed: %s", exc)
        entries = []
    return {"entries": entries}
