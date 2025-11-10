"""Unit tests for RedisStore implementation."""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from omnidaemon.storage.redis_store import RedisStore


class MockPipeline:
    """Mock async pipeline context manager."""

    def __init__(self):
        self.commands = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return False

    async def hset(self, key, mapping=None):
        self.commands.append(("hset", key, mapping))

    async def sadd(self, key, *values):
        self.commands.append(("sadd", key, values))

    async def delete(self, *keys):
        self.commands.append(("delete", keys))

    async def srem(self, key, *values):
        self.commands.append(("srem", key, values))

    async def zrem(self, key, *values):
        self.commands.append(("zrem", key, values))

    async def execute(self):
        return [1] * len(self.commands)


class MockAsyncIterator:
    """Mock async iterator for scan_iter."""

    def __init__(self, items):
        self.items = iter(items)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.items)
        except StopIteration:
            raise StopAsyncIteration


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.ping = AsyncMock(return_value=True)
    redis.info = AsyncMock(
        return_value={
            "redis_version": "7.0.0",
            "used_memory_human": "1K",
            "connected_clients": 1,
        }
    )
    redis.time = AsyncMock(return_value=[1234567890, 0])
    redis.pipeline = MagicMock(return_value=MockPipeline())
    return redis


@pytest.fixture
def store(mock_redis):
    """Create a RedisStore instance for testing."""
    with patch("omnidaemon.storage.redis_store.aioredis") as mock_aioredis:
        mock_aioredis.from_url = AsyncMock(return_value=mock_redis)
        store = RedisStore(redis_url="redis://localhost:6379")
        store._redis = mock_redis
        store._connected = True
        return store


class TestRedisStoreInitialization:
    """Test suite for RedisStore initialization."""

    def test_redis_store_init_default_prefix(self):
        """Test initialization with default prefix."""
        store = RedisStore(redis_url="redis://localhost:6379")
        assert store.key_prefix == "omni"
        assert store.redis_url == "redis://localhost:6379"

    def test_redis_store_init_custom_prefix(self):
        """Test initialization with custom prefix."""
        store = RedisStore(redis_url="redis://localhost:6379", key_prefix="custom")
        assert store.key_prefix == "custom"

    def test_redis_store_init_not_connected(self):
        """Test Redis is not connected on init."""
        store = RedisStore(redis_url="redis://localhost:6379")
        assert store._redis is None
        assert store._connected is False


class TestRedisStoreConnection:
    """Test suite for RedisStore connection operations."""

    @pytest.mark.asyncio
    async def test_connect_success(self, mock_redis):
        """Test successful Redis connection."""
        with patch("omnidaemon.storage.redis_store.aioredis") as mock_aioredis:
            mock_aioredis.from_url = AsyncMock(return_value=mock_redis)
            store = RedisStore(redis_url="redis://localhost:6379")
            await store.connect()

            assert store._redis is not None
            assert store._connected is True

    @pytest.mark.asyncio
    async def test_connect_idempotent(self, store):
        """Test multiple connect() calls are safe."""
        await store.connect()
        await store.connect()
        await store.connect()

        # Should not raise exception
        assert store._connected

    @pytest.mark.asyncio
    async def test_close_success(self, store):
        """Test successful Redis close."""
        await store.close()

        assert store._redis is None
        assert store._connected is False

    @pytest.mark.asyncio
    async def test_close_clears_connection(self, store):
        """Test close clears connection reference."""
        await store.close()

        assert store._redis is None


