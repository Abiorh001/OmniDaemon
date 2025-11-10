"""
Redis-based storage implementation for production deployments.

Provides:
- High performance with persistence
- Native TTL support for results
- Atomic operations
- Distributed access
"""

import json
import time
from typing import Dict, Any, List, Optional
from redis import asyncio as aioredis

from omnidaemon.storage.base import BaseStore


class RedisStore(BaseStore):
    """
    Redis-based storage implementation for production deployments.

    This implementation uses Redis to provide high-performance, distributed storage
    with advanced features for production use.

    Features:
        - Automatic TTL: Native Redis expiration for results
        - Hash-based storage: Efficient agent data storage and updates
        - Sorted sets: Time-ordered metrics for easy querying
        - Atomic operations: Thread-safe by design (Redis is single-threaded)
        - Persistence: Supports Redis RDB and AOF persistence
        - Distributed: Multiple instances can share the same Redis backend
        - Streams: Uses Redis Streams for efficient metric storage

    Best for:
        - Production deployments
        - Multi-instance deployments
        - High-throughput scenarios
        - Distributed systems

    Args:
        redis_url: Redis connection URL (e.g., "redis://localhost:6379")
        key_prefix: Prefix for all Redis keys to avoid collisions (default: "omni")

    Attributes:
        redis_url: Redis connection URL
        key_prefix: Prefix for all Redis keys
        _redis: Redis client instance
        _connected: Whether storage is connected
    """

    def __init__(self, redis_url: str, key_prefix: str = "omni") -> None:
        """
        Initialize Redis storage backend.

        Args:
            redis_url: Redis connection URL (e.g., "redis://localhost:6379")
            key_prefix: Prefix for all Redis keys to avoid namespace collisions
                       (default: "omni")
        """
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self._redis: Optional[aioredis.Redis] = None
        self._connected = False

    def _key(self, *parts: str) -> str:
        """
        Build a namespaced Redis key from parts.

        Args:
            *parts: Variable number of string parts to join

        Returns:
            Redis key string in format "{key_prefix}:{part1}:{part2}:..."

        Example:
            _key("agent", "topic", "name") -> "omni:agent:topic:name"
        """
        return f"{self.key_prefix}:{':'.join(parts)}"

    async def connect(self) -> None:
        """
        Establish connection to Redis.

        This method creates an async Redis client connection. It is idempotent
        and will reuse an existing connection if available.

        Raises:
            ConnectionError: If Redis connection fails
        """
        if self._connected and self._redis:
            return

        self._redis = await aioredis.from_url(
            self.redis_url, decode_responses=True, encoding="utf-8"
        )
        self._connected = True

    async def close(self) -> None:
        """
        Close Redis connection and cleanup resources.

        This method gracefully closes the Redis client connection and marks
        the storage as disconnected. It is idempotent.
        """
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._connected = False

    async def health_check(self) -> Dict[str, Any]:
        """
        Check Redis health and connection status.

        This method performs a PING operation to verify Redis connectivity and
        retrieves server information.

        Returns:
            Dictionary containing:
                - status: "healthy" or "unhealthy"
                - backend: "redis"
                - redis_url: Redis connection URL
                - connected: Whether storage is connected
                - latency_ms: Round-trip latency in milliseconds
                - redis_version: Redis server version
                - used_memory: Memory usage (human-readable)
                - connected_clients: Number of connected clients
                - error: Error message if unhealthy
        """
        if not self._redis:
            await self.connect()

        assert self._redis is not None

        try:
            start = time.time()
            await self._redis.ping()  # type: ignore[misc]
            latency = (time.time() - start) * 1000  # ms

            info = await self._redis.info()  # type: ignore[misc]

            return {
                "status": "healthy",
                "backend": "redis",
                "redis_url": self.redis_url,
                "connected": self._connected,
                "latency_ms": round(latency, 2),
                "redis_version": info.get("redis_version"),
                "used_memory": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "redis",
                "error": str(e),
            }

    async def add_agent(self, topic: str, agent_data: Dict[str, Any]) -> None:
        """
        Add or update an agent for a topic (upsert behavior).

        This method stores agent data in a Redis hash and maintains topic indexes
        using Redis sets. It uses a pipeline for atomic operations.

        Args:
            topic: The topic name the agent subscribes to
            agent_data: Dictionary containing agent metadata (must include 'name')

        Raises:
            ValueError: If agent_data is missing the 'name' field
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None

        agent_name = agent_data.get("name")
        if not agent_name:
            raise ValueError("Agent data must include 'name' field")

        agent_key = self._key("agent", topic, agent_name)

        agent_flat = {
            "name": agent_name,
            "callback_name": agent_data.get("callback_name", ""),
            "tools": json.dumps(agent_data.get("tools", [])),
            "description": agent_data.get("description", ""),
            "config": json.dumps(agent_data.get("config", {})),
            "topic": topic,
            "created_at": time.time(),
        }

        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.hset(agent_key, mapping=agent_flat)  # type: ignore[misc]
            await pipe.sadd(self._key("agents", "topic", topic), agent_name)  # type: ignore[misc]
            await pipe.sadd(self._key("topics"), topic)  # type: ignore[misc]
            await pipe.execute()

    async def get_agent(self, topic: str, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific agent by topic and name.

        Args:
            topic: The topic name
            agent_name: The agent name/identifier

        Returns:
            Agent data dictionary with deserialized JSON fields, or None if not found
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None

        agent_key = self._key("agent", topic, agent_name)
        data = await self._redis.hgetall(agent_key)  # type: ignore[misc]

        if not data:
            return None
        return {
            "name": data.get("name"),
            "callback_name": data.get("callback_name"),
            "tools": json.loads(data.get("tools", "[]")),
            "description": data.get("description"),
            "config": json.loads(data.get("config", "{}")),
            "topic": data.get("topic"),
            "created_at": float(data.get("created_at", 0)),
        }

    async def get_agents_by_topic(self, topic: str) -> List[Dict[str, Any]]:
        """
        Get all agents subscribed to a topic.

        Args:
            topic: The topic name

        Returns:
            List of agent data dictionaries for the topic
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        agent_names = await self._redis.smembers(self._key("agents", "topic", topic))  # type: ignore[misc]

        if not agent_names:
            return []

        agents = []
        for agent_name in agent_names:
            agent = await self.get_agent(topic, agent_name)
            if agent:
                agents.append(agent)

        return agents

    async def list_all_agents(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all registered agents grouped by topic.

        Returns:
            Dictionary mapping topic names to lists of agent data dictionaries
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        topics = await self._redis.smembers(self._key("topics"))  # type: ignore[misc]

        if not topics:
            return {}

        result = {}
        for topic in topics:
            agents = await self.get_agents_by_topic(topic)
            if agents:
                result[topic] = agents

        return result

    async def delete_agent(self, topic: str, agent_name: str) -> bool:
        """Delete a specific agent."""
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        agent_key = self._key("agent", topic, agent_name)

        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.delete(agent_key)  # type: ignore[misc]
            await pipe.srem(self._key("agents", "topic", topic), agent_name)  # type: ignore[misc]
            results = await pipe.execute()

        count = await self._redis.scard(self._key("agents", "topic", topic))  # type: ignore[misc]
        if count == 0:
            await self._redis.srem(self._key("topics"), topic)  # type: ignore[misc]
            await self._redis.delete(self._key("agents", "topic", topic))  # type: ignore[misc]

        return results[0] > 0

    async def delete_topic(self, topic: str) -> int:
        """Delete all agents for a topic."""
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        agent_names = await self._redis.smembers(self._key("agents", "topic", topic))  # type: ignore[misc]

        if not agent_names:
            return 0

        agent_keys = [self._key("agent", topic, name) for name in agent_names]

        async with self._redis.pipeline(transaction=True) as pipe:
            for key in agent_keys:
                await pipe.delete(key)  # type: ignore[misc]

            await pipe.delete(self._key("agents", "topic", topic))  # type: ignore[misc]

            await pipe.srem(self._key("topics"), topic)  # type: ignore[misc]

            await pipe.execute()

        return len(agent_names)

    async def save_result(
        self, task_id: str, result: Dict[str, Any], ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Save task result with optional time-to-live.

        This method stores the result in Redis with native TTL support. Results
        are automatically expired by Redis when TTL is reached. A sorted set
        index is maintained for efficient listing.

        Args:
            task_id: Unique task identifier
            result: Dictionary containing task result data
            ttl_seconds: Optional time-to-live in seconds. If specified, Redis
                       will automatically delete the result after this duration.
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        result_key = self._key("result", task_id)
        result_data = {
            "task_id": task_id,
            "result": result,
            "saved_at": time.time(),
        }

        result_json = json.dumps(result_data, default=str)

        if ttl_seconds:
            await self._redis.setex(result_key, ttl_seconds, result_json)
        else:
            await self._redis.set(result_key, result_json)

        await self._redis.zadd(self._key("results", "index"), {task_id: time.time()})

    async def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task result (Redis handles TTL automatically).

        This method retrieves a result from Redis. If the result has expired
        (TTL reached), Redis will return None automatically.

        Args:
            task_id: The task ID to retrieve

        Returns:
            The result data dictionary, or None if not found or expired
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        result_key = self._key("result", task_id)
        data = await self._redis.get(result_key)

        if not data:
            await self._redis.zrem(self._key("results", "index"), task_id)
            return None

        result_data = json.loads(data)
        return result_data.get("result")

    async def delete_result(self, task_id: str) -> bool:
        """Delete a task result."""
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        result_key = self._key("result", task_id)

        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.delete(result_key)
            await pipe.zrem(self._key("results", "index"), task_id)
            results = await pipe.execute()

        return results[0] > 0

    async def list_results(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List recent results."""
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        task_ids = await self._redis.zrevrange(
            self._key("results", "index"), 0, limit - 1
        )

        if not task_ids:
            return []

        results = []
        for task_id in task_ids:
            result_key = self._key("result", task_id)
            data = await self._redis.get(result_key)
            if data:
                results.append(json.loads(data))

        return results

    async def save_metric(self, metric_data: Dict[str, Any]) -> None:
        """
        Save metric to Redis Stream.

        This method uses Redis Streams to store metrics, which is ideal for
        time-series data. The stream automatically maintains order and supports
        efficient range queries.

        Args:
            metric_data: Dictionary containing metric information

        Note:
            - Stream is capped at 100,000 entries (oldest are removed)
            - Metrics are automatically timestamped
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        metric_data["saved_at"] = time.time()

        await self._redis.xadd(
            self._key("metrics", "stream"),
            {"data": json.dumps(metric_data, default=str)},
            maxlen=100000,
            approximate=True,
        )

    async def get_metrics(
        self, topic: Optional[str] = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Get recent metrics from Redis Stream.

        This method retrieves metrics from the Redis Stream, optionally filtered
        by topic. Metrics are returned in reverse chronological order (most recent first).

        Args:
            topic: Optional topic name to filter metrics
            limit: Maximum number of metrics to return (default: 1000)

        Returns:
            List of metric dictionaries with stream_id added, most recent first.
            If topic is specified, only metrics for that topic are returned.
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        entries = await self._redis.xrevrange(
            self._key("metrics", "stream"), count=limit
        )

        metrics = []
        for entry_id, fields in entries:
            try:
                metric = json.loads(fields.get("data", "{}"))

                if topic and metric.get("topic") != topic:
                    continue

                metric["stream_id"] = entry_id
                metrics.append(metric)
            except json.JSONDecodeError:
                continue

        return metrics

    async def save_config(self, key: str, value: Any) -> None:
        """
        Save a configuration value.

        Args:
            key: Configuration key
            value: Configuration value (will be JSON-serialized)
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        config_key = self._key("config", key)
        await self._redis.set(config_key, json.dumps(value, default=str))

    async def get_config(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.

        Args:
            key: Configuration key to retrieve
            default: Default value if key is not found

        Returns:
            The configuration value (deserialized from JSON) or the default value
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        config_key = self._key("config", key)
        data = await self._redis.get(config_key)

        if data is None:
            return default

        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return default

    async def clear_agents(self) -> int:
        """Clear all agents."""
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        pattern = self._key("agent", "*")
        count = 0

        async for key in self._redis.scan_iter(match=pattern):
            await self._redis.delete(key)
            count += 1

        await self._redis.delete(self._key("topics"))

        topic_sets_pattern = self._key("agents", "topic", "*")
        async for key in self._redis.scan_iter(match=topic_sets_pattern):
            await self._redis.delete(key)

        return count

    async def clear_results(self) -> int:
        """Clear all results."""
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        pattern = self._key("result", "*")
        count = 0

        async for key in self._redis.scan_iter(match=pattern):
            await self._redis.delete(key)
            count += 1

        await self._redis.delete(self._key("results", "index"))

        return count

    async def clear_metrics(self) -> int:
        """Clear all metrics."""
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        count = await self._redis.xlen(self._key("metrics", "stream"))
        await self._redis.delete(self._key("metrics", "stream"))

        return count

    async def clear_all(self) -> Dict[str, int]:
        """
        Clear all OmniDaemon data from Redis.

        This method removes all agents, results, metrics, and configuration
        from Redis. Use with caution!

        Returns:
            Dictionary with counts of deleted items by category
        """
        agents_count = await self.clear_agents()
        results_count = await self.clear_results()
        metrics_count = await self.clear_metrics()

        if not self._redis:
            await self.connect()
        assert self._redis is not None

        pattern = self._key("config", "*")
        config_count = 0
        async for key in self._redis.scan_iter(match=pattern):
            await self._redis.delete(key)
            config_count += 1

        return {
            "agents": agents_count,
            "results": results_count,
            "metrics": metrics_count,
            "config": config_count,
        }
