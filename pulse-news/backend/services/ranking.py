from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from db import db_cursor, get_learned_weight, update_learned_weight  # type: ignore
from services.ml_pipeline import forecaster
from services.personalization import personalizer
from services.agents import editorial_board

logger = logging.getLogger("pulse.ranking")

_ema_state: Dict[str, float] = defaultdict(float)


def _alpha() -> float:
    return get_learned_weight("ema_alpha", 0.3)


def _recency_decay() -> float:
    return get_learned_weight("recency_decay", 0.1)


def _risk_bonus() -> float:
    return get_learned_weight("risk_bonus", 1.2)


def _update_velocity(category: str, count: int) -> float:
    prev = _ema_state.get(category, 0.0)
    a = _alpha()
    new_ema = a * count + (1 - a) * prev
    _ema_state[category] = new_ema
    return new_ema


def _recency_weight(published_at: Optional[str]) -> float:
    if not published_at:
        return 0.5
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00")) if isinstance(published_at, str) else published_at
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        return math.exp(-_recency_decay() * age_hours)
    except Exception as exc:
        logger.debug("Recency weight parse failed for %s: %s", published_at, exc)
        return 0.5


def _update_blend_weights_from_feedback():
    try:
        with db_cursor() as cur:
            cur.execute(
                """SELECT
                    AVG(CASE WHEN feedback_type IN ('click','save','share') THEN 1.0 ELSE 0.0 END) as ml_effectiveness,
                    COUNT(*) as total
                FROM user_interactions
                WHERE created_at > now() - INTERVAL '7 days'"""
            )
            row = cur.fetchone()
            if row and row["total"] and row["total"] > 50:
                ml_eff = float(row["ml_effectiveness"] or 0.5)
                base_w = max(0.1, 1.0 - ml_eff)
                ml_w = 1.0 - base_w
                update_learned_weight("base_blend_weight", round(base_w, 4), row["total"])
                update_learned_weight("ml_blend_weight", round(ml_w, 4), row["total"])
    except Exception as exc:
        logger.debug("[Ranking] Blend weights update failed: %s", exc)


def rank_articles(
    articles: List[Dict[str, Any]],
    top_n: int = 20,
    min_importance: int = 1,
) -> List[Dict[str, Any]]:
    category_counts: Dict[str, int] = defaultdict(int)
    for a in articles:
        cat = a.get("category", "other") or "other"
        category_counts[cat] += 1

    velocity_map: Dict[str, float] = {}
    for cat, cnt in category_counts.items():
        velocity_map[cat] = _update_velocity(cat, cnt)

    _update_blend_weights_from_feedback()
    base_w = get_learned_weight("base_blend_weight", 0.4)
    ml_w = get_learned_weight("ml_blend_weight", 0.6)
    personalize_w = get_learned_weight("personalize_blend_weight", 0.5)
    r_bonus = _risk_bonus()

    scored = []
    for a in articles:
        if a.get("importance", 0) > 5:
            a = editorial_board.review_article(a)

        importance = a.get("importance") or 0
        if importance < min_importance:
            continue

        cat = a.get("category", "other") or "other"
        velocity = velocity_map.get(cat, 1.0)
        recency = _recency_weight(a.get("published_at"))
        risk_bonus = r_bonus if a.get("is_risk") else 1.0

        features = forecaster.extract_features(a, [])
        predicted_importance = forecaster.predict_importance(features)

        base_score = importance * (1 + 0.1 * velocity) * recency * risk_bonus
        blended_score = (base_w * base_score) + (ml_w * (predicted_importance * 10))
        a["rank_score"] = round(blended_score, 4)

        personalized_score = personalizer.adapt_score(a)
        a["rank_score"] = round(
            (1 - personalize_w) * a["rank_score"] + personalize_w * personalized_score,
            4,
        )
        scored.append(a)

    scored.sort(key=lambda x: x["rank_score"], reverse=True)
    return scored[:top_n]


def get_ranked_feed(
    limit: int = 30,
    category: Optional[str] = None,
    min_importance: int = 1,
    risk_only: bool = False,
) -> List[Dict[str, Any]]:
    with db_cursor() as cur:
        filters = ["importance >= %s", "importance IS NOT NULL"]
        params: list = [min_importance]

        if category:
            filters.append("category = %s")
            params.append(category)
        if risk_only:
            filters.append("is_risk = TRUE")

        where = " AND ".join(filters)
        cur.execute(
            f"""SELECT * FROM articles
            WHERE {where}
            ORDER BY importance DESC, ingested_at DESC
            LIMIT %s""",
            params + [limit * 2],
        )
        rows = [dict(r) for r in cur.fetchall()]

    return rank_articles(rows, top_n=limit, min_importance=min_importance)
