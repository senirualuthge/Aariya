"""
Self-Organizing Knowledge (*AccessFIles.txt* §98) + Self-Generated Knowledge
(§79).

Instead of static memory, concepts restructure themselves: this module pulls
whatever knowledge actually exists right now —

  * KnowledgeGraph triples (real stored edges)
  * episodic memories (real ChromaDB documents, when the store is up)
  * open internal thoughts (§52 journal)
  * desktop twin observations (apps/documents the user really touched)

— tokenizes them, clusters them with deterministic Jaccard agglomeration,
names each cluster from its most DISCRIMINATIVE terms (cluster frequency
minus corpus frequency), and — optionally — writes the emergent structure
back into the KnowledgeGraph as self-generated knowledge triples marked
`source=knowledge_organizer`.

Nothing is invented: cluster labels and summaries are assembled verbatim from
member text; with an empty store it honestly reports zero clusters.
"""

from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aariya.knowledge_organizer")

_DATA_DIR = Path("./data")
_JACCARD_AT = 0.25          # merge items whose term overlap clears this
_MIN_TERM_LEN = 3

_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "have", "was",
    "were", "are", "you", "your", "she", "her", "his", "him", "not", "but",
    "all", "can", "will", "just", "about", "into", "over", "under", "when",
    "what", "which", "who", "how", "why", "aariya", "user", "default",
}

_TOKEN_RE = re.compile(r"[a-z0-9_]{%d,}" % _MIN_TERM_LEN)


def _terms(text: str) -> set:
    return {t for t in _TOKEN_RE.findall(str(text or "").lower())
            if t not in _STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


class KnowledgeOrganizer:
    def __init__(self, kg_instance=None, report_path: Optional[str] = None):
        self._lock = threading.Lock()
        self._kg = kg_instance
        self.report_path = Path(report_path) if report_path else (_DATA_DIR / "knowledge_organizer.json")
        self._last_run: Dict[str, Any] = {}

    # ── sources (each honestly reports when unavailable) ───────────────────
    def _get_kg(self):
        if self._kg is None:
            from server.systems.agent.knowledge_graph import kg as _global_kg
            self._kg = _global_kg
        return self._kg

    def _collect(self, max_per_source: int) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []

        # 1. Knowledge graph edges.
        try:
            g = self._get_kg().graph
            for i, (s, o, data) in enumerate(g.edges(data=True)):
                if i >= max_per_source:
                    break
                rel = (data or {}).get("relation") or "->"
                items.append({"kind": "triple", "text": f"{s} {rel} {o}",
                              "terms": _terms(f"{s} {rel} {o}")})
        except Exception as exc:
            logger.debug("[Organizer] kg unavailable: %s", exc)

        # 2. Episodic memories (only when a real chroma store exists).
        try:
            from server.systems.memory.episodic_memory import EpisodicMemory
            em = EpisodicMemory("default")
            got = em.collection.get(include=["documents"]) or {}
            for doc in (got.get("documents") or [])[:max_per_source]:
                items.append({"kind": "memory", "text": str(doc),
                              "terms": _terms(doc)})
        except Exception as exc:
            logger.debug("[Organizer] episodic unavailable: %s", exc)

        # 3. Internal thought stream.
        try:
            from server.systems.cognition.thought_stream import get_thought_stream
            for th in get_thought_stream("default").recent(max_per_source):
                text = str(th.get("text") or "")
                items.append({"kind": "thought", "text": text,
                              "terms": _terms(text)})
        except Exception as exc:
            logger.debug("[Organizer] thoughts unavailable: %s", exc)

        # 4. Desktop twin observations.
        try:
            from server.systems.desktop_twin import get_desktop_twin
            ctx = get_desktop_twin("default").context()
            apps = [a.get("app") for a in ctx.get("top_apps", []) if a.get("app")]
            docs = [d.get("path") for d in ctx.get("recent_documents", []) if d.get("path")]
            for blob in apps + docs:
                items.append({"kind": "desktop", "text": str(blob),
                              "terms": _terms(blob)})
        except Exception as exc:
            logger.debug("[Organizer] desktop twin unavailable: %s", exc)

        return [it for it in items if it["terms"]]

    # ── clustering ─────────────────────────────────────────────────────────
    @staticmethod
    def _cluster(items: List[Dict[str, Any]]) -> List[List[int]]:
        n = len(items)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i in range(n):
            for j in range(i + 1, n):
                if _jaccard(items[i]["terms"], items[j]["terms"]) >= _JACCARD_AT:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[rj] = ri

        groups: Dict[int, List[int]] = {}
        for idx in range(n):
            groups.setdefault(find(idx), []).append(idx)
        return [g for g in groups.values()]

    @staticmethod
    def _label_and_summary(members: List[Dict[str, Any]],
                           corpus_df: Counter) -> Dict[str, Any]:
        tf = Counter(t for m in members for t in m["terms"])
        discriminative = sorted(
            tf.items(), key=lambda kv: (-(kv[1] / max(1, corpus_df[kv[0]])), -kv[1]))
        top_terms = [t for t, _ in discriminative[:2]]
        label = "-".join(top_terms) if top_terms else ""
        example = members[0]["text"][:90]
        kinds = sorted({m["kind"] for m in members})
        return {
            "label": label,
            "top_terms": top_terms,
            "size": len(members),
            "kinds": kinds,
            "summary": f"{len(members)} related {','.join(kinds)} items around "
                       f"'{', '.join(top_terms)}' — e.g. \"{example}\"",
            "members": [{"kind": m["kind"], "text": m["text"]} for m in members[:12]],
        }

    # ── public ─────────────────────────────────────────────────────────────
    def organize(self, ingest: bool = False,
                 max_per_source: int = 200) -> Dict[str, Any]:
        items = self._collect(max_per_source)
        corpus_df: Counter = Counter(t for it in items for t in it["terms"])

        clusters: List[Dict[str, Any]] = []
        for member_idx in self._cluster(items):
            members = [items[i] for i in member_idx]
            c = self._label_and_summary(members, corpus_df)
            clusters.append(c)

        clusters.sort(key=lambda c: -c["size"])

        ingested = 0
        if ingest:
            try:
                kg = self._get_kg()
                for c in clusters:
                    if c["size"] >= 2 and c["label"]:
                        for term in c["top_terms"][1:3] or c["top_terms"][:1]:
                            kg.add_triple(c["label"], "groups_concept", term,
                                          {"source": "knowledge_organizer"})
                            ingested += 1
            except Exception as exc:
                logger.warning("[Organizer] kg ingest failed: %s", exc)

        report = {
            "ts": time.time(),
            "items_scanned": len(items),
            "clusters_found": len(clusters),
            "clusters_ingested_triples": ingested,
            "clusters": clusters[:25],
            "sources_available": sorted({it["kind"] for it in items}) or [],
        }
        with self._lock:
            self._last_run = report
        try:
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("[Organizer] report save failed: %s", exc)
        return report

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {"last_run_ts": self._last_run.get("ts"),
                    "items_scanned": self._last_run.get("items_scanned", 0),
                    "clusters_found": self._last_run.get("clusters_found", 0),
                    "report_path": str(self.report_path)}


_inst: Optional[KnowledgeOrganizer] = None


def get_knowledge_organizer() -> KnowledgeOrganizer:
    global _inst
    if _inst is None:
        _inst = KnowledgeOrganizer()
    return _inst
