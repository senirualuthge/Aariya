"""
Redis-backed fan-out for swarm events (AGENT_UPDATE / AGENT_EVOLVED).

Every published event is ALSO kept in an in-process ring buffer, so
subscribers (e.g. /api/swarm/ws) can still deliver REAL events when Redis is
offline — no pulse is silently dropped just because the broker is missing.
"""

import json
import threading
import time
from collections import deque
from typing import Dict

from server.infrastructure.redis_manager import get_redis

# In-process ring of recent events — the no-Redis delivery path.
_recent: deque = deque(maxlen=200)
_lock = threading.Lock()
_cursor_seq = 0  # monotonically increasing id for cursor-based draining


def recent_events(since: int = 0) -> list:
    """Events with seq > since, oldest first."""
    with _lock:
        return [e for e in _recent if e.get("seq", 0) > since]


def publish(event_type: str, data: dict):
    global _cursor_seq
    with _lock:
        _cursor_seq += 1
        entry = {"seq": _cursor_seq,
                 "ts": time.time(),
                 "type": event_type,
                 "data": data}
        _recent.append(entry)

    try:
        redis_mgr = get_redis()
        if redis_mgr and not redis_mgr.use_fallback and redis_mgr.client:
            redis_mgr.client.publish(
                "swarm_events",
                json.dumps({"type": event_type, "data": data}))
    except Exception:
        # Redis down — the ring buffer above still carries the event.
        pass
    return entry