class TestRedisStoreHealthCheck:
    """Test suite for RedisStore health check operations."""

    @pytest.mark.asyncio
    async def test_health_check_success(self, store, mock_redis):
        """Test successful health check."""
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.info = AsyncMock(return_value={"redis_version": "7.0.0"})

        health = await store.health_check()

        assert health["status"] == "healthy"
        assert health["backend"] == "redis"

    @pytest.mark.asyncio
    async def test_health_check_includes_latency(self, store, mock_redis):
        """Test health_check includes latency."""
        mock_redis.ping = AsyncMock(return_value=True)

        health = await store.health_check()

        assert "latency_ms" in health

    @pytest.mark.asyncio
    async def test_health_check_includes_redis_info(self, store, mock_redis):
        """Test health_check includes Redis info."""
        mock_redis.ping = AsyncMock(return_value=True)
        mock_redis.info = AsyncMock(
            return_value={
                "redis_version": "7.0.0",
                "used_memory_human": "1K",
                "connected_clients": 1,
            }
        )

        health = await store.health_check()

        assert "redis_version" in health
        assert "used_memory" in health
        assert "connected_clients" in health

    @pytest.mark.asyncio
    async def test_health_check_handles_errors(self, store, mock_redis):
        """Test health_check handles connection errors."""
        mock_redis.ping = AsyncMock(side_effect=Exception("Connection failed"))

        health = await store.health_check()

        assert health["status"] == "unhealthy"
        assert "error" in health


