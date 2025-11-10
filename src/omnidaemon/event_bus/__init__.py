"""
Event Bus Module - Dependency Injection
========================================

This module provides a unified, pluggable event bus layer for OmniDaemon.
It follows the same Dependency Injection pattern as the storage layer.

The event bus backend is determined by environment variables:
- EVENT_BUS_TYPE: Backend type (redis_stream, rabbitmq, kafka)
- REDIS_URL: Redis connection URL (for redis_stream backend)

Usage:
    from omnidaemon.event_bus import event_bus

    # Event bus is pre-configured and ready to use
    await event_bus.connect()
    await event_bus.publish({"topic": "test", "payload": {...}})
"""

from typing import Dict, Type, Any
from decouple import config
from omnidaemon.event_bus.base import BaseEventBus
from omnidaemon.event_bus.redis_stream_bus import RedisStreamEventBus


# Registry of available event bus backends
EVENT_BUS_BACKENDS: Dict[str, Type[Any]] = {
    "redis_stream": RedisStreamEventBus,
}


def create_event_bus(backend_name: str, **kwargs) -> BaseEventBus:
    """
    Factory function to create an event bus instance.

    Args:
        backend_name: Name of the backend (e.g., 'redis_stream')
        **kwargs: Backend-specific configuration

    Returns:
        BaseEventBus: Configured event bus instance

    Raises:
        ValueError: If backend is not supported
    """
    backend_cls = EVENT_BUS_BACKENDS.get(backend_name.lower())
    if not backend_cls:
        available = ", ".join(EVENT_BUS_BACKENDS.keys())
        raise ValueError(
            f"Unsupported event bus backend: {backend_name}. Available: {available}"
        )
    return backend_cls(**kwargs)


_backend_type = config("EVENT_BUS_TYPE", default="redis_stream")

if _backend_type.lower() == "redis_stream":
    redis_url = config("REDIS_URL", default="redis://localhost:6379")
    event_bus = create_event_bus(
        "redis_stream",
        redis_url=redis_url,
        default_maxlen=10_000,
        reclaim_interval=30,
        default_reclaim_idle_ms=180_000,
        default_dlq_retry_limit=3,
    )

else:
    # Default to redis_stream
    redis_url = config("REDIS_URL", default="redis://localhost:6379")
    event_bus = create_event_bus("redis_stream", redis_url=redis_url)


__all__ = [
    "BaseEventBus",
    "RedisStreamEventBus",
    "create_event_bus",
    "event_bus",
    "EVENT_BUS_BACKENDS",
]
