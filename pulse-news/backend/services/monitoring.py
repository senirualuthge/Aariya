from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger("pulse.monitoring")

_OTEL_ENABLED = False
try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    _OTEL_ENABLED = True
except ImportError:
    pass


class PulseMetrics:
    def __init__(self):
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._latencies: Dict[str, list[float]] = defaultdict(list)
        self._errors: Dict[str, int] = defaultdict(int)
        self._start_time = time.time()

    def inc(self, name: str, value: int = 1):
        self._counters[name] += value

    def gauge(self, name: str, value: float):
        self._gauges[name] = value

    def record_latency(self, name: str, seconds: float):
        self._latencies[name].append(seconds)
        if len(self._latencies[name]) > 1000:
            self._latencies[name] = self._latencies[name][-1000:]

    def record_error(self, name: str):
        self._errors[name] += 1
        self.inc(f"errors.{name}")

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        uptime = now - self._start_time
        lat_summary = {}
        for name, vals in self._latencies.items():
            if vals:
                lat_summary[name] = {
                    "avg": round(sum(vals) / len(vals), 4),
                    "max": round(max(vals), 4),
                    "min": round(min(vals), 4),
                    "count": len(vals),
                }
        return {
            "uptime_seconds": round(uptime, 1),
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "latencies": lat_summary,
            "errors": dict(self._errors),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


metrics = PulseMetrics()


def track_latency(name: str):
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = fn(*args, **kwargs)
                metrics.record_latency(name, time.time() - start)
                metrics.inc(f"calls.{name}")
                return result
            except Exception as exc:
                metrics.record_error(name)
                raise exc
        return wrapper
    return decorator


def init_opentelemetry(service_name: str = "pulse-news"):
    if not _OTEL_ENABLED:
        logger.info("[OTel] OpenTelemetry not installed — metrics only")
        return

    try:
        provider = TracerProvider()
        processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

        try:
            HTTPXClientInstrumentor().instrument()
        except Exception as exc:
            logger.debug("[OTel] HTTPX instrumentation failed: %s", exc)

        logger.info("[OTel] OpenTelemetry initialized for %s", service_name)
    except Exception as exc:
        logger.warning("[OTel] Init failed: %s", exc)


def flush_metrics():
    pass


class HealthCheck:
    def __init__(self):
        self._checks: Dict[str, Dict[str, Any]] = {}

    def register(self, name: str, check_fn: Callable[[], bool], timeout: float = 5.0):
        self._checks[name] = {"fn": check_fn, "timeout": timeout, "last": None, "ok": False}

    def run_all(self) -> Dict[str, Any]:
        results = {}
        all_ok = True
        for name, cfg in self._checks.items():
            try:
                ok = cfg["fn"]()
                cfg["ok"] = ok
                results[name] = {"ok": ok}
                if not ok:
                    all_ok = False
            except Exception as exc:
                cfg["ok"] = False
                results[name] = {"ok": False, "error": str(exc)}
                all_ok = False
        return {"healthy": all_ok, "checks": results}


health = HealthCheck()


def _check_db():
    try:
        from db import db_cursor  # type: ignore
        with db_cursor() as cur:
            cur.execute("SELECT 1")
            return True
    except Exception as exc:
        logger.warning("[Health] DB check failed: %s", exc)
        return False


def _check_kafka():
    try:
        from kafka_pipeline import kafka_manager
        return kafka_manager.is_connected
    except Exception as exc:
        logger.warning("[Health] Kafka check failed: %s", exc)
        return False


def _check_qdrant():
    try:
        from services.qdrant_rag import qdrant_db
        return qdrant_db.is_ready
    except Exception as exc:
        logger.warning("[Health] Qdrant check failed: %s", exc)
        return False


health.register("database", _check_db)
health.register("kafka", _check_kafka)
health.register("qdrant", _check_qdrant)
