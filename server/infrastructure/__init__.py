"""
Infrastructure components for production-grade AI Girl system.
Includes Redis, PostgreSQL, observability, and CLI display systems.
"""

from .redis_manager import RedisManager, get_redis
from .postgres_manager import PostgresManager, get_postgres
from .observability import logger, log_emotion_update, log_trust_update, log_contradiction
from .cli_display import CLIDisplay, get_cli_display

__all__ = [
    'RedisManager',
    'get_redis',
    'PostgresManager',
    'get_postgres',
    'logger',
    'log_emotion_update',
    'log_trust_update',
    'log_contradiction',
    'CLIDisplay',
    'get_cli_display'
]
