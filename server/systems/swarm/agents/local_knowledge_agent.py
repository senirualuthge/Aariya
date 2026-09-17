"""
Local Knowledge Agent — semantic retrieval over the local file index.

Thin swarm agent over FileMemoryIndexer.semantic_search. Answers questions
about the user's documents by returning the top-K matching chunks.
"""

from typing import Dict, Any

from server.systems.filesystem.file_memory_indexer import FileMemoryIndexer


class LocalKnowledgeAgent:
    def __init__(self, indexer: FileMemoryIndexer | None = None):
        self.indexer = indexer or FileMemoryIndexer()
        self.name = "local_knowledge_agent"

    async def act(self, state: Dict[str, Any]) -> Any:
        query = state.get("query") if isinstance(state, dict) else None
        return await self.process(query) if query else {"status": "no_query"}

    async def process(self, query: str) -> Dict[str, Any]:
        results = self.indexer.semantic_search(query, top_k=5)
        docs = results.get("documents", [[]])
        metas = results.get("metadatas", [[]])
        hits = []
        if docs and isinstance(docs[0], list):
            for doc, meta in zip(docs[0], metas[0] if metas else []):
                hits.append({"text": (doc or "")[:2000], "path": (meta or {}).get("path")})
        return {"status": "ok", "query": query, "results": hits}
