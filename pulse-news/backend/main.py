from __future__ import annotations

import logging
import os
from typing import Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from ws_manager import manager

from db import init_db  # type: ignore
from scheduler import start_scheduler
from services.ranking import get_ranked_feed


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pulse")

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    start_scheduler()

    try:
        from kafka_pipeline import start_kafka_pipeline
        await start_kafka_pipeline()
    except Exception as exc:
        logger.warning("[Pulse] Kafka pipeline not started: %s", exc)

    try:
        from services.qdrant_rag import qdrant_db
        qdrant_db.connect()
    except Exception as exc:
        logger.warning("[Pulse] Qdrant not connected: %s", exc)

    logger.info("[Pulse] Startup complete — DB, scheduler, Kafka, Qdrant initialized")
    yield

app = FastAPI(title="Pulse AI News", lifespan=lifespan)


@app.get("/api/news")
def get_news(
    limit: int = Query(20, ge=1, le=100),
    min_importance: int = Query(4, ge=0, le=10),
    category: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    risk_only: bool = Query(False),
):
    articles = get_ranked_feed(
        limit=limit, min_importance=min_importance, category=category, risk_only=risk_only,
    )
    if region:
        articles = [a for a in articles if region in (a.get("region_tags") or [])]
    return {"status": "ok", "data": articles}


@app.get("/api/categories")
def get_categories():
    from db import db_cursor  # type: ignore
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT category FROM articles WHERE category IS NOT NULL")
        rows = cur.fetchall()
    return {"status": "ok", "data": [r[0] for r in rows]}


@app.get("/api/health")
def health():
    return {"status": "ok", "ws_clients": manager.count}


@app.post("/api/feedback/{article_id}")
async def feedback(article_id: str, type: str = Query(...), user_id: str = Query("anonymous")):
    from services.personalization import personalizer
    personalizer.process_feedback(article_id, type, user_id)
    return {"status": "ok"}


@app.get("/api/briefing")
def get_briefing(
    style: str = Query("default", regex="^(default|brief|detailed|risk)$"),
):
    from services.ranking import get_ranked_feed
    from datetime import datetime, timezone

    articles = get_ranked_feed(limit=5, min_importance=5)

    top_risk = [a for a in articles if a.get("is_risk") and (a.get("importance") or 0) >= 7]
    top_story = articles[0] if articles else None

    briefing = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headline_count": len(articles),
        "top_story": {
            "title": top_story.get("title") if top_story else None,
            "summary": top_story.get("summary") if top_story else None,
        },
        "top_stories": [
            {
                "title": a.get("title"),
                "summary": a.get("summary"),
                "category": a.get("category", "other"),
                "importance": a.get("importance"),
                "is_risk": a.get("is_risk", False),
            }
            for a in articles
        ],
        "risk_alerts": [
            {
                "title": a.get("title"),
                "summary": a.get("summary"),
                "priority": a.get("alert_priority", "normal"),
            }
            for a in top_risk
        ],
        "narrative": _build_narrative(articles, style),
    }
    return {"status": "ok", "data": briefing}


def _build_narrative(articles: list, style: str) -> str:
    if not articles:
        return "No news to report at this time."

    lines = []
    if style == "risk":
        risks = [a for a in articles if a.get("is_risk")]
        if not risks:
            return "No significant risks detected in the current news cycle."
        lines.append(f"I've identified {len(risks)} risk items you should know about.")
        for r in risks:
            lines.append(f"{r.get('title')} — {r.get('summary')}")
        return " ".join(lines)

    top = articles[0]
    lines.append(f"Your top story: {top.get('title')}.")
    if top.get("summary"):
        lines.append(top["summary"])

    if len(articles) > 1:
        lines.append(f"Also notable: {articles[1].get('title')}.")

    risks = [a for a in articles if a.get("is_risk")]
    if risks:
        lines.append(f"Risk alert: {risks[0].get('title')}")

    if style == "detailed":
        for a in articles[2:]:
            lines.append(f"{a.get('title')}. {a.get('summary', '')}")

    return " ".join(lines)


