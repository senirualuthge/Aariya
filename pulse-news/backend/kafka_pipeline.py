from __future__ import annotations

import json
import logging
import asyncio
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Callable, Awaitable

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from server.cognition.core.runtime import CognitiveRuntime

logger = logging.getLogger("pulse.kafka")

# Initialize the global cognitive runtime
cognitive_runtime = CognitiveRuntime()


KAFKA_BROKER = os.getenv("PULSE_KAFKA_BROKER", "localhost:9092")
TOPICS = {
    "raw": "news.raw.ingest",
    "cleaned": "news.cleaned.article",
    "chunks": "news.chunks.embedding",
    "nlu_entities": "news.nlu.entities",
    "nlu_topics": "news.nlu.topics",
    "embedding": "news.embedding.vector",
    "trend_signals": "news.trend.signals",
    "trend_snapshots": "news.trend.snapshots",
    "trend_predictions": "news.trend.predictions",
    "alerts": "news.alerts",
    "user_events": "news.user.events",
    "dlq": "news.dlq.failed",
}

try:
    from confluent_kafka import Producer, Consumer, KafkaException
    _HAS_KAFKA = True
except ImportError:
    _HAS_KAFKA = False

_CONSUMER_GROUPS: Dict[str, str] = {
    "raw": "pulse-enrichment-group",
    "cleaned": "pulse-cleaned-group",
    "chunks": "pulse-embedding-group",
    "nlu_entities": "pulse-nlu-group",
    "trend_signals": "pulse-trend-group",
    "alerts": "pulse-alert-group",
    "user_events": "pulse-user-group",
}


