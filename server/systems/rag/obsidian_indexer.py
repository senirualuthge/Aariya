"""
Obsidian Dual-Vault Indexer — syncs markdown vaults into RAG memory.

Developer vault  (OBSIDIAN_DEVELOPER_VAULT_PATH) -> mem_type=obsidian_developer
  Read-only context so the AI can understand its own architecture.
Runtime vault    (OBSIDIAN_RUNTIME_VAULT_PATH)   -> mem_type=obsidian_runtime
  AI-written episodic logs / runtime captures.

Chunks are `From <filename>:`-prefixed and deduped against existing
memories before insert (deterministic id = md5(relative_path + chunk_index)).
Re-syncing an unchanged vault is therefore a no-op.

Dependencies: chromadb (graceful fallback to in-memory keyword store).
"""

import hashlib
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import chromadb
    from chromadb.config import Settings
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False

# Ensure OBSIDIAN_* vault paths from .env are visible regardless of how the
# server was launched (uvicorn env-file, pydantic env_file, or plain os.getenv).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

logger = logging.getLogger(__name__)

# Env var names (also declared in .env.example)
ENV_DEVELOPER_VAULT = "OBSIDIAN_DEVELOPER_VAULT_PATH"
ENV_RUNTIME_VAULT = "OBSIDIAN_RUNTIME_VAULT_PATH"
ENV_PERSIST_DIR = "OBSIDIAN_PERSIST_DIR"

MEM_TYPE_DEVELOPER = "obsidian_developer"
MEM_TYPE_RUNTIME = "obsidian_runtime"

COLLECTION_NAME = "obsidian_vaults"
DEFAULT_PERSIST_PATH = "./data/chroma/obsidian"

# Chunk target size (chars) — Obsidian notes are split on headers where possible.
CHUNK_TARGET_CHARS = int(os.getenv("OBSIDIAN_CHUNK_TARGET_CHARS", "1500"))
MAX_CHUNK_CHARS = int(os.getenv("OBSIDIAN_MAX_CHUNK_CHARS", "2500"))

# Daily-rotation bounds for the runtime vault Logs/ dir (cleanup_runtime_logs):
#   RUNTIME_LOG_RETENTION_DAYS — keep daily logs this long, delete older ones
#   RUNTIME_LOG_MAX_KB         — rotate today's file into Logs/Archive/ when bigger
RUNTIME_LOG_RETENTION_DAYS = int(os.getenv("RUNTIME_LOG_RETENTION_DAYS", "30"))
RUNTIME_LOG_MAX_BYTES = int(os.getenv("RUNTIME_LOG_MAX_KB", "512")) * 1024

_SKIP_DIRS = {".obsidian", ".git", ".trash", ".hidden", "node_modules", "Archive"}

# Serializes vault syncs. Multiple writers can now trigger sync_vault
# concurrently (startup sync thread, research-turn runtime notes, telemetry
# ticks) — Chroma's dedupe-get + add isn't atomic, so writes are serialized
# to avoid double-inserts on the shared collection.
_SYNC_LOCK = threading.Lock()

# Similarity floor for vault retrieval — Chroma returns top-k regardless of
# relevance, so clearly-unrelated chunks are dropped before use. Calibrated on
# the live vaults: real developer-vault matches score >= 0.28, real runtime
# matches >= 0.167, while noise (gibberish queries, an empty vault's
# Welcome.md) measures 0.0-0.128, so 0.15 removes noise without cutting
# legitimate matches. Shared by the research pipeline and the
# /api/obsidian/search endpoint.
SIMILARITY_FLOOR = 0.15


