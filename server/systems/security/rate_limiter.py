"""
Rate Limiter — sliding-window per-IP / per-client rate limiter for WebSocket messages.

Usage (in WebSocket handler):
    from server.systems.security.rate_limiter import get_rate_limiter
    limiter = get_rate_limiter()
    if limiter.is_limited("127.0.0.1"):
        await websocket.close(code=1008)
        return
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Limits
MAX_REQUESTS_PER_SECOND = 10    # burst cap
MAX_REQUESTS_PER_MINUTE = 120   # sustained cap
WINDOW_SECOND = 1.0
WINDOW_MINUTE = 60.0


@dataclass
class _ClientBucket:
    timestamps: List[float] = field(default_factory=list)
    blocked_until: float = 0.0


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: Dict[str, _ClientBucket] = defaultdict(_ClientBucket)

    def is_limited(self, client_id: str) -> bool:
        """
        Return True if the client is currently rate-limited.
        Side-effect: records this call as a new request.
        """
        bucket = self._buckets[client_id]
        now = time.time()

        # Still in a hard block period?
        if now < bucket.blocked_until:
            return True

        # Prune old timestamps
        bucket.timestamps = [t for t in bucket.timestamps if now - t < WINDOW_MINUTE]

        # Count requests in each window
        per_second = sum(1 for t in bucket.timestamps if now - t < WINDOW_SECOND)
        per_minute = len(bucket.timestamps)

        bucket.timestamps.append(now)

        if per_second >= MAX_REQUESTS_PER_SECOND:
            # Short hard-block (3 s) for burst abuse
            bucket.blocked_until = now + 3.0
            return True

        if per_minute >= MAX_REQUESTS_PER_MINUTE:
            # Longer block (30 s) for sustained abuse
            bucket.blocked_until = now + 30.0
            return True

        return False

    def get_stats(self, client_id: str) -> Dict[str, object]:
        """Return current rate stats for a client (for dashboard display)."""
        bucket = self._buckets.get(client_id)
        if not bucket:
            return {"requests_last_minute": 0, "blocked": False}
        now = time.time()
        per_minute = sum(1 for t in bucket.timestamps if now - t < WINDOW_MINUTE)
        return {
            "requests_last_minute": per_minute,
            "blocked": now < bucket.blocked_until,
        }

    def reset(self, client_id: str) -> None:
        """Manually unblock a client (admin action)."""
        if client_id in self._buckets:
            del self._buckets[client_id]


# Module-level singleton
_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter()
    return _limiter
