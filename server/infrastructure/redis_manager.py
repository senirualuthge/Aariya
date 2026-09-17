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
        if self.use_fallback or self.client is None:
            self._local_cache[key] = json.dumps(value)
        else:
            self.client.set(key, json.dumps(value))

    def get(self, key):
        if self.use_fallback or self.client is None:
            val = self._local_cache.get(key)
            return json.loads(val) if val else None
        else:
            val = self.client.get(key)
            return json.loads(val) if val else None

    def get_trust_score(self, user_id):
        """Cached trust score (float or None). Works on Redis and fallback."""
        try:
            val = self.get(f"trust:{user_id}")
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def set_trust_score(self, user_id, score):
        self.set(f"trust:{user_id}", float(score))

    def get_contradiction_history(self, user_id):
        """Cached contradiction-EMA (float or None)."""
        try:
            val = self.get(f"contradiction_ema:{user_id}")
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    def set_contradiction_history(self, user_id, ema):
        self.set(f"contradiction_ema:{user_id}", float(ema))

    def get_session_state(self, key):
        """Session state dict for a state-machine key (or None)."""
        val = self.get(key)
        return val if isinstance(val, dict) else None

    def update_session_field(self, key, field, value):
        """Update one field of the stored session-state dict."""
        data = self.get(key)
        data = data if isinstance(data, dict) else {}
        data[field] = value
        self.set(key, data)
        return data

_redis_mgr = None
def get_redis():
    global _redis_mgr
    if not _redis_mgr:
        _redis_mgr = RedisManager()
    return _redis_mgr