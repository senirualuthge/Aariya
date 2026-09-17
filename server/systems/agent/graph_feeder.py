"""
Knowledge Graph Feeder (AccessFIles §55 — graph memory fed by REAL data).

The persistent KnowledgeGraph (systems/agent/knowledge_graph.py) starts empty
and stays that way unless something real is folded in. This module ingests
genuine system signals as triples:

  * autonomy goals        → (user, has_goal, description)
  * learned insights      → (user, learned, topic)
  * knowledge gaps        → (user, curious_about, topic)
  * desktop twin activity → (user, used_app, app) / (user, opened_document, doc)
  * conversation messages → deterministic reference extraction: URLs,
                            absolute file paths, e-mail addresses

No LLM call and no invented entities: every triple originates from something
that actually happened in the running system. Duplicate edges are skipped so
re-ingesting is idempotent.
"""

import logging
import re
from typing import Dict, List

logger = logging.getLogger("aariya.agent.graph_feeder")

# Deterministic reference extractors — matched against REAL message text.
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
_PATH_RE = re.compile(r"(?:/[\w.\- ()]{2,}){2,}|(?:[A-Za-z]:\\(?:[\w.\- ]+\\){1,}[\w.\- ]+)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def extract_references(text: str) -> Dict[str, List[str]]:
    """Pull concrete references out of a real message body."""
    refs: Dict[str, List[str]] = {"url": [], "path": [], "email": []}
    text = text or ""
    for m in _URL_RE.findall(text):
        if m not in refs["url"]:
            refs["url"].append(m[:200])
    for m in _PATH_RE.findall(text):
        token = m.strip().rstrip(".,;:")
        # A bare "/" or a single segment is noise; require some depth.
        if token.count("/") + token.count("\\") >= 2 and token not in refs["path"]:
            refs["path"].append(token[:200])
    for m in _EMAIL_RE.findall(text):
        if m not in refs["email"]:
            refs["email"].append(m.lower()[:120])
    return refs


def _add_unique(kg, subject: str, relation: str, object_: str) -> bool:
    """Add a triple unless the exact relation→object edge already exists."""
    try:
        for fact in kg.query(subject):
            if fact.get("relation") == relation and fact.get("object") == object_:
                return False
        kg.add_triple(subject, relation, object_, {"source": "graph_feeder"})
        return True
    except Exception as exc:
        logger.debug("[graph_feeder] triple skipped (%s → %s): %s", subject, relation, exc)
        return False


def ingest_real_signals(user_id: str = "user_default") -> int:
    """Fold current real state into the graph. Returns triples added."""
    from server.systems.agent.knowledge_graph import kg

    added = 0

    # ── Autonomy store: goals / insights / gaps ────────────────────────────
    try:
        from server.autonomy.state import AutonomyStore
        store = AutonomyStore()
        for g in store.list_goals(user_id=user_id, status=None):
            desc = (g.get("description") or "").strip()
            if desc:
                added += _add_unique(kg, user_id, "has_goal", desc[:120])
        for i in store.list_insights(limit=25):
            topic = (i.get("topic") or "").strip()
            if topic:
                added += _add_unique(kg, user_id, "learned", topic[:120])
        for gap in store.list_gaps(limit=25):
            topic = (gap.get("topic") or "").strip()
            if topic:
                added += _add_unique(kg, user_id, "curious_about", topic[:120])
    except Exception as exc:
        logger.debug("[graph_feeder] autonomy signals unavailable: %s", exc)

    # ── Desktop twin: really-observed apps & documents ──────────────────────
    try:
        from server.systems.desktop_twin import get_desktop_twin
        ctx = get_desktop_twin(user_id).context() or {}
        for entry in (ctx.get("top_apps") or [])[:5]:
            app = (entry or {}).get("app")
            if app:
                added += _add_unique(kg, user_id, "used_app", str(app)[:80])
        app_now = (ctx.get("active_app") or "").strip()
        if app_now:
            added += _add_unique(kg, user_id, "used_app", str(app_now)[:80])
        for doc in (ctx.get("recent_documents") or [])[:10]:
            if doc:
                added += _add_unique(kg, user_id, "opened_document", str(doc)[:160])
    except Exception as exc:
        logger.debug("[graph_feeder] twin signals unavailable: %s", exc)

    # ── Conversation log: concrete references in real messages ─────────────
    try:
        from server.db import get_db_connection
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """SELECT role, text FROM conversation_messages
                   WHERE user_id = ? ORDER BY id DESC LIMIT 300""",
                (user_id,),
            ).fetchall()
        finally:
            conn.close()
        relations = {"url": "referenced_url",
                     "path": "referenced_file",
                     "email": "referenced_email"}
        for row in rows:
            refs = extract_references(row["text"])
            subject = user_id if row["role"] == "user" else f"{user_id}_aariya"
            for kind, found in refs.items():
                for value in found:
                    added += _add_unique(kg, subject, relations[kind], value)
    except Exception as exc:
        logger.debug("[graph_feeder] conversation signals unavailable: %s", exc)

    return added


def query_entity(entity: str) -> List[Dict]:
    """Read-side helper for the API: facts about one entity."""
    from server.systems.agent.knowledge_graph import kg
    return kg.query(entity)
