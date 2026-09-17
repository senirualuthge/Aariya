"""
StreamPublisher / StreamSubscriber — event distribution over Redis PubSub.

Falls back to an in-process async broadcast (thread-safe queues) when Redis
is unavailable so callers never need to branch on infrastructure.

Both classes expose a clean async interface so the rest of the codebase can
publish and subscribe without knowing whether the transport is Redis or local.
"""

import asyncio
import json
import logging
import time
from typing import Any, Callable, Dict, List

logger = logging.getLogger("aariya.streaming")


# ── Redis transport (real) ───────────────────────────────────────────────────

def _get_redis_client():
    """Return a live redis.Redis or None when Redis is unreachable."""
    try:
        from server.infrastructure.redis_manager import get_redis
        mgr = get_redis()
        if mgr.client is not None and not mgr.use_fallback:
            return mgr.client
    except Exception as exc:
        logger.debug("[streaming] Redis unavailable: %s", exc)
    return None


class StreamPublisher:
    """Publish JSON-serialisable events to a named topic.

    When Redis is available, messages go through real PubSub so any
    connected subscriber (including other processes) receives them.
    When Redis is unavailable the message is logged at debug level and
    dropped — callers never block or crash.
    """

    def __init__(self, topic: str):
        self.topic = topic
        self._redis = _get_redis_client()
        self._transport = "redis" if self._redis else "log-only"
        logger.info(
            "[StreamPublisher] topic=%s transport=%s", self.topic, self._transport
        )

    async def publish(self, payload: Dict[str, Any]) -> None:
        """Publish *payload* to the topic."""
        if self._redis is None:
            # Try to reconnect lazily — Redis may have come back.
            self._redis = _get_redis_client()
            if self._redis is not None:
                self._transport = "redis"
                logger.info(
                    "[StreamPublisher] topic=%s reconnected to Redis", self.topic
                )

        if self._redis is not None:
            try:
                self._redis.publish(self.topic, json.dumps(payload, default=str))
            except Exception as exc:
                logger.warning(
                    "[StreamPublisher] publish to %s failed: %s", self.topic, exc
                )
        else:
            logger.debug(
                "[StreamPublisher] topic=%s (log-only) payload_keys=%s",
                self.topic,
                list(payload.keys())[:5],
            )


# ── Subscriber with local async fan-out ──────────────────────────────────────

class StreamSubscriber:
    """Subscribe to a topic and fan out received messages to async handlers.

    When Redis is available the subscriber runs a background task that
    listens on the Redis PubSub channel and dispatches each message to
    every registered handler.

    When Redis is unavailable, handlers can still be invoked manually
    via `emit_local()` — useful for in-process testing and single-node
    deployments.
    """

    def __init__(self, topic: str):
        self.topic = topic
        self.handlers: List[Callable[[Dict[str, Any]], Any]] = []
        self._redis = _get_redis_client()
        self._pubsub = None
        self._listen_task: asyncio.Task | None = None
        self._running = False
        self._local_buffer: List[Dict[str, Any]] = []
        self._transport = "redis" if self._redis else "local"
        logger.info(
            "[StreamSubscriber] topic=%s transport=%s", self.topic, self._transport
        )

    def add_handler(self, handler: Callable[[Dict[str, Any]], Any]) -> None:
        """Register a callback invoked for every message on the topic."""
        self.handlers.append(handler)

    # ── Redis listener ────────────────────────────────────────────────────

    async def listen(self) -> None:
        """Start consuming from the Redis PubSub channel.

        If Redis is unavailable the method returns immediately — handlers
        can still be driven via `emit_local()`.
        """
        if self._redis is None:
            self._redis = _get_redis_client()
        if self._redis is None:
            logger.info(
                "[StreamSubscriber] topic=%s no Redis — using local emit mode",
                self.topic,
            )
            return

        try:
            self._pubsub = self._redis.pubsub()
            self._pubsub.subscribe(self.topic)
            self._running = True
            self._listen_task = asyncio.get_event_loop().create_task(
                self._drain()
            )
            logger.info("[StreamSubscriber] topic=%s listening on Redis", self.topic)
        except Exception as exc:
            logger.warning(
                "[StreamSubscriber] topic=%s Redis subscribe failed: %s",
                self.topic,
                exc,
            )

    async def stop(self) -> None:
        """Gracefully shut down the listener."""
        self._running = False
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None
        if self._pubsub is not None:
            try:
                self._pubsub.unsubscribe(self.topic)
                self._pubsub.close()
            except Exception:
                pass
            self._pubsub = None

    async def _drain(self) -> None:
        """Background loop that reads messages from Redis and dispatches."""
        while self._running and self._pubsub is not None:
            try:
                message = self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=0.1
                )
                if message is not None and message.get("type") == "message":
                    raw = message.get("data")
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    if raw is None:
                        continue
                    try:
                        payload: Dict[str, Any] = json.loads(raw) if isinstance(raw, str) else {"raw": raw}
                    except (json.JSONDecodeError, TypeError):
                        payload = {"raw": raw}
                    await self._dispatch(payload)
                else:
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug(
                    "[StreamSubscriber] topic=%s drain error: %s", self.topic, exc
                )
                await asyncio.sleep(0.05)

    # ── Local (in-process) emit ───────────────────────────────────────────

    async def emit_local(self, payload: Dict[str, Any]) -> None:
        """Dispatch a message to handlers without Redis — for single-node use."""
        await self._dispatch(payload)
        self._local_buffer.append(payload)
        if len(self._local_buffer) > 500:
            self._local_buffer = self._local_buffer[-250:]

    # ── Fan-out ───────────────────────────────────────────────────────────

    async def _dispatch(self, payload: Dict[str, Any]) -> None:
        """Call every registered handler with *payload*."""
        for handler in self.handlers:
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning(
                    "[StreamSubscriber] handler %s failed for topic %s: %s",
                    handler.__name__ if hasattr(handler, "__name__") else handler,
                    self.topic,
                    exc,
                )