class ObsidianIndexer:
    """
    Syncs the two Obsidian vaults into a single ChromaDB collection,
    tagged by mem_type so retrieval can be scoped to either vault.
    """

    def __init__(
        self,
        persist_path: Optional[str] = None,
        developer_vault: Optional[str] = None,
        runtime_vault: Optional[str] = None,
    ):
        self.persist_path = persist_path or os.getenv(ENV_PERSIST_DIR, DEFAULT_PERSIST_PATH)
        self.developer_vault = developer_vault or os.getenv(ENV_DEVELOPER_VAULT, "")
        self.runtime_vault = runtime_vault or os.getenv(ENV_RUNTIME_VAULT, "")
        self._fallback: List[Dict] = []          # used when chromadb unavailable
        self._fallback_ids: set = set()          # dedupe for fallback store
        self.collection = None
        self._vector_ready = False

        if _CHROMA_AVAILABLE:
            try:
                self.client = chromadb.PersistentClient(
                    path=self.persist_path,
                    settings=Settings(anonymized_telemetry=False),
                )
                self.collection = self.client.get_or_create_collection(
                    name=COLLECTION_NAME,
                    metadata={"hnsw:space": "cosine"},
                )
                self._vector_ready = True
            except Exception as exc:
                logger.warning("ChromaDB init failed (%s) — falling back to in-memory store.", exc)

    # ── Vault discovery ─────────────────────────────────────────────────────
    def _discover_markdown_files(self, vault_path: str) -> List[Path]:
        """Return all .md files in a vault, skipping .obsidian and binary assets."""
        root = Path(vault_path)
        if not root.is_dir():
            logger.warning("Vault path does not exist: %s", vault_path)
            return []
        files = []
        for p in root.rglob("*.md"):
            rel = p.relative_to(root)
            if any(part in _SKIP_DIRS for part in rel.parts):
                continue
            files.append(p)
        return sorted(files)

    # ── Chunking ────────────────────────────────────────────────────────────
    def _chunk_file(self, path: Path) -> List[str]:
        """Split a markdown file into chunks, preferring header boundaries."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Skipping unreadable file %s: %s", path, exc)
            return []

        # Normalize line endings and strip leading/trailing whitespace.
        text = text.replace("\r\n", "\n").strip()
        if not text:
            return []

        # Split on markdown headings (##, ###, ...). A single line per chunk.
        parts = re.split(r"(?m)^(?=#{2,7} )", text)

        chunks: List[str] = []
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if len(part) <= CHUNK_TARGET_CHARS:
                chunks.append(part)
            else:
                # Re-split oversized sections on paragraph boundaries,
                # hard-capping any single paragraph at MAX_CHUNK_CHARS.
                paragraphs = [p.strip() for p in part.split("\n\n") if p.strip()]
                buf = ""
                for para in paragraphs:
                    piece = para if len(para) <= MAX_CHUNK_CHARS else para[:MAX_CHUNK_CHARS]
                    if buf and len(buf) + len(piece) > CHUNK_TARGET_CHARS:
                        chunks.append(buf)
                        buf = ""
                    buf = f"{buf}\n\n{piece}" if buf else piece
                if buf:
                    chunks.append(buf)
        return chunks

    def _memory_id(self, rel_path: str, chunk_index: int) -> str:
        """Deterministic id — identical vault state yields identical ids (dedupe)."""
        raw = f"{rel_path}::{chunk_index}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    # ── Sync ────────────────────────────────────────────────────────────────
    def sync_vault(self, vault_path: str, mem_type: str) -> Dict[str, int]:
        """
        Index every markdown file in the vault.
        Chunks are stored as `From <filename>:`-prefixed documents and
        deduped against existing memories (by deterministic id) before insert.

        Returns stats: {files, chunks, inserted, skipped_duplicates}.
        """
        stats = {"files": 0, "chunks": 0, "inserted": 0, "skipped_duplicates": 0}

        if not vault_path:
            logger.info("No vault path configured for %s — skipping.", mem_type)
            return stats

        for path in self._discover_markdown_files(vault_path):
            stats["files"] += 1
            rel = str(path.relative_to(vault_path)).replace("\\", "/")
            chunks = self._chunk_file(path)

            # Batch-build all ids for this file so we dedupe in one round-trip.
            ids = [self._memory_id(rel, idx) for idx in range(len(chunks))]
            existing = self._existing_ids(ids)

            for idx, chunk in enumerate(chunks):
                doc_id = ids[idx]
                document = f"From {rel}:\n{chunk}"
                meta = {
                    "mem_type": mem_type,
                    "source": rel,
                    "chunk_index": idx,
                    "timestamp": int(time.time()),
                }
                if doc_id in existing:
                    stats["skipped_duplicates"] += 1
                elif self._store(doc_id, document, meta):
                    stats["inserted"] += 1
                else:
                    stats["skipped_duplicates"] += 1
                stats["chunks"] += 1

        logger.info(
            "Obsidian sync %s: %d files, %d chunks, %d inserted, %d duplicates.",
            mem_type, stats["files"], stats["chunks"], stats["inserted"],
            stats["skipped_duplicates"],
        )
        return stats

    def _existing_ids(self, ids: List[str]) -> set:
        """Return the subset of ids already present (batched dedupe check)."""
        if not ids:
            return set()
        if self._vector_ready and self.collection is not None:
            try:
                got = self.collection.get(ids=ids, include=[])
                return set(got.get("ids", []))
            except Exception as exc:
                logger.warning("ChromaDB get failed (%s) — falling back to in-memory.", exc)
                self._vector_ready = False
        return self._fallback_ids & set(ids)

    def _store(self, doc_id: str, document: str, meta: Dict) -> bool:
        """Insert a chunk unless it already exists. Returns True if inserted."""
        if self._vector_ready and self.collection is not None:
            try:
                existing = self.collection.get(ids=[doc_id], include=[])
                if existing and existing.get("ids"):
                    return False
                # Use upsert instead of add to avoid ChromaDB warnings when
                # an embedding ID already exists in the HNSW index but the
                # collection-level dedup check missed it (race condition on
                # re-indexing the same vault content).
                self.collection.upsert(ids=[doc_id], documents=[document], metadatas=[meta])
                return True
            except Exception as exc:
                logger.warning("ChromaDB write failed (%s) — falling back to in-memory.", exc)
                self._vector_ready = False

        # Fallback in-memory store (keeps last 20000 chunks).
        if doc_id in self._fallback_ids:
            return False
        self._fallback.append({"id": doc_id, "document": document, "metadata": meta})
        self._fallback_ids.add(doc_id)
        self._fallback = self._fallback[-20000:]
        return True

    def sync_all(self) -> Dict[str, Dict[str, int]]:
        """Sync both vaults. Returns per-vault stats."""
        with _SYNC_LOCK:
            return {
                MEM_TYPE_DEVELOPER: self.sync_vault(self.developer_vault, MEM_TYPE_DEVELOPER),
                MEM_TYPE_RUNTIME: self.sync_vault(self.runtime_vault, MEM_TYPE_RUNTIME),
            }

    def append_runtime_note(self, text: str, title: str = "") -> Optional[str]:
        """
        Append a timestamped entry to the runtime vault — Aariya's running log.
        Writes to `<runtime_vault>/Logs/<YYYY-MM-DD>.md` as a new section so the
        next vault sync indexes it as obsidian_runtime context. The runtime
        vault is documented as AI-written episodic logs, so this is the writer
        half of that loop (retrieval is done by `retrieve`/`_gather_vault_context`).

        Returns the written file path, or None when no runtime vault is
        configured or the write fails (never raises).
        """
        if not self.runtime_vault:
            return None
        try:
            from datetime import datetime
            now = datetime.now()
            log_dir = Path(self.runtime_vault) / "Logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"{now.strftime('%Y-%m-%d')}.md"
            heading = f"## {title} — {now.strftime('%H:%M:%S')}" if title else f"## {now.strftime('%H:%M:%S')}"
            with open(log_file, "a", encoding="utf-8") as fh:
                fh.write(f"\n{heading}\n{text.strip()}\n")
            logger.info("Runtime note appended: %s", log_file)
        except OSError as exc:
            logger.warning("Failed to write runtime note: %s", exc)
            return None

        # Index the new note immediately so it is retrievable in the same
        # session (the startup sync would only pick it up on the next boot).
        # Idempotent: unchanged files are deduped by deterministic chunk ids.
        try:
            with _SYNC_LOCK:
                self.sync_vault(self.runtime_vault, MEM_TYPE_RUNTIME)
        except Exception as exc:
            logger.warning("Runtime vault re-sync after note failed: %s", exc)
        return str(log_file)

    # ── Retrieval ───────────────────────────────────────────────────────────
    def retrieve(
        self,
        query: str,
        k: int = 5,
        mem_type: Optional[str] = None,
        sources: Optional[List[str]] = None,
    ) -> List[Dict]:
        """
        Retrieve relevant chunks. Optionally scope to one vault (mem_type)
        and/or a set of source files.

        Returns a list of {text, mem_type, source, chunk_index, similarity}.
        """
        if not query.strip():
            return []

        results = []

        if self._vector_ready and self.collection is not None:
            try:
                if self.collection.count() == 0:
                    return []
                # Build a ChromaDB `where` clause only from filters actually present.
                filters: List[Dict[str, Any]] = []
                if mem_type:
                    filters.append({"mem_type": mem_type})
                if sources:
                    filters.append({"source": {"$in": sources}})
                where = {"$and": filters} if len(filters) > 1 else (filters[0] if filters else None)

                n = min(k, self.collection.count())
                qres = self.collection.query(
                    query_texts=[query],
                    n_results=n,
                    where=where,  # type: ignore
                )
                
                docs = qres.get("documents")
                if not docs or not docs[0]:
                    return []
                    
                metas = qres.get("metadatas")
                distances = qres.get("distances")
                
                for i, doc in enumerate(docs[0]):
                    # Check that meta is not None before assigning
                    meta_list = metas[0] if metas and metas[0] else []
                    meta = meta_list[i] if i < len(meta_list) and meta_list[i] is not None else {}
                    
                    dist_list = distances[0] if distances and distances[0] else []
                    dist = dist_list[i] if i < len(dist_list) and dist_list[i] is not None else 0.0
                    
                    results.append({
                        "text": doc,
                        "mem_type": meta.get("mem_type"),
                        "source": meta.get("source"),
                        "chunk_index": meta.get("chunk_index"),
                        "similarity": round(1.0 - float(dist), 4),
                    })
                return results
            except Exception as exc:
                logger.warning("ChromaDB query failed (%s) — falling back to keyword search.", exc)

        # Fallback: naive keyword overlap.
        query_words = set(re.findall(r"\w+", query.lower()))
        scored = []
        for m in self._fallback:
            if mem_type and m["metadata"].get("mem_type") != mem_type:
                continue
            if sources and m["metadata"].get("source") not in sources:
                continue
            words = set(re.findall(r"\w+", m["document"].lower()))
            overlap = len(query_words & words) / max(len(query_words), 1)
            if overlap > 0:
                scored.append((overlap, m))
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, m in scored[:k]:
            results.append({
                "text": m["document"],
                "mem_type": m["metadata"].get("mem_type"),
                "source": m["metadata"].get("source"),
                "chunk_index": m["metadata"].get("chunk_index"),
                "similarity": round(score, 4),
            })
        return results

    def format_for_prompt(self, memories: List[Dict], limit: int = 5) -> str:
        """Format retrieved chunks as a prompt-injection block."""
        if not memories:
            return ""
        lines = ["[Obsidian vault context:]"]
        for m in memories[:limit]:
            lines.append(f"- ({m.get('source', '?')}) {m.get('text', '')[:220]}")
        return "\n".join(lines)

    def _purge_source_chunks(self, source_rel: str) -> int:
        """Remove every indexed chunk for one source file (Chroma + fallback)."""
        purged = 0
        if self._vector_ready and self.collection is not None:
            try:
                got = self.collection.get(where={"source": source_rel}, include=[])
                ids = got.get("ids", [])
                if ids:
                    self.collection.delete(ids=ids)
                    purged = len(ids)
            except Exception as exc:
                logger.warning("Chroma purge failed for %s: %s", source_rel, exc)
        self._fallback = [
            m for m in self._fallback if m["metadata"].get("source") != source_rel
        ]
        self._fallback_ids = {m["id"] for m in self._fallback}
        return purged

    def cleanup_runtime_logs(
        self,
        retention_days: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> Dict[str, int]:
        """
        Daily-rotation cleanup so the runtime vault Logs/ dir stays bounded.

        Retention — daily log files (and Archive/ files) older than
        `retention_days` are deleted from disk and their Chroma chunks purged,
        so retrieval never surfaces notes from deleted files. Today's file and
        underscore-prefixed meta files (e.g. _TEMPLATE.md) are never touched.

        Rotation — when today's file exceeds `max_bytes` it is moved to
        Logs/Archive/ (kept on disk for manual browsing, but excluded from
        indexing) and its chunks purged, so a single busy day can't grow
        without bound. Archived files are themselves subject to retention.

        Defaults come from RUNTIME_LOG_RETENTION_DAYS (30) and
        RUNTIME_LOG_MAX_KB (512). Idempotent, never raises.
        Returns {"deleted_files", "rotated_files", "purged_chunks"}.
        """
        if not self.runtime_vault:
            return {"deleted_files": 0, "rotated_files": 0, "purged_chunks": 0}
        if retention_days is None:
            retention_days = RUNTIME_LOG_RETENTION_DAYS
        if max_bytes is None:
            max_bytes = RUNTIME_LOG_MAX_BYTES

        stats = {"deleted_files": 0, "rotated_files": 0, "purged_chunks": 0}
        logs_dir = Path(self.runtime_vault) / "Logs"
        if not logs_dir.is_dir():
            return stats
        archive_dir = logs_dir / "Archive"
        today = datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")

        with _SYNC_LOCK:
            # 1. Retention — sweep daily files + archives older than the cutoff.
            paths = list(logs_dir.glob("*.md"))
            if archive_dir.is_dir():
                paths += list(archive_dir.glob("*.md"))
            for path in paths:
                if path.name.startswith("_"):
                    continue  # template / meta files never get deleted
                date_part = path.name[:10]
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_part):
                    continue  # not a dated log — leave it alone
                if date_part >= cutoff:
                    continue  # today, or still within retention
                try:
                    path.unlink()
                except OSError as exc:
                    logger.warning("Failed to delete old runtime log %s: %s", path, exc)
                    continue
                stats["deleted_files"] += 1
                # Only daily files were ever indexed (Archive/ is skipped), so
                # purge their chunks to keep retrieval free of phantom notes.
                if path.parent == logs_dir:
                    stats["purged_chunks"] += self._purge_source_chunks(f"Logs/{path.name}")

            # 2. Rotation — oversized today file -> Archive/ (still on disk for
            #    manual browsing, but excluded from indexing; chunks purged).
            today_path = logs_dir / f"{today}.md"
            try:
                too_big = today_path.exists() and today_path.stat().st_size > max_bytes
            except OSError:
                too_big = False
            if too_big:
                try:
                    archive_dir.mkdir(parents=True, exist_ok=True)
                    stamp = datetime.now().strftime("%H%M%S")
                    dest = archive_dir / f"{today}-{stamp}.md"
                    today_path.rename(dest)
                    stats["rotated_files"] += 1
                    stats["purged_chunks"] += self._purge_source_chunks(f"Logs/{today}.md")
                    logger.info("Runtime log rotated: %s -> %s", today_path.name, dest.name)
                except OSError as exc:
                    logger.warning("Runtime log rotation failed: %s", exc)

        if stats["deleted_files"] or stats["rotated_files"]:
            logger.info("Runtime log cleanup: %s", stats)
        return stats

    def read_runtime_logs(self, limit: int = 10) -> List[Dict]:
        """
        Read the newest entries from the runtime vault's Logs/ directory.

        Reads from disk (the authoritative source) so it includes notes written
        since the last Chroma sync — telemetry ticks, research turns, manual
        notes. Each entry is a `## <Heading> — HH:MM:SS` section; meta files
        (underscore-prefixed, e.g. _TEMPLATE.md) are skipped.

        Returns newest-first: [{file, heading, text}].
        """
        if not self.runtime_vault:
            return []
        logs_dir = Path(self.runtime_vault) / "Logs"
        if not logs_dir.is_dir():
            return []

        # Include recent Archive/ files (rotated oversized days) so the "latest"
        # view doesn't blank out after a rotation; archives are pruned by the
        # same retention sweep as the daily files, so this stays bounded.
        paths = list(logs_dir.glob("*.md"))
        archive_dir = logs_dir / "Archive"
        if archive_dir.is_dir():
            paths += list(archive_dir.glob("*.md"))

        entries: List[Dict] = []
        for path in sorted(paths):
            if path.name.startswith("_"):
                continue  # meta files (template etc.)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("Skipping unreadable runtime log %s: %s", path, exc)
                continue
            for raw in re.split(r"(?m)^(?=## )", text):
                section = raw.strip()
                if not section or not section.startswith("##"):
                    continue
                first, _, body = section.partition("\n")
                heading = first[2:].strip() or path.name
                # Sort key: date file first, then the HH:MM(:SS) in the heading.
                time_match = re.search(r"—\s*(\d{1,2}:\d{2}(?::\d{2})?)\s*$", heading)
                entries.append({
                    "file":      path.name,
                    "heading":   heading,
                    "text":      body.strip(),
                    "_sort_key": (path.name, time_match.group(1) if time_match else ""),
                })
        entries.sort(key=lambda e: e["_sort_key"], reverse=True)
        for entry in entries:
            entry.pop("_sort_key", None)
        return entries[:limit]

    def count(self, mem_type: Optional[str] = None) -> int:
        if self._vector_ready and self.collection is not None:
            try:
                if mem_type:
                    got = self.collection.get(where={"mem_type": mem_type}, include=[])
                    return len(got.get("ids", []))
                return self.collection.count()
            except Exception:
                pass
        if mem_type:
            return sum(1 for m in self._fallback if m["metadata"].get("mem_type") == mem_type)
        return len(self._fallback)


# Singleton
_indexer: Optional[ObsidianIndexer] = None


def get_obsidian_indexer() -> ObsidianIndexer:
    global _indexer
    if _indexer is None:
        _indexer = ObsidianIndexer()
    return _indexer


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    indexer = get_obsidian_indexer()
    results = indexer.sync_all()
    for mem_type, stats in results.items():
        print(f"{mem_type}: {stats}")
