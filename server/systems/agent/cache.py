from typing import Dict, Any, Optional
import time
import json
import hashlib
import logging
from server.systems.agent.config import config

logger = logging.getLogger(__name__)

class CacheManager:
    """
    Manages caching of query results and intermediate reasoning steps.
    """
    
    def __init__(self):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.ttl = 3600  # 1 hour default TTL
        
    def get(self, key: str) -> Optional[Any]:
        """Retrieve item from cache if valid."""
        if key in self.cache:
            entry = self.cache[key]
            if time.time() < entry["expires"]:
                return entry["data"]
            else:
                del self.cache[key]
        return None
        
    def set(self, key: str, value: Any, ttl: int = 3600):
        """Store item in cache."""
        self.cache[key] = {
            "data": value,
            "expires": time.time() + ttl
        }
        
    def generate_key(self, query: str) -> str:
        """Generate hash key for a query."""
        return hashlib.md5(query.encode()).hexdigest()

# Global instance
cache = CacheManager()
