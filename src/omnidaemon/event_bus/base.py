from abc import ABC, abstractmethod
from typing import Any, Callable


class BaseEventBus(ABC):
    """Abstract event bus contract. Implement drivers for RedisStreams/Kafka/NATS/RabbitMQ."""

    @abstractmethod
    async def connect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError

    @abstractmethod
    async def publish(self, topic: str, message: dict) -> None:
        raise NotImplementedError

    @abstractmethod
    async def subscribe(self, topic: str, callback: Callable[[dict], Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    async def unsubscribe(self, topic: str) -> None:
        raise NotImplementedError
