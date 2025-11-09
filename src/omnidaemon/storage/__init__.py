"""
OmniDaemon Storage Layer

Unified persistence layer for all OmniDaemon data:
- Agent registry
- Task results
- Metrics
- Configuration

Supports multiple backends: JSON (local), Redis, PostgreSQL, MongoDB

"""

from typing import Dict, Type
from decouple import config

from omnidaemon.storage.base import BaseStore
from omnidaemon.storage.json_store import JSONStore
from omnidaemon.storage.redis_store import RedisStore


STORAGE_BACKENDS: Dict[str, Type[BaseStore]] = {
    "json": JSONStore,
    "redis": RedisStore,
}


def create_store(backend_name: str, **kwargs) -> BaseStore:
    """
    Factory function to create storage backend instance.

    Args:
        backend_name: Type of storage ("json", "redis", etc.)
        **kwargs: Backend-specific configuration

    Returns:
        Configured storage instance

    Raises:
        ValueError: If backend type is unsupported
    """
    backend_cls = STORAGE_BACKENDS.get(backend_name.lower())
    if not backend_cls:
        available = ", ".join(STORAGE_BACKENDS.keys())
        raise ValueError(
            f"Unsupported storage backend: {backend_name}. Available: {available}"
        )
    return backend_cls(**kwargs)


_backend_type = config("STORAGE_BACKEND", default="json")

if _backend_type.lower() == "json":
    storage_dir = config("JSON_STORAGE_DIR", default=".omnidaemon_data")
    store = create_store("json", storage_dir=storage_dir)
elif _backend_type.lower() == "redis":
    redis_url = config("REDIS_URL", default="redis://localhost:6379")
    key_prefix = config("REDIS_KEY_PREFIX", default="omni")
    store = create_store("redis", redis_url=redis_url, key_prefix=key_prefix)
else:
    # Fallback to JSON
    store = create_store("json", storage_dir=".omnidaemon_data")


__all__ = [
    "BaseStore",
    "JSONStore",
    "RedisStore",
    "create_store",
    "store",
    "STORAGE_BACKENDS",
]
