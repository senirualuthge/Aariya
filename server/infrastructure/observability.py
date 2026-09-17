"""
Structured logging and observability system.
Provides JSON logs with session trace IDs, emotion timelines, and performance metrics.
"""

import json
import time
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime
import sys


class StructuredLogger:
    """JSON structured logger with session trace IDs."""
    
    def __init__(self, service_name: str = "ai-girl-brain"):
        self.service_name = service_name
        self.latency_budgets = {
            'asr': 300,  # ms
            'llm': 1500,  # ms
            'tts': 200,  # ms
            'total_turn': 2000  # ms
        }
    
    def _log(self, level: str, message: str, **kwargs):
        """Internal logging method."""
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'service': self.service_name,
            'level': level,
            'message': message,
            **kwargs
        }
        print(json.dumps(log_entry), file=sys.stderr if level == 'ERROR' else sys.stdout)

        # Feed the dashboard brain-log ring (mobile analytics shows these).
        try:
            from server.routers.dashboard_ws import push_brain_log
            push_brain_log(f"[{level}] {message}")
        except Exception:
            pass

        # --- PHASE 1: Emit Signal for important events ---
        if level in ["ERROR", "WARN"]:
            try:
                from server.infrastructure.signal_bus import get_signal_bus, Signal
                bus = get_signal_bus()

                signal = Signal(
                    type="bug" if level == "ERROR" else "system",
                    severity="critical" if level == "ERROR" else "warning",
                    source=self.service_name,
                    payload={
                        "title": message,
                        "description": str(kwargs.get('error', message)),
                        "meta": kwargs,
                    },
                )

                # Emit via task to avoid blocking the synchronous logging call
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(bus.emit(signal))
                except RuntimeError:
                    # No running loop (early startup / sync context): persist
                    # and mirror synchronously so the signal is never lost.
                    bus.persist(signal)
                    bus.record(signal)
            except Exception:
                # Never let signal emission crash the logger itself
                pass
    
    def info(self, message: str, **kwargs):
        """Log info message."""
        self._log('INFO', message, **kwargs)
    
    def warn(self, message: str, **kwargs):
        """Log warning message."""
        self._log('WARN', message, **kwargs)
    
    def error(self, message: str, **kwargs):
        """Log error message."""
        self._log('ERROR', message, **kwargs)
    
    def debug(self, message: str, **kwargs):
        """Log debug message."""
        self._log('DEBUG', message, **kwargs)


# Global logger instance
logger = StructuredLogger()


def log_emotion_update(
    session_id: str,
    user_id: str,
    emotion_input: Dict[str, float],
    fused_emotion: Dict[str, float],
    confidence: Optional[Dict[str, float]] = None
):
    """Log emotion fusion event."""
    logger.info(
        "Emotion update",
        session_id=session_id,
        user_id=user_id,
        emotion_input=emotion_input,
        fused_emotion=fused_emotion,
        confidence=confidence or {}
    )


def log_trust_update(
    session_id: str,
    user_id: str,
    trust_before: float,
    trust_after: float,
    trust_delta: float,
    trigger_event: str
):
    """Log trust score change."""
    logger.info(
        "Trust update",
        session_id=session_id,
        user_id=user_id,
        trust_before=round(trust_before, 3),
        trust_after=round(trust_after, 3),
        trust_delta=round(trust_delta, 3),
        trigger_event=trigger_event
    )


def log_contradiction(
    session_id: str,
    user_id: str,
    turn_number: int,
    contradiction_score: float,
    contradiction_ema: float,
    modalities: Dict[str, Any]
):
    """Log contradiction detection."""
    logger.info(
        "Contradiction detected",
        session_id=session_id,
        user_id=user_id,
        turn_number=turn_number,
        contradiction_score=round(contradiction_score, 3),
        contradiction_ema=round(contradiction_ema, 3),
        modalities=modalities
    )


def log_personality_drift(
    session_id: str,
    user_id: str,
    personality_before: Dict[str, float],
    personality_after: Dict[str, float],
    drift_delta: Dict[str, float]
):
    """Log personality drift event."""
    logger.info(
        "Personality drift",
        session_id=session_id,
        user_id=user_id,
        personality_before=personality_before,
        personality_after=personality_after,
        drift_delta=drift_delta
    )


def log_latency(
    session_id: str,
    component: str,
    latency_ms: float,
    exceeded_budget: bool = False
):
    """Log component latency."""
    logger.info(
        "Latency measurement",
        session_id=session_id,
        component=component,
        latency_ms=round(latency_ms, 2),
        exceeded_budget=exceeded_budget
    )


def log_safety_constraint_violation(
    session_id: str,
    user_id: str,
    constraint_type: str,
    proposed_value: Any,
    enforced_value: Any,
    reason: str
):
    """Log when safety constraints block a behavior."""
    logger.warn(
        "Safety constraint enforced",
        session_id=session_id,
        user_id=user_id,
        constraint_type=constraint_type,
        proposed_value=proposed_value,
        enforced_value=enforced_value,
        reason=reason
    )


def log_neural_network_fallback(
    session_id: str,
    reason: str,
    fallback_method: str
):
    """Log when system falls back from neural network to heuristics."""
    logger.warn(
        "Neural network fallback",
        session_id=session_id,
        reason=reason,
        fallback_method=fallback_method
    )


def log_failure_containment(
    session_id: str,
    component: str,
    error: str,
    degradation_mode: str
):
    """Log graceful degradation event."""
    logger.warn(
        "Failure containment activated",
        session_id=session_id,
        component=component,
        error=error,
        degradation_mode=degradation_mode
    )


class LatencyTracker:
    """Context manager for tracking operation latency."""
    
    def __init__(self, session_id: str, component: str, budget_ms: Optional[float] = None):
        self.session_id = session_id
        self.component = component
        self.budget_ms = budget_ms
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            latency_ms = (time.time() - self.start_time) * 1000
            exceeded = bool(self.budget_ms and latency_ms > self.budget_ms)
            log_latency(self.session_id, self.component, latency_ms, exceeded)