class KafkaManager:
    def __init__(self):
        self.is_connected = False
        self.producer: Optional[Any] = None
        self.consumers: Dict[str, Any] = {}
        self._running = False
        self._partition_count = 3
        self._delivery_callbacks: Dict[str, list] = defaultdict(list)

    async def connect(self):
        if not _HAS_KAFKA:
            logger.warning("[Kafka] confluent-kafka not installed — pipeline disabled")
            return
        try:
            self.producer = Producer({
                'bootstrap.servers': KAFKA_BROKER,
                'queue.buffering.max.messages': 100000,
                'batch.num.messages': 500,
                'linger.ms': 10,
                'compression.type': 'snappy',
            })
            self.is_connected = True
            logger.info("[Kafka] Connected to %s with %d partitions", KAFKA_BROKER, self._partition_count)
        except Exception as e:
            logger.error("[Kafka] Connection failed: %s", e)

    def _delivery_ok(self, err, msg):
        if err is not None:
            logger.error("[Kafka] Delivery failed to %s: %s", msg.topic() if msg else "?", err)
            if msg:
                self._publish_dlq(msg.topic(), msg.value().decode("utf-8") if msg.value() else "", str(err))
        else:
            logger.debug("[Kafka] Delivered to %s [%s]", msg.topic(), msg.partition() if msg else "?")

    def _publish_dlq(self, original_topic: str, payload: str, error: str):
        dlq_entry = json.dumps({
            "original_topic": original_topic,
            "payload": payload,
            "error": error,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        })
        if not self.producer:
            logger.error("[Kafka] Cannot publish to DLQ, producer is None.")
            return
        try:
            self.producer.produce(TOPICS["dlq"], dlq_entry.encode("utf-8"), callback=lambda e, m: None)
            self.producer.poll(0)
        except Exception as exc:
            logger.error("[Kafka] DLQ publish failed: %s", exc)

    async def publish(self, topic: str, message: Dict[str, Any], key: Optional[str] = None):
        if not self.is_connected or not self.producer:
            return
        payload = b""
        try:
            payload = json.dumps(message, default=str).encode("utf-8")
            self.producer.produce(
                topic, payload,
                key=key.encode("utf-8") if key else None,
                callback=self._delivery_ok,
            )
            self.producer.poll(0)
        except BufferError:
            logger.warning("[Kafka] Buffer full — flushing and retrying %s", topic)
            self.producer.flush(5)
            try:
                self.producer.produce(topic, payload, key=key.encode("utf-8") if key else None,
                                      callback=self._delivery_ok)
                self.producer.poll(0)
            except Exception as e:
                logger.error("[Kafka] Retry failed for %s: %s", topic, e)
        except Exception as e:
            logger.error("[Kafka] Publish error on %s: %s", topic, e)

    async def publish_raw_article(self, article: Dict[str, Any]):
        await self.publish(TOPICS["raw"], {
            "type": "article", "version": 2,
            "article_id": article.get("id"),
            "title": article.get("title"),
            "url": article.get("url"),
            "source_id": article.get("source_id"),
            "published_at": article.get("published_at"),
            "content_hash": article.get("content_hash"),
            "content": (article.get("content") or "")[:2000],
            "description": article.get("description", ""),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }, key=article.get("id"))

    async def publish_cleaned(self, article: Dict[str, Any]):
        await self.publish(TOPICS["cleaned"], {
            "type": "cleaned_article", "version": 2,
            "article_id": article.get("id"),
            "title": article.get("title"),
            "clean_text": article.get("clean_text", article.get("content", "")),
            "language": article.get("language", "en"),
            "word_count": article.get("word_count", 0),
        }, key=article.get("id"))

    async def publish_chunks(self, article_id: str, chunks: list[Dict[str, Any]]):
        await self.publish(TOPICS["chunks"], {
            "type": "chunks", "version": 2,
            "article_id": article_id,
            "chunks": chunks,
        }, key=article_id)

    async def publish_nlu_entities(self, article_id: str, entities: list[Dict[str, Any]]):
        await self.publish(TOPICS["nlu_entities"], {
            "type": "nlu_entities", "version": 2,
            "article_id": article_id,
            "entities": entities,
        }, key=article_id)

    async def publish_nlu_topics(self, article_id: str, topics: list[str], weights: list[float]):
        await self.publish(TOPICS["nlu_topics"], {
            "type": "nlu_topics", "version": 2,
            "article_id": article_id,
            "topics": topics,
            "weights": weights,
        }, key=article_id)

    async def publish_embedding(self, article_id: str, vector: list[float], model: str = "sentence-transformers/all-MiniLM-L6-v2"):
        await self.publish(TOPICS["embedding"], {
            "type": "embedding", "version": 2,
            "article_id": article_id,
            "model": model,
            "vector": vector[:384],
            "dimensions": len(vector[:384]),
        }, key=article_id)

    async def publish_trend_signal(self, signal: Dict[str, Any]):
        await self.publish(TOPICS["trend_signals"], {
            "type": "trend_signal", "version": 2,
            **signal,
        }, key=signal.get("category"))

    async def publish_trend_snapshot(self, snapshot: Dict[str, Any]):
        await self.publish(TOPICS["trend_snapshots"], {
            "type": "trend_snapshot", "version": 2,
            **snapshot,
        }, key=snapshot.get("category"))

    async def publish_trend_prediction(self, prediction: Dict[str, Any]):
        await self.publish(TOPICS["trend_predictions"], {
            "type": "trend_prediction", "version": 2,
            **prediction,
        })

    async def publish_alert(self, article: Dict[str, Any]):
        await self.publish(TOPICS["alerts"], {
            "type": "breaking_alert", "version": 2,
            "article_id": article.get("id"),
            "title": article.get("title"),
            "summary": article.get("summary"),
            "importance": article.get("importance"),
            "is_risk": article.get("is_risk", False),
            "priority": article.get("alert_priority", "normal"),
            "category": article.get("category"),
            "trend_score": article.get("trend_score"),
            "burst_score": article.get("burst_score"),
            "alerted_at": datetime.now(timezone.utc).isoformat(),
        }, key=article.get("article_id"))

    async def publish_user_event(self, event: Dict[str, Any]):
        await self.publish(TOPICS["user_events"], {
            "type": "user_event", "version": 2,
            **event,
        }, key=event.get("user_id", "anonymous"))

    # ── Consumer creation ─────────────────────────────────────────────────

    def _create_consumer(self, topic_key: str, group_suffix: str = "") -> Optional[Consumer]:
        if not self.is_connected:
            return None
        try:
            consumer = Consumer({
                'bootstrap.servers': KAFKA_BROKER,
                'group.id': _CONSUMER_GROUPS.get(topic_key, f"pulse-{topic_key}-group") + group_suffix,
                'auto.offset.reset': 'earliest',
                'enable.auto.commit': True,
                'max.poll.interval.ms': 300000,
            })
            consumer.subscribe([TOPICS[topic_key]])
            self.consumers[topic_key] = consumer
            return consumer
        except Exception as exc:
            logger.warning("[Kafka] Consumer %s failed: %s", topic_key, exc)
            return None

    async def _run_consumer_loop(self, topic_key: str, handler: Callable[[Dict[str, Any]], Awaitable[None]],
                                 poll_timeout: float = 1.0):
        consumer = self._create_consumer(topic_key)
        if not consumer:
            return
        logger.info("[Kafka] Consumer started for %s", TOPICS[topic_key])
        try:
            while self._running:
                msg = await asyncio.to_thread(consumer.poll, poll_timeout)
                if msg is None:
                    continue
                if msg.error():
                    continue
                try:
                    val_bytes = msg.value()
                    val = json.loads(val_bytes.decode("utf-8")) if val_bytes else {}
                    
                    # Route real signals to CognitiveRuntime
                    await cognitive_runtime.step({
                        "source": "kafka",
                        "topic": topic_key,
                        "payload": val
                    })
                    
                    await handler(val)
                except Exception as exc:

                    logger.error("[Kafka] Handler error for %s: %s", topic_key, exc)
                    val_bytes = msg.value()
                    self._publish_dlq(TOPICS[topic_key], val_bytes.decode("utf-8") if val_bytes else "", str(exc))
        except asyncio.CancelledError:
            pass
        finally:
            consumer.close()
            logger.info("[Kafka] Consumer stopped for %s", TOPICS[topic_key])

    # ── Topic handlers ────────────────────────────────────────────────────

    async def _handle_raw(self, msg: Dict[str, Any]):
        logger.debug("[Kafka] Raw article: %s", msg.get("title", "")[:60])

    async def _handle_cleaned(self, msg: Dict[str, Any]):
        logger.debug("[Kafka] Cleaned: %s", msg.get("article_id", ""))

    async def _handle_nlu_entities(self, msg: Dict[str, Any]):
        entities = msg.get("entities", [])
        if entities:
            try:
                from db import db_cursor  # type: ignore
                with db_cursor() as cur:
                    for ent in entities:
                        cur.execute(
                            """INSERT INTO entities (name, type, metadata)
                               VALUES (%s, %s, %s)
                               ON CONFLICT (name) DO UPDATE SET mention_count = entities.mention_count + 1""",
                            (ent.get("name"), ent.get("type", "unknown"),
                             json.dumps(ent.get("metadata", {}))),
                        )
            except Exception as exc:
                logger.debug("[Kafka] Entity persist: %s", exc)

    async def _handle_trend_signals(self, msg: Dict[str, Any]):
        try:
            from services.ml_pipeline import forecaster
            forecaster.compute_trend_signal(msg.get("category", "other"))
        except Exception as exc:
            logger.debug("[Kafka] Trend signal: %s", exc)

    async def _handle_user_events(self, msg: Dict[str, Any]):
        event_type = msg.get("event_type", "unknown")
        logger.debug("[Kafka] User event: %s", event_type)

    async def _handle_alerts(self, msg: Dict[str, Any]):
        logger.info("[Kafka] Alert: %s (priority=%s)", msg.get("title", "")[:60], msg.get("priority"))

    # ── Start pipeline ────────────────────────────────────────────────────

    async def start_pipeline(self):
        if not self.is_connected:
            return
        self._running = True
        consumers = [
            ("raw", self._handle_raw),
            ("cleaned", self._handle_cleaned),
            ("nlu_entities", self._handle_nlu_entities),
            ("trend_signals", self._handle_trend_signals),
            ("alerts", self._handle_alerts),
            ("user_events", self._handle_user_events),
        ]
        for topic_key, handler in consumers:
            asyncio.create_task(self._run_consumer_loop(topic_key, handler))
        logger.info("[Kafka] Pipeline started — %d consumers", len(consumers))

    def stop(self):
        self._running = False
        for name, c in self.consumers.items():
            try:
                c.close()
            except Exception:
                pass
        if self.producer:
            self.producer.flush(10)
            
        cognitive_runtime.stop()
        logger.info("[Kafka] Pipeline stopped")

    async def start_bg_flush(self, interval: int = 5):
        while self._running and self.producer:
            self.producer.poll(0)
            await asyncio.sleep(interval)


kafka_manager = KafkaManager()


async def start_kafka_pipeline():
    await kafka_manager.connect()
    
    # Start the cognitive maintenance loop
    cognitive_runtime.start()
    
    if kafka_manager.is_connected:
        asyncio.create_task(kafka_manager.start_bg_flush())
        await kafka_manager.start_pipeline()