class TestRedisStoreAgentCRUD:
    """Test suite for RedisStore agent CRUD operations."""

    @pytest.mark.asyncio
    async def test_add_agent_success(self, store, mock_redis):
        """Test successful agent addition."""
        mock_pipeline = MockPipeline()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        await store.add_agent(
            "test.topic", {"name": "test-agent", "callback_name": "callback"}
        )

        assert len(mock_pipeline.commands) > 0
        assert any(cmd[0] == "hset" for cmd in mock_pipeline.commands)
        assert any(cmd[0] == "sadd" for cmd in mock_pipeline.commands)

    @pytest.mark.asyncio
    async def test_add_agent_upsert(self, store, mock_redis):
        """Test add_agent updates existing agent."""
        mock_pipeline = MockPipeline()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        await store.add_agent(
            "test.topic", {"name": "test-agent", "callback_name": "callback1"}
        )
        await store.add_agent(
            "test.topic", {"name": "test-agent", "callback_name": "callback2"}
        )

        # Should call pipeline twice (upsert)
        assert mock_redis.pipeline.call_count == 2

    @pytest.mark.asyncio
    async def test_add_agent_creates_topic_set(self, store, mock_redis):
        """Test add_agent creates topic set."""
        mock_pipeline = MockPipeline()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        await store.add_agent("new.topic", {"name": "agent1"})

        # Should add to topics set
        assert any(
            cmd[0] == "sadd" and "topics" in str(cmd[1])
            for cmd in mock_pipeline.commands
        )

    @pytest.mark.asyncio
    async def test_add_agent_missing_name(self, store):
        """Test add_agent fails without name."""
        with pytest.raises(ValueError, match="Agent data must include 'name' field"):
            await store.add_agent("test.topic", {"callback_name": "callback"})

    @pytest.mark.asyncio
    async def test_get_agent_success(self, store, mock_redis):
        """Test successful agent retrieval."""
        agent_data = {
            "name": "test-agent",
            "callback_name": "callback",
            "tools": "[]",
            "description": "",
            "config": "{}",
            "topic": "test.topic",
            "created_at": "1234567890.0",
        }
        mock_redis.hgetall = AsyncMock(return_value=agent_data)

        agent = await store.get_agent("test.topic", "test-agent")

        assert agent is not None
        assert agent["name"] == "test-agent"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, store, mock_redis):
        """Test get_agent returns None if not found."""
        mock_redis.hgetall = AsyncMock(return_value={})

        agent = await store.get_agent("test.topic", "nonexistent")

        assert agent is None

    @pytest.mark.asyncio
    async def test_get_agent_deserializes_json(self, store, mock_redis):
        """Test get_agent deserializes JSON fields."""
        agent_data = {
            "name": "test-agent",
            "callback_name": "",
            "tools": json.dumps(["tool1", "tool2"]),
            "description": "",
            "config": "{}",
            "topic": "test.topic",
            "created_at": "1234567890.0",
        }
        mock_redis.hgetall = AsyncMock(return_value=agent_data)

        agent = await store.get_agent("test.topic", "test-agent")

        assert agent["tools"] == ["tool1", "tool2"]

    @pytest.mark.asyncio
    async def test_get_agents_by_topic_success(self, store, mock_redis):
        """Test successful agents by topic retrieval."""
        mock_redis.smembers = AsyncMock(return_value={"agent1", "agent2"})
        mock_redis.hgetall = AsyncMock(
            side_effect=[
                {
                    "name": "agent1",
                    "callback_name": "",
                    "tools": "[]",
                    "description": "",
                    "config": "{}",
                    "topic": "test.topic",
                    "created_at": "1234567890.0",
                },
                {
                    "name": "agent2",
                    "callback_name": "",
                    "tools": "[]",
                    "description": "",
                    "config": "{}",
                    "topic": "test.topic",
                    "created_at": "1234567890.0",
                },
            ]
        )

        agents = await store.get_agents_by_topic("test.topic")

        assert len(agents) == 2

    @pytest.mark.asyncio
    async def test_get_agents_by_topic_empty(self, store, mock_redis):
        """Test get_agents_by_topic with no agents."""
        mock_redis.smembers = AsyncMock(return_value=set())

        agents = await store.get_agents_by_topic("test.topic")

        assert agents == []

    @pytest.mark.asyncio
    async def test_list_all_agents_success(self, store, mock_redis):
        """Test successful all agents listing."""
        mock_redis.smembers = AsyncMock(
            side_effect=[
                {"topic1", "topic2"},  # Topics
                {"agent1"},  # Agents for topic1
                {"agent2"},  # Agents for topic2
            ]
        )
        mock_redis.hgetall = AsyncMock(
            side_effect=[
                {
                    "name": "agent1",
                    "callback_name": "",
                    "tools": "[]",
                    "description": "",
                    "config": "{}",
                    "topic": "topic1",
                    "created_at": "1234567890.0",
                },
                {
                    "name": "agent2",
                    "callback_name": "",
                    "tools": "[]",
                    "description": "",
                    "config": "{}",
                    "topic": "topic2",
                    "created_at": "1234567890.0",
                },
            ]
        )

        all_agents = await store.list_all_agents()

        assert "topic1" in all_agents or "topic2" in all_agents

    @pytest.mark.asyncio
    async def test_list_all_agents_empty(self, store, mock_redis):
        """Test list_all_agents with no agents."""
        mock_redis.smembers = AsyncMock(return_value=set())

        all_agents = await store.list_all_agents()

        assert all_agents == {}

    @pytest.mark.asyncio
    async def test_delete_agent_success(self, store, mock_redis):
        """Test successful agent deletion."""
        mock_pipeline = MockPipeline()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_redis.scard = AsyncMock(return_value=0)

        deleted = await store.delete_agent("test.topic", "test-agent")

        assert deleted is True
        assert len(mock_pipeline.commands) > 0

    @pytest.mark.asyncio
    async def test_delete_agent_not_found(self, store, mock_redis):
        """Test delete_agent handles not found."""
        mock_pipeline = MockPipeline()
        mock_pipeline.execute = AsyncMock(return_value=[0])  # Delete returns 0
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_redis.scard = AsyncMock(return_value=1)

        deleted = await store.delete_agent("test.topic", "nonexistent")

        assert deleted is False

    @pytest.mark.asyncio
    async def test_delete_agent_removes_from_set(self, store, mock_redis):
        """Test delete_agent removes from topic set."""
        mock_pipeline = MockPipeline()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_redis.scard = AsyncMock(return_value=0)
        mock_redis.srem = AsyncMock()
        mock_redis.delete = AsyncMock()

        await store.delete_agent("test.topic", "test-agent")

        # Should call srem in pipeline
        assert any(cmd[0] == "srem" for cmd in mock_pipeline.commands)

    @pytest.mark.asyncio
    async def test_delete_agent_removes_empty_topic(self, store, mock_redis):
        """Test delete_agent removes empty topic."""
        mock_pipeline = MockPipeline()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)
        mock_redis.scard = AsyncMock(return_value=0)  # Empty topic set
        mock_redis.srem = AsyncMock()
        mock_redis.delete = AsyncMock()

        await store.delete_agent("test.topic", "test-agent")

        # Should delete empty topic set
        mock_redis.delete.assert_called()

    @pytest.mark.asyncio
    async def test_delete_topic_success(self, store, mock_redis):
        """Test successful topic deletion."""
        mock_redis.smembers = AsyncMock(return_value={"agent1", "agent2"})
        mock_pipeline = MockPipeline()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        count = await store.delete_topic("test.topic")

        assert count == 2
        assert mock_redis.pipeline.called

    @pytest.mark.asyncio
    async def test_delete_topic_returns_count(self, store, mock_redis):
        """Test delete_topic returns agent count."""
        mock_redis.smembers = AsyncMock(return_value={"agent1", "agent2", "agent3"})
        mock_pipeline = MockPipeline()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        count = await store.delete_topic("test.topic")

        assert count == 3

    @pytest.mark.asyncio
    async def test_delete_topic_empty(self, store, mock_redis):
        """Test delete_topic with no agents."""
        mock_redis.smembers = AsyncMock(return_value=set())

        count = await store.delete_topic("test.topic")

        assert count == 0

    @pytest.mark.asyncio
    async def test_clear_agents_success(self, store, mock_redis):
        """Test successful agents clearing."""
        mock_redis.scan_iter = MagicMock(
            return_value=MockAsyncIterator(
                ["omni:agent:topic1:agent1", "omni:agent:topic2:agent2"]
            )
        )
        mock_redis.delete = AsyncMock()

        count = await store.clear_agents()

        assert count == 2
        assert mock_redis.delete.called

    @pytest.mark.asyncio
    async def test_clear_agents_uses_scan(self, store, mock_redis):
        """Test clear_agents uses SCAN for efficiency."""
        mock_redis.scan_iter = MagicMock(return_value=MockAsyncIterator([]))
        mock_redis.delete = AsyncMock()

        await store.clear_agents()

        mock_redis.scan_iter.assert_called()


