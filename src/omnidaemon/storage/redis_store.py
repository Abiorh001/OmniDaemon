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
    Redis-based storage implementation.

    Smart features:
    - Automatic TTL for results (native Redis expiration)
    - Hash-based storage for agents (efficient updates)
    - Sorted sets for metrics (time-ordered, easy to query)
    - Atomic operations (thread-safe by design)
    - Persistence (Redis RDB/AOF)
    """

    def __init__(self, redis_url: str, key_prefix: str = "omni"):
        """
        Initialize Redis storage.

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379)
            key_prefix: Prefix for all Redis keys (default: "omni")
        """
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self._redis: Optional[aioredis.Redis] = None
        self._connected = False

    def _key(self, *parts: str) -> str:
        """Build a namespaced Redis key."""
        return f"{self.key_prefix}:{':'.join(parts)}"

    async def connect(self) -> None:
        """Connect to Redis."""
        if self._connected and self._redis:
            return

        self._redis = await aioredis.from_url(
            self.redis_url, decode_responses=True, encoding="utf-8"
        )
        self._connected = True

    async def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
            self._redis = None
            self._connected = False

    async def health_check(self) -> Dict[str, Any]:
        """Check Redis health."""
        if not self._redis:
            await self.connect()

        try:
            start = time.time()
            await self._redis.ping()
            latency = (time.time() - start) * 1000  # ms

            info = await self._redis.info()

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
        Add or update an agent.remove old, add new
        """
        if not self._redis:
            await self.connect()

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
            await pipe.hset(agent_key, mapping=agent_flat)
            await pipe.sadd(self._key("agents", "topic", topic), agent_name)
            await pipe.sadd(self._key("topics"), topic)
            await pipe.execute()

    async def get_agent(self, topic: str, agent_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific agent."""
        if not self._redis:
            await self.connect()

        agent_key = self._key("agent", topic, agent_name)
        data = await self._redis.hgetall(agent_key)

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
        """Get all agents for a topic."""
        if not self._redis:
            await self.connect()

        agent_names = await self._redis.smembers(self._key("agents", "topic", topic))

        if not agent_names:
            return []

        agents = []
        for agent_name in agent_names:
            agent = await self.get_agent(topic, agent_name)
            if agent:
                agents.append(agent)

        return agents

    async def list_all_agents(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all agents grouped by topic."""
        if not self._redis:
            await self.connect()

        topics = await self._redis.smembers(self._key("topics"))

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

        agent_key = self._key("agent", topic, agent_name)

        async with self._redis.pipeline(transaction=True) as pipe:
            await pipe.delete(agent_key)
            await pipe.srem(self._key("agents", "topic", topic), agent_name)
            results = await pipe.execute()

        count = await self._redis.scard(self._key("agents", "topic", topic))
        if count == 0:
            await self._redis.srem(self._key("topics"), topic)
            await self._redis.delete(self._key("agents", "topic", topic))

        return results[0] > 0

    async def delete_topic(self, topic: str) -> int:
        """Delete all agents for a topic."""
        if not self._redis:
            await self.connect()

        agent_names = await self._redis.smembers(self._key("agents", "topic", topic))

        if not agent_names:
            return 0

        agent_keys = [self._key("agent", topic, name) for name in agent_names]

        async with self._redis.pipeline(transaction=True) as pipe:
            for key in agent_keys:
                await pipe.delete(key)

            await pipe.delete(self._key("agents", "topic", topic))

            await pipe.srem(self._key("topics"), topic)

            await pipe.execute()

        return len(agent_names)

    async def save_result(
        self, task_id: str, result: Dict[str, Any], ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Save task result with optional TTL.

        """
        if not self._redis:
            await self.connect()

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
        """Get task result (Redis handles TTL automatically)."""
        if not self._redis:
            await self.connect()

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

        Uses Redis Streams for metrics - perfect for time-series data!
        """
        if not self._redis:
            await self.connect()

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
        """Get recent metrics from Redis Stream."""
        if not self._redis:
            await self.connect()

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
        """Save configuration value."""
        if not self._redis:
            await self.connect()

        config_key = self._key("config", key)
        await self._redis.set(config_key, json.dumps(value, default=str))

    async def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        if not self._redis:
            await self.connect()

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

        count = await self._redis.xlen(self._key("metrics", "stream"))
        await self._redis.delete(self._key("metrics", "stream"))

        return count

    async def clear_all(self) -> Dict[str, int]:
        """Clear all OmniDaemon data."""
        agents_count = await self.clear_agents()
        results_count = await self.clear_results()
        metrics_count = await self.clear_metrics()

        if not self._redis:
            await self.connect()

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
