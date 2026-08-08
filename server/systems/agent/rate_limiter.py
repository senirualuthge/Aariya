import time
import logging
from server.systems.agent.config import config

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    Manages request rates to external APIs and internal resources.
    Token bucket algorithm.
    """
    
    def __init__(self):
        self.tokens = 10
        self.rate = 1  # tokens per second
        self.last_update = time.time()
        self.capacity = 10
        
    def acquire(self) -> bool:
        """Attempt to acquire a token."""
        now = time.time()
        elapsed = now - self.last_update
        
        # Refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now
        
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

# Global instance
rate_limiter = RateLimiter()