# ── Trends endpoints ──────────────────────────────────────────────────────

@app.get("/api/trends")
def get_trends(
    category: Optional[str] = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    from db import db_cursor  # type: ignore
    from typing import Any
    with db_cursor() as cur:
        filters = []
        params: list[Any] = []
        if category:
            filters.append("category = %s")
            params.append(category)
        where = " AND ".join(filters) if filters else "TRUE"
        cur.execute(
            f"""SELECT category, velocity, burst_ratio, source_diversity, trend_score, status, recorded_at
            FROM trend_signals WHERE {where}
            ORDER BY recorded_at DESC LIMIT %s""",
            params + [limit],
        )
        rows = [dict(r) for r in cur.fetchall()]
    return {"status": "ok", "data": rows}


@app.get("/api/trends/snapshots")
def get_trend_snapshots(
    category: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=168),
):
    from db import db_cursor  # type: ignore
    from typing import Any
    with db_cursor() as cur:
        filters = ["snapped_at > now() - INTERVAL '%s hours'"]
        params: list[Any] = [hours]
        if category:
            filters.append("category = %s")
            params.append(category)
        where = " AND ".join(filters)
        cur.execute(
            f"""SELECT category, trend_score, status, burst_ratio, source_diversity, snapped_at
            FROM trend_snapshots WHERE {where}
            ORDER BY snapped_at ASC""",
            params,
        )
        rows = [dict(r) for r in cur.fetchall()]
    return {"status": "ok", "data": rows}


@app.get("/api/trends/predictions")
def get_trend_predictions(category: Optional[str] = Query(None)):
    from db import db_cursor  # type: ignore
    from typing import Any
    with db_cursor() as cur:
        filters = []
        params: list[Any] = []
        if category:
            filters.append("category = %s")
            params.append(category)
        where = " AND ".join(filters) if filters else "TRUE"
        cur.execute(
            f"""SELECT category, predicted_importance, predicted_breaking_prob, predicted_at, horizon_hours
            FROM trend_predictions WHERE {where}
            ORDER BY predicted_at DESC LIMIT 20""",
            params,
        )
        rows = [dict(r) for r in cur.fetchall()]
    return {"status": "ok", "data": rows}


# ── Search endpoint ───────────────────────────────────────────────────────

@app.get("/api/search")
def search_articles(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
):
    try:
        from services.qdrant_rag import qdrant_db
        if qdrant_db.is_ready:
            results = qdrant_db.search(q, limit=limit)
            if results:
                return {"status": "ok", "data": results}
    except Exception as exc:
        logger.debug("[Search] Qdrant search failed, falling back to DB: %s", exc)

    from db import db_cursor  # type: ignore
    with db_cursor() as cur:
        cur.execute(
            """SELECT * FROM articles
            WHERE title ILIKE %s OR summary ILIKE %s OR description ILIKE %s
            ORDER BY importance DESC NULLS LAST, ingested_at DESC
            LIMIT %s""",
            (f"%{q}%", f"%{q}%", f"%{q}%", limit),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return {"status": "ok", "data": rows}


# ── Chat / Q&A endpoint ───────────────────────────────────────────────────

@app.post("/api/chat")
async def chat_question(question: str = Query(..., min_length=1)):
    try:
        from services.qdrant_rag import qdrant_db
        if qdrant_db.is_ready:
            context_docs = qdrant_db.search(question, limit=3)
        else:
            context_docs = []
    except Exception as exc:
        logger.debug("[Chat] Qdrant context search failed: %s", exc)
        context_docs = []

    context = ""
    if context_docs:
        context = "\n".join(
            f"- {d.get('title', '')}: {d.get('summary', '')[:300]}"
            for d in context_docs if isinstance(d, dict)
        )

    try:
        from openai import OpenAI
        import os
        client = OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )
        system = "You are a news assistant. Answer based on the provided context if available."
        prompt = f"Context:\n{context}\n\nQuestion: {question}\n\nAnswer concisely:" if context else question
        resp = client.chat.completions.create(
            model=os.getenv("PULSE_CHAT_MODEL", "poolside/laguna-xs.2:free"),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_tokens=300, temperature=0.3,
        )
        answer = resp.choices[0].message.content or "I couldn't find an answer."
    except Exception as exc:
        logger.debug("[Chat] LLM unavailable: %s", exc)
        answer = "Sorry, I couldn't process your question right now."

    return {"status": "ok", "data": {"question": question, "answer": answer, "sources": context_docs}}


