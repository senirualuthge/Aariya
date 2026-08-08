import redis
import os
import json

class RedisManager:
    def __init__(self):
        self.host = os.getenv("REDIS_HOST", "localhost")
        self.port = int(os.getenv("REDIS_PORT", 6379))
        self.use_fallback = False
        self.client = None
        self._local_cache = {}

        try:
            self.client = redis.Redis(host=self.host, port=self.port, decode_responses=True)
            self.client.ping()
        except Exception:
            self.use_fallback = True

    def set(self, key, value):
        if self.use_fallback:
            self._local_cache[key] = json.dumps(value)
        else:
            self.client.set(key, json.dumps(value))

    def get(self, key):
        if self.use_fallback:
            val = self._local_cache.get(key)
            return json.loads(val) if val else None
        else:
            val = self.client.get(key)
            return json.loads(val) if val else None

_redis_mgr = None
def get_redis():
    global _redis_mgr
    if not _redis_mgr:
        _redis_mgr = RedisManager()
    return _redis_mgr