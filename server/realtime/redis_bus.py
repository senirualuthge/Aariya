import json
from server.infrastructure.redis_manager import get_redis

def publish(event_type: str, data: dict):
    redis_mgr = get_redis()
    if redis_mgr and not redis_mgr.use_fallback:
        redis_mgr.client.publish("swarm_events", json.dumps({"type": event_type, "data": data}))