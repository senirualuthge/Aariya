import asyncio
from typing import Dict, Any, Callable, Awaitable
import logging

logger = logging.getLogger("aariya.streaming")

class StreamPublisher:
    """
    Abstract interface for publishing events to a distributed message broker (Kafka/Redis).
    Currently implemented as an abstraction layer to allow dropping in KafkaProducer 
    or Redis PubSub without rewriting the agent logic.
    """
    def __init__(self, topic: str):
        self.topic = topic
        logger.info(f"Initialized StreamPublisher for topic: {topic}")
        
    async def publish(self, payload: Dict[str, Any]):
        """Publish payload to the topic."""
        # TODO: Refactor loop to distribute: 
        # await redis.publish(self.topic, json.dumps(payload))
        pass

class StreamSubscriber:
    """
    Abstract interface for subscribing to a distributed message broker (Kafka/Redis).
    """
    def __init__(self, topic: str):
        self.topic = topic
        self.handlers: list[Callable[[Dict[str, Any]], Awaitable[None]]] = []
        logger.info(f"Initialized StreamSubscriber for topic: {topic}")
        
    def add_handler(self, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        self.handlers.append(handler)
        
    async def listen(self):
        """
        Starts listening to the topic. In a distributed setup, this would be an infinite loop
        consuming from Kafka or Redis streams.
        """
        # Example for future distributed node:
        # async for msg in subscription:
        #    for handler in self.handlers:
        #        await handler(msg.value)
        pass