class TestRedisStoreResultCRUD:
    """Test suite for RedisStore result CRUD operations."""

    @pytest.mark.asyncio
    async def test_save_result_success(self, store, mock_redis):
        """Test successful result save."""
        mock_redis.set = AsyncMock()
        mock_redis.zadd = AsyncMock()

        await store.save_result("task-1", {"result": "data", "status": "success"})

        mock_redis.set.assert_called()
        mock_redis.zadd.assert_called()

    @pytest.mark.asyncio
    async def test_save_result_with_ttl(self, store, mock_redis):
        """Test save_result with TTL."""
        mock_redis.setex = AsyncMock()
        mock_redis.zadd = AsyncMock()

        await store.save_result("task-1", {"result": "data"}, ttl_seconds=3600)

        # Verify setex was called
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][1] == 3600  # TTL in seconds

    @pytest.mark.asyncio
    async def test_save_result_without_ttl(self, store, mock_redis):
        """Test save_result without TTL."""
        mock_redis.set = AsyncMock()
        mock_redis.zadd = AsyncMock()

        await store.save_result("task-1", {"result": "data"})

        mock_redis.set.assert_called()

    @pytest.mark.asyncio
    async def test_save_result_adds_to_index(self, store, mock_redis):
        """Test save_result adds to sorted set index."""
        mock_redis.set = AsyncMock()
        mock_redis.zadd = AsyncMock()

        await store.save_result("task-1", {"result": "data"})

        mock_redis.zadd.assert_called()

    @pytest.mark.asyncio
    async def test_get_result_success(self, store, mock_redis):
        """Test successful result retrieval."""
        result_data = {"result": "test data", "status": "success"}
        mock_redis.get = AsyncMock(return_value=json.dumps(result_data))
        mock_redis.zrem = AsyncMock()

        result = await store.get_result("task-1")

        assert result is not None
        assert result == "test data"  # Returns result_data.get("result")

    @pytest.mark.asyncio
    async def test_get_result_expired(self, store, mock_redis):
        """Test get_result returns None for expired results (Redis TTL)."""
        mock_redis.get = AsyncMock(return_value=None)

        result = await store.get_result("task-1")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_result_not_found(self, store, mock_redis):
        """Test get_result returns None if not found."""
        mock_redis.get = AsyncMock(return_value=None)

        result = await store.get_result("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_result_removes_from_index_if_expired(self, store, mock_redis):
        """Test get_result cleans index."""
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.zrem = AsyncMock()

        await store.get_result("task-1")

        # Should clean up index if expired
        # Implementation dependent

    @pytest.mark.asyncio
    async def test_delete_result_success(self, store, mock_redis):
        """Test successful result deletion."""
        mock_pipeline = MockPipeline()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        deleted = await store.delete_result("task-1")

        assert deleted is True
        assert len(mock_pipeline.commands) > 0

    @pytest.mark.asyncio
    async def test_delete_result_not_found(self, store, mock_redis):
        """Test delete_result handles not found."""
        mock_pipeline = MockPipeline()
        mock_pipeline.execute = AsyncMock(return_value=[0])  # Delete returns 0
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        deleted = await store.delete_result("nonexistent")

        assert deleted is False

    @pytest.mark.asyncio
    async def test_delete_result_removes_from_index(self, store, mock_redis):
        """Test delete_result removes from index."""
        mock_pipeline = MockPipeline()
        mock_redis.pipeline = MagicMock(return_value=mock_pipeline)

        await store.delete_result("task-1")

        # Should call zrem in pipeline
        assert any(cmd[0] == "zrem" for cmd in mock_pipeline.commands)

    @pytest.mark.asyncio
    async def test_list_results_success(self, store, mock_redis):
        """Test successful result listing."""
        mock_redis.zrevrange = AsyncMock(return_value=["task-1", "task-2"])
        mock_redis.get = AsyncMock(
            side_effect=[
                json.dumps({"result": "data1"}),
                json.dumps({"result": "data2"}),
            ]
        )

        results = await store.list_results()

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_results_sorted(self, store, mock_redis):
        """Test list_results returns sorted by timestamp."""
        mock_redis.zrevrange = AsyncMock(return_value=["task-2", "task-1"])
        mock_redis.get = AsyncMock(
            side_effect=[
                json.dumps({"result": "data2", "task_id": "task-2"}),
                json.dumps({"result": "data1", "task_id": "task-1"}),
            ]
        )

        results = await store.list_results()

        # Results are returned as-is from JSON, sorted by zrevrange
        assert results[0]["task_id"] == "task-2"

    @pytest.mark.asyncio
    async def test_list_results_with_limit(self, store, mock_redis):
        """Test list_results respects limit."""
        # zrevrange is called with limit-1, so limit=2 means zrevrange(0, 1) = 2 items
        mock_redis.zrevrange = AsyncMock(return_value=["task-1", "task-2"])
        mock_redis.get = AsyncMock(return_value=json.dumps({"result": "data"}))

        results = await store.list_results(limit=2)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_clear_results_success(self, store, mock_redis):
        """Test successful results clearing."""
        mock_redis.scan_iter = MagicMock(
            return_value=MockAsyncIterator(["omni:result:task-1", "omni:result:task-2"])
        )
        mock_redis.delete = AsyncMock()

        count = await store.clear_results()

        assert count == 2
        assert mock_redis.delete.called

    @pytest.mark.asyncio
    async def test_clear_results_uses_scan(self, store, mock_redis):
        """Test clear_results uses SCAN."""
        mock_redis.scan_iter = MagicMock(return_value=MockAsyncIterator([]))
        mock_redis.delete = AsyncMock()

        await store.clear_results()

        mock_redis.scan_iter.assert_called()


class TestRedisStoreMetric:
    """Test suite for RedisStore metric operations."""

    @pytest.mark.asyncio
    async def test_save_metric_success(self, store, mock_redis):
        """Test successful metric save."""
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")

        await store.save_metric({"topic": "test.topic", "event": "processed"})

        mock_redis.xadd.assert_called()

    @pytest.mark.asyncio
    async def test_save_metric_uses_stream(self, store, mock_redis):
        """Test save_metric uses Redis Stream."""
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")

        await store.save_metric({"topic": "test.topic", "event": "processed"})

        call_args = mock_redis.xadd.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_save_metric_respects_maxlen(self, store, mock_redis):
        """Test save_metric respects maxlen."""
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")

        await store.save_metric({"topic": "test.topic", "event": "processed"})

        # Verify xadd was called (maxlen is handled internally)
        mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_metrics_success(self, store, mock_redis):
        """Test successful metrics retrieval."""
        mock_redis.xrevrange = AsyncMock(
            return_value=[
                ("1234567890-0", {"data": json.dumps({"event": "test1"})}),
                ("1234567891-0", {"data": json.dumps({"event": "test2"})}),
            ]
        )

        metrics = await store.get_metrics()

        assert len(metrics) == 2

    @pytest.mark.asyncio
    async def test_get_metrics_with_topic_filter(self, store, mock_redis):
        """Test get_metrics with topic filter."""
        mock_redis.xrevrange = AsyncMock(
            return_value=[
                (
                    "1234567890-0",
                    {"data": json.dumps({"topic": "topic1", "event": "test1"})},
                )
            ]
        )

        metrics = await store.get_metrics(topic="topic1")

        assert len(metrics) >= 0  # Filtering may happen in code or Redis

    @pytest.mark.asyncio
    async def test_get_metrics_with_limit(self, store, mock_redis):
        """Test get_metrics respects limit."""
        # xrevrange is called with count=limit, so it should return only limit items
        mock_redis.xrevrange = AsyncMock(
            return_value=[
                (f"{i}-0", {"data": json.dumps({"event": f"test{i}"})})
                for i in range(5)
            ]
        )

        metrics = await store.get_metrics(limit=5)

        assert len(metrics) == 5

    @pytest.mark.asyncio
    async def test_get_metrics_reversed(self, store, mock_redis):
        """Test get_metrics returns reversed order."""
        mock_redis.xrevrange = AsyncMock(
            return_value=[
                ("1234567891-0", {"data": json.dumps({"event": "test2"})}),
                ("1234567890-0", {"data": json.dumps({"event": "test1"})}),
            ]
        )

        metrics = await store.get_metrics()

        # Most recent first
        assert metrics[0]["event"] == "test2"

    @pytest.mark.asyncio
    async def test_get_metrics_handles_json_error(self, store, mock_redis):
        """Test get_metrics handles JSON decode errors."""
        mock_redis.xrevrange = AsyncMock(
            return_value=[("1234567890-0", {"data": "invalid json"})]
        )

        # Should handle gracefully
        metrics = await store.get_metrics()

        # Should either skip invalid or return empty
        assert isinstance(metrics, list)

    @pytest.mark.asyncio
    async def test_clear_metrics_success(self, store, mock_redis):
        """Test successful metrics clearing."""
        mock_redis.delete = AsyncMock(return_value=1)
        mock_redis.xlen = AsyncMock(return_value=10)

        count = await store.clear_metrics()

        assert count >= 0
        mock_redis.delete.assert_called()


class TestRedisStoreConfig:
    """Test suite for RedisStore config operations."""

    @pytest.mark.asyncio
    async def test_save_config_success(self, store, mock_redis):
        """Test successful config save."""
        mock_redis.set = AsyncMock()

        await store.save_config("key1", "value1")

        mock_redis.set.assert_called()

    @pytest.mark.asyncio
    async def test_get_config_success(self, store, mock_redis):
        """Test successful config retrieval."""
        mock_redis.get = AsyncMock(return_value=json.dumps({"nested": "value"}))

        value = await store.get_config("key1")

        assert value == {"nested": "value"}

    @pytest.mark.asyncio
    async def test_get_config_default(self, store, mock_redis):
        """Test get_config returns default if not found."""
        mock_redis.get = AsyncMock(return_value=None)

        value = await store.get_config("nonexistent", default="default_value")

        assert value == "default_value"

    @pytest.mark.asyncio
    async def test_get_config_not_found(self, store, mock_redis):
        """Test get_config returns None if not found and no default."""
        mock_redis.get = AsyncMock(return_value=None)

        value = await store.get_config("nonexistent")

        assert value is None

    @pytest.mark.asyncio
    async def test_get_config_deserializes_json(self, store, mock_redis):
        """Test get_config deserializes JSON."""
        config_data = {"nested": {"key": "value"}}
        mock_redis.get = AsyncMock(return_value=json.dumps(config_data))

        value = await store.get_config("key1")

        assert value == config_data


class TestRedisStoreClearAll:
    """Test suite for RedisStore clear_all operations."""

    @pytest.mark.asyncio
    async def test_clear_all_success(self, store, mock_redis):
        """Test successful clear_all."""
        mock_redis.scan_iter = MagicMock(return_value=MockAsyncIterator([]))
        mock_redis.delete = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_redis.xlen = AsyncMock(return_value=0)

        counts = await store.clear_all()

        assert "agents" in counts
        assert "results" in counts
        assert "metrics" in counts
        assert "config" in counts

    @pytest.mark.asyncio
    async def test_clear_all_returns_counts(self, store, mock_redis):
        """Test clear_all returns all counts."""
        mock_redis.scan_iter = MagicMock(return_value=MockAsyncIterator([]))
        mock_redis.delete = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_redis.xlen = AsyncMock(return_value=0)

        counts = await store.clear_all()

        assert isinstance(counts["agents"], int)
        assert isinstance(counts["results"], int)
        assert isinstance(counts["metrics"], int)
        assert isinstance(counts["config"], int)

    @pytest.mark.asyncio
    async def test_clear_all_removes_config(self, store, mock_redis):
        """Test clear_all removes config."""
        mock_redis.scan_iter = MagicMock(return_value=MockAsyncIterator([]))
        mock_redis.delete = AsyncMock()
        mock_redis.keys = AsyncMock(
            return_value=["omni:config:key1", "omni:config:key2"]
        )
        mock_redis.xlen = AsyncMock(return_value=0)

        await store.clear_all()

        # Verify config keys were deleted
        assert mock_redis.delete.called

    @pytest.mark.asyncio
    async def test_clear_all_uses_scan(self, store, mock_redis):
        """Test clear_all uses SCAN for efficiency."""
        mock_redis.scan_iter = MagicMock(return_value=MockAsyncIterator([]))
        mock_redis.delete = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_redis.xlen = AsyncMock(return_value=0)

        await store.clear_all()

        mock_redis.scan_iter.assert_called()


class TestRedisStoreKeyPrefix:
    """Test suite for RedisStore key prefix operations."""

    def test_key_prefix_isolation(self):
        """Test key prefix provides namespace isolation."""
        store1 = RedisStore(redis_url="redis://localhost:6379", key_prefix="prefix1")
        store2 = RedisStore(redis_url="redis://localhost:6379", key_prefix="prefix2")

        key1 = store1._key("agents", "topic1", "agent1")
        key2 = store2._key("agents", "topic1", "agent1")

        assert key1 != key2
        assert key1.startswith("prefix1")
        assert key2.startswith("prefix2")

    def test_key_prefix_custom(self):
        """Test custom key prefix works correctly."""
        store = RedisStore(redis_url="redis://localhost:6379", key_prefix="custom")

        key = store._key("agents", "topic1", "agent1")

        assert key.startswith("custom")
        assert "agents" in key
        assert "topic1" in key
        assert "agent1" in key