# ── Voice intent endpoint ──────────────────────────────────────────────────

@app.post("/api/voice/intent")
async def voice_intent(text: str = Query(..., min_length=1)):
    try:
        from openai import OpenAI
        import os
        client = OpenAI(
            api_key=os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        )
        resp = client.chat.completions.create(
            model=os.getenv("PULSE_CHAT_MODEL", "poolside/laguna-xs.2:free"),
            messages=[{
                "role": "system",
                "content": """Classify the voice command into one of these intents (JSON only):
{"intent": "read_headlines", "params": {}}
{"intent": "read_top_story", "params": {}}
{"intent": "read_category", "params": {"category": "tech|economy|global|security"}}
{"intent": "stop_reading", "params": {}}
{"intent": "next_article", "params": {}}
{"intent": "ask_question", "params": {"question": "..."}}
{"intent": "unknown", "params": {}}
Respond with ONLY the JSON object.""",
            }, {
                "role": "user",
                "content": text,
            }],
            max_tokens=100, temperature=0.1,
        )
        raw = resp.choices[0].message.content or "{}"
        raw = raw.strip().strip("```json").strip("```").strip()
        import json
        intent = json.loads(raw)
    except Exception as exc:
        logger.debug("[Voice] Intent parsing failed: %s", exc)
        intent = {"intent": "unknown", "params": {}}

    return {"status": "ok", "data": intent}


# ── User settings endpoints ───────────────────────────────────────────────

@app.get("/api/user/settings")
def get_user_settings(user_id: str = Query("anonymous")):
    from db import get_user_settings as _get_settings  # type: ignore
    return {"status": "ok", "data": _get_settings(user_id)}


@app.post("/api/user/settings")
async def update_user_settings(
    user_id: str = Query("anonymous"),
    interests: Optional[str] = Query(None),
    region: Optional[str] = Query(None),
    risk_mode: Optional[bool] = Query(None),
    alert_threshold: Optional[int] = Query(None, ge=1, le=10),
    alert_cooldown_mins: Optional[int] = Query(None, ge=5, le=1440),
    tts_rate: Optional[float] = Query(None, ge=0.1, le=1.0),
    tts_pitch: Optional[float] = Query(None, ge=0.5, le=2.0),
    theme: Optional[str] = Query(None, regex="^(dark|light)$"),
):
    from db import db_cursor  # type: ignore
    from typing import Any
    updates: dict[str, Any] = {}
    if interests: updates["interests"] = interests.split(",")
    if region: updates["region"] = region
    if risk_mode is not None: updates["risk_mode"] = risk_mode
    if alert_threshold: updates["alert_threshold"] = alert_threshold
    if alert_cooldown_mins: updates["alert_cooldown_mins"] = alert_cooldown_mins
    if tts_rate: updates["tts_rate"] = tts_rate
    if tts_pitch: updates["tts_pitch"] = tts_pitch
    if theme: updates["theme"] = theme

    if updates:
        set_clause = ", ".join(f"{k} = %s" for k in updates)
        vals = list(updates.values())
        with db_cursor() as cur:
            cur.execute(
                f"INSERT INTO user_settings (user_id, {', '.join(updates.keys())}) "
                f"VALUES (%s, {', '.join(['%s'] * len(updates))}) "
                f"ON CONFLICT (user_id) DO UPDATE SET {set_clause}",
                [user_id] + vals + vals,
            )
    return {"status": "ok"}


# ── WebSocket ─────────────────────────────────────────────────────────────

@app.websocket("/ws/feed")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            msg = data.strip().lower()
            if msg == "ping":
                await ws.send_text('{"type":"pong"}')
            elif msg.startswith("subscribe:"):
                pass
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)
