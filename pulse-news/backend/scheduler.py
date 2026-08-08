from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

# APScheduler — gracefully degrade if not installed
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    _HAS_APSCHEDULER = True
except ImportError:
    AsyncIOScheduler = None  # type: ignore
    CronTrigger = None
    IntervalTrigger = None
    _HAS_APSCHEDULER = False
    import logging as _log
    _log.getLogger("pulse.scheduler").warning(
        "apscheduler not installed — install with: pip install apscheduler\n"
        "Scheduler will run in degraded mode (no background tasks)"
    )

from ws_manager import manager

logger = logging.getLogger("pulse.scheduler")

_scheduler: AsyncIOScheduler | None = None  # type: ignore

ALLOWED_REGIONS = os.getenv("PULSE_ALLOWED_REGIONS", "").split(",") if os.getenv("PULSE_ALLOWED_REGIONS") else None
TREND_CATEGORIES = (os.getenv("PULSE_TREND_CATEGORIES") or "tech,economy,global,security,other").split(",")


def _geo_filter(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not ALLOWED_REGIONS:
        return articles
    filtered = []
    for a in articles:
        tags = a.get("region_tags") or []
        single = a.get("region_tag") or ""
        if not tags and not single:
            continue
        if any(tag in ALLOWED_REGIONS for tag in tags):
            filtered.append(a)
        elif single in ALLOWED_REGIONS:
            filtered.append(a)
    return filtered or articles


def _run_agents(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    try:
        from services.agents import editorial_board
        results = []
        for a in articles:
            reviewed = editorial_board.review_article(a)
            results.append(reviewed)
        return results
    except Exception as exc:
        logger.debug("[Scheduler] Agent review skipped: %s", exc)
        return articles


async def _compute_trend_signals(articles: List[Dict[str, Any]]):
    try:
        from services.ml_pipeline import forecaster
        from kafka_pipeline import kafka_manager
        categories = set(a.get("category", "other") or "other" for a in articles)
        for cat in categories:
            signal = forecaster.compute_trend_signal(cat)
            try:
                from db import db_cursor  # type: ignore
                with db_cursor() as cur:
                    cur.execute(
                        """INSERT INTO trend_signals
                        (category, velocity, burst_ratio, source_diversity, trend_score, status, recorded_at)
                        VALUES (%s,%s,%s,%s,%s,%s,now())""",
                        (signal["category"], signal["velocity"], signal["burst_ratio"],
                         signal["source_diversity"], signal["trend_score"], signal["status"]),
                    )
            except Exception as exc:
                logger.debug("[Scheduler] Trend signal persist: %s", exc)
            if kafka_manager.is_connected:
                await kafka_manager.publish_trend_signal(signal)
    except Exception as exc:
        logger.debug("[Scheduler] Trend signals skipped: %s", exc)


async def _generate_trend_snapshots():
    try:
        from services.ml_pipeline import forecaster
        from kafka_pipeline import kafka_manager
        for cat in TREND_CATEGORIES:
            signal = forecaster.compute_trend_signal(cat)
            snapshot = {
                "category": cat,
                "trend_score": signal["trend_score"],
                "status": signal["status"],
                "burst_ratio": signal["burst_ratio"],
                "source_diversity": signal["source_diversity"],
                "snapped_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                from db import db_cursor  # type: ignore
                with db_cursor() as cur:
                    cur.execute(
                        """INSERT INTO trend_snapshots (category, trend_score, status, burst_ratio, source_diversity, snapped_at)
                        VALUES (%s,%s,%s,%s,%s,%s)""",
                        (snapshot["category"], snapshot["trend_score"], snapshot["status"],
                         snapshot["burst_ratio"], snapshot["source_diversity"], snapshot["snapped_at"]),
                    )
            except Exception as exc:
                logger.debug("[Scheduler] Snapshot persist: %s", exc)
            if kafka_manager.is_connected:
                await kafka_manager.publish_trend_snapshot(snapshot)
    except Exception as exc:
        logger.debug("[Scheduler] Trend snapshots skipped: %s", exc)


async def _generate_ml_predictions():
    try:
        from services.ml_pipeline import forecaster
        from kafka_pipeline import kafka_manager
        predictions = []
        for cat in TREND_CATEGORIES:
            signal = forecaster.compute_trend_signal(cat)
            features = {
                "velocity_1h": float(signal["recent_mentions"]),
                "velocity_24h": signal["velocity"],
                "novelty_score": 0.5, "source_credibility": 0.6,
                "entity_count": 0, "importance": 5,
                "engagement_rate": 0, "source_diversity": signal["source_diversity"] / 5.0,
                "burst_score": signal["burst_score"] if "burst_score" in signal else max(0, (signal["burst_ratio"] - 1) / 3),
                "sentiment": 0,
            }
            pred = {
                "category": cat,
                "predicted_importance": forecaster.predict_importance(features),
                "predicted_breaking_prob": forecaster.predict_breaking_probability(features),
                "predicted_at": datetime.now(timezone.utc).isoformat(),
                "horizon_hours": 6,
            }
            predictions.append(pred)
            try:
                from db import db_cursor  # type: ignore
                with db_cursor() as cur:
                    cur.execute(
                        """INSERT INTO trend_predictions (category, predicted_importance, predicted_breaking_prob, predicted_at, horizon_hours)
                        VALUES (%s,%s,%s,%s,%s)""",
                        (pred["category"], pred["predicted_importance"], pred["predicted_breaking_prob"],
                         pred["predicted_at"], pred["horizon_hours"]),
                    )
            except Exception as exc:
                logger.debug("[Scheduler] Prediction persist: %s", exc)
            if kafka_manager.is_connected:
                await kafka_manager.publish_trend_prediction(pred)
        return predictions
    except Exception as exc:
        logger.debug("[Scheduler] ML predictions skipped: %s", exc)
        return []


async def _fetch_and_enrich_job():
    from services.news_fetcher import fetch_all_news
    from services.ai_processor import enrich_batch
    from services.ranking import rank_articles
    from services.rag import index_article

    import asyncio
    try:
        logger.info("[Scheduler] Starting fetch cycle...")
        raw = await asyncio.to_thread(fetch_all_news)

        # Geo-filter
        raw = _geo_filter(raw)

        enriched = await enrich_batch(raw)

        # Multi-agent board review
        enriched = _run_agents(enriched)

        ranked = await asyncio.to_thread(rank_articles, enriched, top_n=20)

        await asyncio.gather(
            *(asyncio.to_thread(index_article, article) for article in enriched)
        )

        try:
            from services.qdrant_rag import qdrant_db
            if qdrant_db.is_ready:
                for article in enriched:
                    await asyncio.to_thread(qdrant_db.index_article, article)
        except Exception as exc:
            logger.debug("[Scheduler] Qdrant indexing skipped: %s", exc)

        try:
            from kafka_pipeline import kafka_manager
            if kafka_manager.is_connected:
                for article in raw:
                    await kafka_manager.publish_raw_article(article)
                for article in enriched:
                    await kafka_manager.publish_cleaned(article)
                    await kafka_manager.publish_nlu_entities(article.get("id", ""),
                        [{"name": e, "type": "unknown"} for e in (article.get("key_entities") or [])])
                    await kafka_manager.publish_nlu_topics(article.get("id", ""),
                        [article.get("category", "other")], [1.0])
        except Exception as exc:
            logger.debug("[Scheduler] Kafka publish skipped: %s", exc)

        for article in ranked:
            payload = dict(article)
            payload["type"] = "news_update"
            await manager.broadcast(payload)

        high_imp = [a for a in ranked if a.get("should_alert") or (a.get("importance") or 0) >= 8]
        if high_imp:
            try:
                from services.firebase_alerts import firebase
                firebase.initialize()
                for article in high_imp:
                    firebase.send_alert(article)
            except Exception as exc:
                logger.debug("[Scheduler] Firebase alert skipped: %s", exc)

            try:
                from services.aigirl_bridge import dispatch_alert_to_aigirl
                for article in high_imp:
                    await dispatch_alert_to_aigirl(article)
            except Exception as exc:
                logger.debug("[Scheduler] AI Girl bridge skipped: %s", exc)

            try:
                from kafka_pipeline import kafka_manager
                if kafka_manager.is_connected:
                    for article in high_imp:
                        await kafka_manager.publish_alert(article)
            except Exception as exc:
                logger.debug("[Scheduler] Kafka alert publish skipped: %s", exc)

        try:
            from services.ml_pipeline import forecaster
            await asyncio.to_thread(forecaster.collect_training_samples, enriched)
        except Exception as exc:
            logger.debug("[Scheduler] ML sample collection skipped: %s", exc)

        await _compute_trend_signals(enriched)

        logger.info(
            "[Scheduler] Cycle complete: %d fetched, %d enriched, %d ranked, %d alerts",
            len(raw), len(enriched), len(ranked), len(high_imp),
        )
    except Exception as exc:
        logger.error("[Scheduler] Fetch cycle failed: %s", exc)


async def _cleanup_job():
    from db import db_cursor  # type: ignore
    try:
        with db_cursor() as cur:
            cur.execute("DELETE FROM articles WHERE ingested_at < now() - INTERVAL '7 days'")
            deleted = cur.rowcount
            cur.execute("DELETE FROM trend_signals WHERE recorded_at < now() - INTERVAL '30 days'")
            cur.execute("DELETE FROM trend_snapshots WHERE snapped_at < now() - INTERVAL '30 days'")
            cur.execute("DELETE FROM user_interactions WHERE created_at < now() - INTERVAL '90 days'")
            logger.info("[Scheduler] Cleanup: removed %d articles, old signals/interactions", deleted)
    except Exception as exc:
        logger.error("[Scheduler] Cleanup failed: %s", exc)


async def _ml_training_job():
    try:
        from services.ml_pipeline import forecaster
        await forecaster.train_models()
    except Exception as exc:
        logger.error("[Scheduler] ML training failed: %s", exc)


async def _trend_snapshot_job():
    await _generate_trend_snapshots()
    await _generate_ml_predictions()


async def _briefing_job():
    try:
        from services.ranking import get_ranked_feed
        from services.aigirl_bridge import dispatch_briefing_to_aigirl

        articles = get_ranked_feed(limit=5, min_importance=5)
        if not articles:
            return

        top_risk = [a for a in articles if a.get("is_risk") and (a.get("importance") or 0) >= 7]
        briefing = {
            "headline_count": len(articles),
            "top_story": {"title": articles[0].get("title")} if articles else {},
            "risk_alerts": [{"title": a.get("title")} for a in top_risk],
        }
        await dispatch_briefing_to_aigirl(briefing)

        try:
            from services.firebase_alerts import firebase
            firebase.send_briefing_alert(len(articles), len(top_risk))
        except Exception:
            pass
    except Exception as exc:
        logger.debug("[Scheduler] Briefing dispatch skipped: %s", exc)


def start_scheduler():
    """Start the APScheduler instance. Returns None if apscheduler is not installed."""
    global _scheduler
    if not _HAS_APSCHEDULER:
        logger.warning("[Scheduler] apscheduler not available — background tasks disabled")
        return None

    if _scheduler and _scheduler.running:
        logger.warning("[Scheduler] Already running — skipping restart")
        return _scheduler

    _scheduler = AsyncIOScheduler(timezone="UTC")  # type: ignore

    _scheduler.add_job(  # type: ignore
        _fetch_and_enrich_job,
        trigger=IntervalTrigger(minutes=5),  # type: ignore
        id="fetch_and_enrich",
        name="News fetch + AI enrich",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now(timezone.utc),
    )

    _scheduler.add_job(  # type: ignore
        _trend_snapshot_job,
        trigger=IntervalTrigger(minutes=15),  # type: ignore
        id="trend_snapshots",
        name="Trend snapshot + ML predictions",
        replace_existing=True,
        max_instances=1,
    )

    _scheduler.add_job(  # type: ignore
        _cleanup_job,
        trigger=CronTrigger(hour=0, minute=0),  # type: ignore
        id="cleanup_old_articles",
        name="Delete old articles + signals",
        replace_existing=True,
    )

    _scheduler.add_job(  # type: ignore
        _ml_training_job,
        trigger=CronTrigger(hour=2, minute=0),  # type: ignore
        id="ml_training",
        name="ML model training (nightly)",
        replace_existing=True,
    )

    _scheduler.add_job(  # type: ignore
        _briefing_job,
        trigger=CronTrigger(hour=8, minute=0),  # type: ignore
        id="daily_briefing",
        name="Daily briefing to AI Girl",
        replace_existing=True,
    )

    manager.start_heartbeat()
    _scheduler.start()  # type: ignore
    logger.info("[Scheduler] Started — fetch:5min, trends:15min, cleanup:00:00, ML:02:00, briefing:08:00")
    return _scheduler


def stop_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Stopped")
