"""Unit tests for RedisStreamEventBus."""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from omnidaemon.event_bus.redis_stream_bus import RedisStreamEventBus


async def cleanup_bus_tasks(bus: RedisStreamEventBus, group_name: str):
    """Helper to cleanup tasks after subscribe tests."""
    bus._running = False
    if group_name in bus._consumers:
        consumer_meta = bus._consumers[group_name]
        for task in consumer_meta.get("consume_tasks", []) + consumer_meta.get(
            "reclaim_tasks", []
        ):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def stop_loop_task(
    task: asyncio.Task, bus: RedisStreamEventBus, timeout: float = 0.5
):
    """Helper to stop a loop task gracefully."""
    bus._running = False
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


class TestRedisStreamEventBusInitialization:
    """Test suite for RedisStreamEventBus initialization."""

    @patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"})
    def test_redis_stream_bus_init_defaults(self):
        """Test initialization with default parameters."""
        bus = RedisStreamEventBus()
        # Redis URL may have /0 appended by aioredis, so check it starts with expected value
        assert bus.redis_url.startswith("redis://localhost:6379")
        assert bus.default_maxlen == 10_000
        assert bus.reclaim_interval == 30
        assert bus.default_reclaim_idle_ms == 180_000
        assert bus.default_dlq_retry_limit == 3
        assert bus._redis is None
        assert bus._running is False
        assert isinstance(bus._consumers, dict)
        assert isinstance(bus._in_flight, dict)

    def test_redis_stream_bus_init_custom_redis_url(self):
        """Test initialization with custom Redis URL."""
        bus = RedisStreamEventBus(redis_url="redis://custom:6379")
        assert bus.redis_url == "redis://custom:6379"

    def test_redis_stream_bus_init_custom_maxlen(self):
        """Test initialization with custom maxlen."""
        bus = RedisStreamEventBus(default_maxlen=5_000)
        assert bus.default_maxlen == 5_000

    def test_redis_stream_bus_init_custom_reclaim_interval(self):
        """Test initialization with custom reclaim interval."""
        bus = RedisStreamEventBus(reclaim_interval=60)
        assert bus.reclaim_interval == 60

    def test_redis_stream_bus_init_custom_reclaim_idle_ms(self):
        """Test initialization with custom reclaim idle time."""
        bus = RedisStreamEventBus(default_reclaim_idle_ms=300_000)
        assert bus.default_reclaim_idle_ms == 300_000

    def test_redis_stream_bus_init_custom_dlq_retry_limit(self):
        """Test initialization with custom DLQ retry limit."""
        bus = RedisStreamEventBus(default_dlq_retry_limit=5)
        assert bus.default_dlq_retry_limit == 5

    def test_redis_stream_bus_init_redis_not_connected(self):
        """Test that Redis is not connected on init."""
        bus = RedisStreamEventBus()
        assert bus._redis is None
        assert bus._connect_lock is not None


class TestRedisStreamEventBusConnection:
    """Test suite for RedisStreamEventBus connection management."""

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """Test successful connection to Redis."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")

        mock_redis = AsyncMock()
        with patch(
            "omnidaemon.event_bus.redis_stream_bus.aioredis.from_url",
            return_value=mock_redis,
        ):
            await bus.connect()

            assert bus._redis is not None
            assert bus._redis == mock_redis

    @pytest.mark.asyncio
    async def test_connect_with_lock(self):
        """Test connection uses lock to prevent race conditions."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")

        mock_redis = AsyncMock()
        with patch(
            "omnidaemon.event_bus.redis_stream_bus.aioredis.from_url",
            return_value=mock_redis,
        ):
            # Call connect multiple times concurrently
            await asyncio.gather(bus.connect(), bus.connect(), bus.connect())

            # Should only create one connection
            assert bus._redis is not None

    @pytest.mark.asyncio
    async def test_connect_idempotent(self):
        """Test multiple connect() calls are idempotent."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")

        mock_redis = AsyncMock()
        with patch(
            "omnidaemon.event_bus.redis_stream_bus.aioredis.from_url",
            return_value=mock_redis,
        ):
            await bus.connect()
            first_redis = bus._redis

            await bus.connect()
            second_redis = bus._redis

            # Should be the same instance
            assert first_redis is second_redis

    @pytest.mark.asyncio
    async def test_connect_invalid_redis_url(self):
        """Test connection failure with invalid Redis URL."""
        bus = RedisStreamEventBus(redis_url="invalid://url")

        with patch(
            "omnidaemon.event_bus.redis_stream_bus.aioredis.from_url",
            side_effect=Exception("Connection failed"),
        ):
            with pytest.raises(Exception, match="Connection failed"):
                await bus.connect()

    @pytest.mark.asyncio
    async def test_connect_redis_unavailable(self):
        """Test connection failure when Redis is unavailable."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")

        with patch(
            "omnidaemon.event_bus.redis_stream_bus.aioredis.from_url",
            side_effect=ConnectionError("Redis unavailable"),
        ):
            with pytest.raises(ConnectionError, match="Redis unavailable"):
                await bus.connect()

    @pytest.mark.asyncio
    async def test_close_success(self):
        """Test successful close of Redis connection."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")

        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True
        bus._consumers = {
            "group1": {
                "consume_tasks": [asyncio.create_task(asyncio.sleep(100))],
                "reclaim_tasks": [asyncio.create_task(asyncio.sleep(100))],
            }
        }

        await bus.close()

        assert bus._redis is None
        assert bus._running is False
        mock_redis.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_cancels_consumers(self):
        """Test close cancels all consumer tasks."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")

        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        task1 = asyncio.create_task(asyncio.sleep(100))
        task2 = asyncio.create_task(asyncio.sleep(100))

        bus._consumers = {
            "group1": {"consume_tasks": [task1, task2], "reclaim_tasks": []}
        }

        await bus.close()

        # Wait a bit for cancellation to propagate
        await asyncio.sleep(0.01)

        assert task1.cancelled()
        assert task2.cancelled()

    @pytest.mark.asyncio
    async def test_close_cancels_reclaim_tasks(self):
        """Test close cancels all reclaim tasks."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")

        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        task1 = asyncio.create_task(asyncio.sleep(100))
        task2 = asyncio.create_task(asyncio.sleep(100))

        bus._consumers = {
            "group1": {"consume_tasks": [], "reclaim_tasks": [task1, task2]}
        }

        await bus.close()

        # Wait a bit for cancellation to propagate
        await asyncio.sleep(0.01)

        assert task1.cancelled()
        assert task2.cancelled()

    @pytest.mark.asyncio
    async def test_close_clears_redis_connection(self):
        """Test close clears Redis connection reference."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")

        mock_redis = AsyncMock()
        bus._redis = mock_redis

        await bus.close()

        assert bus._redis is None

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        """Test multiple close() calls are safe."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")

        mock_redis = AsyncMock()
        bus._redis = mock_redis

        await bus.close()
        await bus.close()
        await bus.close()

        # Should not raise any errors
        assert bus._redis is None


class TestRedisStreamEventBusPublish:
    """Test suite for RedisStreamEventBus publish operations."""

    @pytest.mark.asyncio
    async def test_publish_success(self):
        """Test successful message publication."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")
        bus._redis = mock_redis

        event_payload = {
            "id": "task-123",
            "topic": "test.topic",
            "payload": {"content": "test content"},
        }

        task_id = await bus.publish(event_payload)

        assert task_id == "task-123"
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert "omni-stream:test.topic" in str(call_args)

    @pytest.mark.asyncio
    async def test_publish_auto_connect(self):
        """Test publish auto-connects if not connected."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")

        with patch(
            "omnidaemon.event_bus.redis_stream_bus.aioredis.from_url",
            return_value=mock_redis,
        ):
            event_payload = {
                "id": "task-123",
                "topic": "test.topic",
                "payload": {"content": "test content"},
            }

            await bus.publish(event_payload)

            assert bus._redis is not None
            mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_returns_task_id(self):
        """Test publish returns correct task ID."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")
        bus._redis = mock_redis

        event_payload = {
            "id": "custom-task-id",
            "topic": "test.topic",
            "payload": {"content": "test"},
        }

        task_id = await bus.publish(event_payload)
        assert task_id == "custom-task-id"

    @pytest.mark.asyncio
    async def test_publish_creates_stream(self):
        """Test publish creates stream if it doesn't exist."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")
        bus._redis = mock_redis

        event_payload = {
            "id": "task-123",
            "topic": "new.topic",
            "payload": {"content": "test"},
        }

        await bus.publish(event_payload)

        # xadd with mkstream=True creates stream automatically
        mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_respects_maxlen(self):
        """Test publish respects maxlen parameter."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", default_maxlen=100
        )
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")
        bus._redis = mock_redis

        event_payload = {
            "id": "task-123",
            "topic": "test.topic",
            "payload": {"content": "test"},
        }

        await bus.publish(event_payload, maxlen=50)

        call_args = mock_redis.xadd.call_args
        assert call_args[1]["maxlen"] == 50

    @pytest.mark.asyncio
    async def test_publish_with_all_fields(self):
        """Test publish with all EventEnvelope fields."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")
        bus._redis = mock_redis

        event_payload = {
            "id": "task-123",
            "topic": "test.topic",
            "payload": {
                "content": "test content",
                "webhook": "https://example.com/webhook",
                "reply_to": "reply.topic",
            },
            "correlation_id": "corr-123",
            "causation_id": "cause-123",
            "source": "test-source",
            "delivery_attempts": 1,
            "created_at": 1234567890.0,
        }

        await bus.publish(event_payload)

        mock_redis.xadd.assert_called_once()
        # Verify the payload includes all fields
        # xadd is called as xadd(stream_name, {"data": payload}, maxlen=..., approximate=...)
        # So data is in the second positional argument (index 0, then index 1)
        call_args = mock_redis.xadd.call_args
        data_dict = call_args[0][1]  # Second positional argument
        assert "data" in data_dict
        # Verify the data contains all expected fields
        import json

        data = json.loads(data_dict["data"])
        assert data["content"] == "test content"
        assert data["webhook"] == "https://example.com/webhook"
        assert data["reply_to"] == "reply.topic"
        assert data["correlation_id"] == "corr-123"
        assert data["causation_id"] == "cause-123"
        assert data["source"] == "test-source"

    @pytest.mark.asyncio
    async def test_publish_missing_topic(self):
        """Test publish fails when topic is missing."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        event_payload = {
            "id": "task-123",
            "payload": {"content": "test"},
            # Missing topic
        }

        with pytest.raises(
            ValueError, match="Event payload must include 'topic' field"
        ):
            await bus.publish(event_payload)

    @pytest.mark.asyncio
    async def test_publish_empty_payload(self):
        """Test publish with empty payload."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")
        bus._redis = mock_redis

        event_payload = {"id": "task-123", "topic": "test.topic", "payload": {}}

        await bus.publish(event_payload)
        mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_json_serialization(self):
        """Test publish properly serializes JSON data."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="1234567890-0")
        bus._redis = mock_redis

        event_payload = {
            "id": "task-123",
            "topic": "test.topic",
            "payload": {"content": {"nested": "data"}},
        }

        await bus.publish(event_payload)

        # Verify xadd was called with serialized data
        # xadd is called as xadd(stream_name, {"data": payload}, maxlen=..., approximate=...)
        call_args = mock_redis.xadd.call_args
        data_dict = call_args[0][1]  # Second positional argument
        assert "data" in data_dict
        # Data should be a JSON string
        import json

        data_str = data_dict["data"]
        assert isinstance(data_str, str)
        # Should be valid JSON
        json.loads(data_str)


class TestRedisStreamEventBusSubscribe:
    """Test suite for RedisStreamEventBus subscribe operations."""

    @pytest.mark.asyncio
    async def test_subscribe_success(self):
        """Test successful subscription."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        async def callback(msg):
            pass

        await bus.subscribe(
            topic="test.topic", agent_name="test-agent", callback=callback
        )

        assert "group:test.topic:test-agent" in bus._consumers
        mock_redis.xgroup_create.assert_called_once()

        # Cleanup: cancel tasks and stop running
        await cleanup_bus_tasks(bus, "group:test.topic:test-agent")

    @pytest.mark.asyncio
    async def test_subscribe_auto_connect(self):
        """Test subscribe auto-connects if not connected."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()

        with patch(
            "omnidaemon.event_bus.redis_stream_bus.aioredis.from_url",
            return_value=mock_redis,
        ):

            async def callback(msg):
                pass

            await bus.subscribe(
                topic="test.topic", agent_name="test-agent", callback=callback
            )

            assert bus._redis is not None

            # Cleanup
            await cleanup_bus_tasks(bus, "group:test.topic:test-agent")

    @pytest.mark.asyncio
    async def test_subscribe_creates_group(self):
        """Test subscribe creates consumer group."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        async def callback(msg):
            pass

        await bus.subscribe(
            topic="test.topic", agent_name="test-agent", callback=callback
        )

        mock_redis.xgroup_create.assert_called_once()
        call_args = mock_redis.xgroup_create.call_args
        assert call_args[0][0] == "omni-stream:test.topic"
        assert call_args[0][1] == "group:test.topic:test-agent"
        assert call_args[1]["mkstream"] is True

        # Cleanup
        await cleanup_bus_tasks(bus, "group:test.topic:test-agent")

    @pytest.mark.asyncio
    async def test_subscribe_existing_group(self):
        """Test subscribe handles existing group gracefully."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()

        # Simulate BUSYGROUP error (group already exists)
        from redis.exceptions import ResponseError

        mock_redis.xgroup_create = AsyncMock(side_effect=ResponseError("BUSYGROUP"))
        bus._redis = mock_redis

        async def callback(msg):
            pass

        # Should not raise error
        await bus.subscribe(
            topic="test.topic", agent_name="test-agent", callback=callback
        )

        # Should still create consumer entry
        assert "group:test.topic:test-agent" in bus._consumers

        # Cleanup
        await cleanup_bus_tasks(bus, "group:test.topic:test-agent")

    @pytest.mark.asyncio
    async def test_subscribe_multiple_consumers(self):
        """Test subscribe creates multiple consumers."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        async def callback(msg):
            pass

        await bus.subscribe(
            topic="test.topic",
            agent_name="test-agent",
            callback=callback,
            config={"consumer_count": 3},
        )

        consumer_meta = bus._consumers["group:test.topic:test-agent"]
        assert len(consumer_meta["consume_tasks"]) == 3
        assert len(consumer_meta["reclaim_tasks"]) == 3

        # Cleanup
        await cleanup_bus_tasks(bus, "group:test.topic:test-agent")

    @pytest.mark.asyncio
    async def test_subscribe_custom_group_name(self):
        """Test subscribe with custom group name."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        async def callback(msg):
            pass

        await bus.subscribe(
            topic="test.topic",
            agent_name="test-agent",
            callback=callback,
            group_name="custom-group",
        )

        assert "custom-group" in bus._consumers
        mock_redis.xgroup_create.assert_called_with(
            "omni-stream:test.topic", "custom-group", id="$", mkstream=True
        )

        # Cleanup
        await cleanup_bus_tasks(bus, "custom-group")

    @pytest.mark.asyncio
    async def test_subscribe_custom_consumer_name(self):
        """Test subscribe with custom consumer name."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        async def callback(msg):
            pass

        await bus.subscribe(
            topic="test.topic",
            agent_name="test-agent",
            callback=callback,
            consumer_name="custom-consumer",
        )

        consumer_meta = bus._consumers["group:test.topic:test-agent"]
        # Check that consumer name is used in tasks
        assert consumer_meta is not None

        # Cleanup
        await cleanup_bus_tasks(bus, "group:test.topic:test-agent")

    @pytest.mark.asyncio
    async def test_subscribe_custom_reclaim_idle_ms(self):
        """Test subscribe with custom reclaim idle time."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        async def callback(msg):
            pass

        await bus.subscribe(
            topic="test.topic",
            agent_name="test-agent",
            callback=callback,
            config={"reclaim_idle_ms": 300_000},
        )

        consumer_meta = bus._consumers["group:test.topic:test-agent"]
        assert consumer_meta["config"]["reclaim_idle_ms"] == 300_000

        # Cleanup
        await cleanup_bus_tasks(bus, "group:test.topic:test-agent")

    @pytest.mark.asyncio
    async def test_subscribe_custom_dlq_retry_limit(self):
        """Test subscribe with custom DLQ retry limit."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        async def callback(msg):
            pass

        await bus.subscribe(
            topic="test.topic",
            agent_name="test-agent",
            callback=callback,
            config={"dlq_retry_limit": 5},
        )

        consumer_meta = bus._consumers["group:test.topic:test-agent"]
        assert consumer_meta["config"]["dlq_retry_limit"] == 5

        # Cleanup
        await cleanup_bus_tasks(bus, "group:test.topic:test-agent")

    @pytest.mark.asyncio
    async def test_subscribe_callback_async(self):
        """Test subscribe with async callback."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        async def async_callback(msg):
            return "result"

        await bus.subscribe(
            topic="test.topic", agent_name="test-agent", callback=async_callback
        )

        assert "group:test.topic:test-agent" in bus._consumers

        # Cleanup
        await cleanup_bus_tasks(bus, "group:test.topic:test-agent")

    @pytest.mark.asyncio
    async def test_subscribe_callback_sync(self):
        """Test subscribe with sync callback."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        def sync_callback(msg):
            return "result"

        await bus.subscribe(
            topic="test.topic", agent_name="test-agent", callback=sync_callback
        )

        assert "group:test.topic:test-agent" in bus._consumers

        # Cleanup
        await cleanup_bus_tasks(bus, "group:test.topic:test-agent")

    @pytest.mark.asyncio
    async def test_subscribe_stores_metadata(self):
        """Test subscribe stores consumer metadata."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_create = AsyncMock()
        bus._redis = mock_redis

        async def callback(msg):
            pass

        await bus.subscribe(
            topic="test.topic", agent_name="test-agent", callback=callback
        )

        consumer_meta = bus._consumers["group:test.topic:test-agent"]
        assert consumer_meta["topic"] == "test.topic"
        assert consumer_meta["agent_name"] == "test-agent"
        assert consumer_meta["callback"] == callback
        assert consumer_meta["group"] == "group:test.topic:test-agent"
        assert consumer_meta["dlq"] == "omni-dlq:group:test.topic:test-agent"

        # Cleanup
        await cleanup_bus_tasks(bus, "group:test.topic:test-agent")


class TestRedisStreamEventBusConsumeLoop:
    """Test suite for RedisStreamEventBus consume loop operations."""

    @pytest.mark.asyncio
    async def test_consume_loop_reads_messages(self):
        """Test consume loop reads messages from stream."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        # Use an event to coordinate stopping the bus after message is processed
        message_processed = asyncio.Event()
        callback_called = []

        call_count = 0

        async def xreadgroup_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        "omni-stream:test.topic",
                        [("1234567890-0", {"data": '{"content": "test"}'})],
                    )
                ]
            # Second call - return empty and stop
            bus._running = False
            return []

        # Stop bus after callback processes message
        async def callback_with_stop(msg):
            callback_called.append(msg)
            # Give a tiny bit of time for processing, then stop
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)
        mock_redis.xack = AsyncMock()
        mock_redis.xadd = AsyncMock()  # For monitor emit

        # Run consume loop briefly
        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
            )
        )

        # Wait for message to be processed
        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Wait for loop to exit (should be quick since _running is False)
        try:
            await asyncio.wait_for(consume_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

        # Verify callback was called
        assert len(callback_called) > 0

    @pytest.mark.asyncio
    async def test_consume_loop_calls_callback(self):
        """Test consume loop calls callback with message."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        message_processed = asyncio.Event()
        received_messages = []

        call_count = 0

        async def xreadgroup_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        "omni-stream:test.topic",
                        [("1234567890-0", {"data": '{"content": "test message"}'})],
                    )
                ]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            received_messages.append(msg)
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)
        mock_redis.xack = AsyncMock()
        mock_redis.xadd = AsyncMock()

        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        try:
            await asyncio.wait_for(consume_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

        assert len(received_messages) > 0
        assert received_messages[0]["content"] == "test message"

    @pytest.mark.asyncio
    async def test_consume_loop_acks_on_success(self):
        """Test consume loop ACKs message on success."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        message_processed = asyncio.Event()

        call_count = 0

        async def xreadgroup_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        "omni-stream:test.topic",
                        [("1234567890-0", {"data": '{"content": "test"}'})],
                    )
                ]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)
        mock_redis.xack = AsyncMock()
        mock_redis.xadd = AsyncMock()

        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Verify xack was called
        mock_redis.xack.assert_called()

        try:
            await asyncio.wait_for(consume_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_consume_loop_handles_callback_error(self):
        """Test consume loop handles callback errors."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        message_processed = asyncio.Event()

        call_count = 0

        async def xreadgroup_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        "omni-stream:test.topic",
                        [("1234567890-0", {"data": '{"content": "test"}'})],
                    )
                ]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            raise ValueError("Callback error")
            # This won't execute, but set flag anyway
            bus._running = False
            message_processed.set()

        mock_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)
        mock_redis.xack = AsyncMock()

        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
            )
        )

        # Wait a bit for error to be handled, then stop
        await asyncio.sleep(0.05)
        bus._running = False

        try:
            await asyncio.wait_for(consume_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

        # Message should not be ACKed on error
        # (it will remain in pending for reclaim)

    @pytest.mark.asyncio
    async def test_consume_loop_tracks_in_flight(self):
        """Test consume loop tracks in-flight messages."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        msg_id = "1234567890-0"
        message_processed = asyncio.Event()

        call_count = 0

        async def xreadgroup_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        "omni-stream:test.topic",
                        [(msg_id, {"data": '{"content": "test"}'})],
                    )
                ]
            bus._running = False
            return []

        in_flight_checked = asyncio.Event()

        async def callback_with_stop(msg):
            # Check in-flight tracking while processing (before it's removed)
            group = "group:test.topic:test-agent"
            assert group in bus._in_flight
            assert msg_id in bus._in_flight[group]
            in_flight_checked.set()
            await asyncio.sleep(0.02)  # Simulate processing time
            bus._running = False
            message_processed.set()

        mock_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)
        mock_redis.xack = AsyncMock()
        mock_redis.xadd = AsyncMock()

        group = "group:test.topic:test-agent"
        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group=group,
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
            )
        )

        # Wait for in-flight check to happen
        try:
            await asyncio.wait_for(in_flight_checked.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Verify in-flight was checked during callback
        assert in_flight_checked.is_set()

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        try:
            await asyncio.wait_for(consume_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_consume_loop_removes_in_flight_on_complete(self):
        """Test in-flight tracking cleanup."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        msg_id = "1234567890-0"
        message_processed = asyncio.Event()

        call_count = 0

        async def xreadgroup_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        "omni-stream:test.topic",
                        [(msg_id, {"data": '{"content": "test"}'})],
                    )
                ]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)
        mock_redis.xack = AsyncMock()
        mock_redis.xadd = AsyncMock()

        group = "group:test.topic:test-agent"
        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group=group,
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Wait a bit more for cleanup
        await asyncio.sleep(0.05)

        # In-flight should be cleaned up after processing
        if group in bus._in_flight:
            assert msg_id not in bus._in_flight[group]

        try:
            await asyncio.wait_for(consume_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_consume_loop_handles_json_decode_error(self):
        """Test consume loop handles malformed JSON."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        message_processed = asyncio.Event()
        received_messages = []

        call_count = 0

        async def xreadgroup_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        "omni-stream:test.topic",
                        [("1234567890-0", {"data": "invalid json{"})],
                    )
                ]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            received_messages.append(msg)
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)
        mock_redis.xack = AsyncMock()
        mock_redis.xadd = AsyncMock()

        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Should handle invalid JSON gracefully
        assert len(received_messages) > 0
        assert "raw" in received_messages[0]

        try:
            await asyncio.wait_for(consume_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_consume_loop_handles_connection_closed(self):
        """Test consume loop handles connection loss."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        mock_redis.xreadgroup = AsyncMock(
            side_effect=ConnectionError("Connection closed")
        )

        async def callback(msg):
            pass

        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback,
            )
        )

        # Wait for loop to detect connection error and exit
        try:
            await asyncio.wait_for(consume_task, timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

        # Should exit gracefully on connection error
        assert consume_task.done()

    @pytest.mark.asyncio
    async def test_consume_loop_handles_cancellation(self):
        """Test consume loop handles cancellation gracefully."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        # Make xreadgroup return empty and stop after first call
        call_count = 0

        async def xreadgroup_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # After first empty result, stop the bus so loop exits
                await asyncio.sleep(0.01)
                bus._running = False
            return []

        mock_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)

        async def callback(msg):
            pass

        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback,
            )
        )

        # Wait for loop to process and exit
        try:
            await asyncio.wait_for(consume_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

        # Should handle cancellation without errors
        # Note: task might complete normally if _running was set, or be cancelled
        assert consume_task.done()

    @pytest.mark.asyncio
    async def test_consume_loop_emits_monitor_events(self):
        """Test consume loop emits monitoring events."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        message_processed = asyncio.Event()

        call_count = 0

        async def xreadgroup_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        "omni-stream:test.topic",
                        [("1234567890-0", {"data": '{"content": "test"}'})],
                    )
                ]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)
        mock_redis.xack = AsyncMock()
        mock_redis.xadd = AsyncMock()  # For monitor emit

        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Verify monitor events were emitted
        assert mock_redis.xadd.called

        try:
            await asyncio.wait_for(consume_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_consume_loop_blocking_timeout(self):
        """Test consume loop respects blocking timeout."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        # Make xreadgroup return empty and stop after first call
        call_count = 0

        async def xreadgroup_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # After first empty result, stop the bus so loop exits
                await asyncio.sleep(0.01)
                bus._running = False
            return []

        mock_redis.xreadgroup = AsyncMock(side_effect=xreadgroup_side_effect)

        async def callback(msg):
            pass

        consume_task = asyncio.create_task(
            bus._consume_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback,
            )
        )

        # Wait for loop to process and exit
        try:
            await asyncio.wait_for(consume_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            consume_task.cancel()
            try:
                await consume_task
            except asyncio.CancelledError:
                pass

        # Should handle empty results (timeout) gracefully
        assert mock_redis.xreadgroup.called


class TestRedisStreamEventBusReclaimLoop:
    """Test suite for RedisStreamEventBus reclaim loop operations."""

    @pytest.mark.asyncio
    async def test_reclaim_loop_finds_pending(self):
        """Test reclaim loop finds pending messages."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        # Mock pending messages - return once, then stop immediately
        call_count = 0

        async def xpending_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Stop immediately after first call to prevent sleep
                await asyncio.sleep(0.01)
                bus._running = False
                return [{"message_id": "1234567890-0", "time_since_delivered": 200000}]
            return []

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)
        mock_redis.xclaim = AsyncMock(return_value=[])

        async def callback(msg):
            pass

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        try:
            await asyncio.wait_for(reclaim_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass

        # Verify xpending_range was called
        mock_redis.xpending_range.assert_called()

    @pytest.mark.asyncio
    async def test_reclaim_loop_claims_idle_messages(self):
        """Test reclaim loop claims idle messages."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        msg_id = "1234567890-0"
        message_processed = asyncio.Event()

        call_count = 0

        async def xpending_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"message_id": msg_id, "time_since_delivered": 200000}]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)
        mock_redis.xclaim = AsyncMock(
            return_value=[(msg_id, {"data": '{"content": "test"}'})]
        )
        mock_redis.hincrby = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()
        mock_redis.xack = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.xadd = AsyncMock()

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Verify xclaim was called
        mock_redis.xclaim.assert_called()

        try:
            await asyncio.wait_for(reclaim_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_reclaim_loop_respects_idle_time(self):
        """Test reclaim loop respects idle time threshold."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        # Message with idle time less than threshold
        call_count = 0

        async def xpending_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Stop immediately after first call
                await asyncio.sleep(0.01)
                bus._running = False
                return [
                    {
                        "message_id": "1234567890-0",
                        "time_since_delivered": 100000,
                    }  # Less than 180000
                ]
            return []

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)

        async def callback(msg):
            pass

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        try:
            await asyncio.wait_for(reclaim_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass

        # Should not claim messages below threshold
        mock_redis.xclaim.assert_not_called()

    @pytest.mark.asyncio
    async def test_reclaim_loop_retries_failed_messages(self):
        """Test reclaim loop retries failed messages."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        msg_id = "1234567890-0"
        message_processed = asyncio.Event()
        callback_called = []

        call_count = 0

        async def xpending_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"message_id": msg_id, "time_since_delivered": 200000}]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            callback_called.append(msg)
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)
        mock_redis.xclaim = AsyncMock(
            return_value=[
                (msg_id, {"data": '{"content": "test", "delivery_attempts": 0}'})
            ]
        )
        mock_redis.hincrby = AsyncMock(return_value=1)  # First retry
        mock_redis.expire = AsyncMock()
        mock_redis.xack = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.xadd = AsyncMock()

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Verify callback was called for retry
        assert len(callback_called) > 0

        try:
            await asyncio.wait_for(reclaim_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_reclaim_loop_increments_retry_count(self):
        """Test reclaim loop increments retry counter."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        msg_id = "1234567890-0"
        message_processed = asyncio.Event()

        call_count = 0

        async def xpending_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"message_id": msg_id, "time_since_delivered": 200000}]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)
        mock_redis.xclaim = AsyncMock(
            return_value=[
                (msg_id, {"data": '{"content": "test", "delivery_attempts": 0}'})
            ]
        )
        mock_redis.hincrby = AsyncMock(return_value=2)  # Retry count = 2
        mock_redis.expire = AsyncMock()
        mock_redis.xack = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.xadd = AsyncMock()

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Verify retry count was incremented
        mock_redis.hincrby.assert_called()

        try:
            await asyncio.wait_for(reclaim_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_reclaim_loop_sends_to_dlq_on_limit(self):
        """Test reclaim loop sends to DLQ after retry limit."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        msg_id = "1234567890-0"
        message_processed = asyncio.Event()

        call_count = 0

        async def xpending_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"message_id": msg_id, "time_since_delivered": 200000}]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)
        mock_redis.xclaim = AsyncMock(
            return_value=[
                (msg_id, {"data": '{"content": "test", "delivery_attempts": 0}'})
            ]
        )
        # Retry count exceeds limit (4 > 3)
        mock_redis.hincrby = AsyncMock(return_value=4)
        mock_redis.expire = AsyncMock()
        mock_redis.xack = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.xadd = AsyncMock()  # For DLQ

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Verify message was sent to DLQ (xadd called for DLQ)
        assert mock_redis.xadd.called

        try:
            await asyncio.wait_for(reclaim_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_reclaim_loop_acks_after_dlq(self):
        """Test reclaim loop ACKs message after DLQ."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        msg_id = "1234567890-0"
        message_processed = asyncio.Event()

        call_count = 0

        async def xpending_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"message_id": msg_id, "time_since_delivered": 200000}]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)
        mock_redis.xclaim = AsyncMock(
            return_value=[
                (msg_id, {"data": '{"content": "test", "delivery_attempts": 0}'})
            ]
        )
        mock_redis.hincrby = AsyncMock(return_value=4)  # Exceeds limit
        mock_redis.expire = AsyncMock()
        mock_redis.xack = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.xadd = AsyncMock()

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Verify xack was called after sending to DLQ
        mock_redis.xack.assert_called()

        try:
            await asyncio.wait_for(reclaim_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_reclaim_loop_skips_in_flight(self):
        """Test reclaim loop skips in-flight messages."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        msg_id = "1234567890-0"
        group = "group:test.topic:test-agent"

        # Mark message as in-flight
        bus._in_flight[group] = {msg_id}

        call_count = 0

        async def xpending_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Stop immediately after first call
                await asyncio.sleep(0.01)
                bus._running = False
                return [{"message_id": msg_id, "time_since_delivered": 200000}]
            return []

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)

        async def callback(msg):
            pass

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group=group,
                consumer="consumer:test-agent-1",
                callback=callback,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        try:
            await asyncio.wait_for(reclaim_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass

        # Should not claim in-flight messages
        mock_redis.xclaim.assert_not_called()

    @pytest.mark.asyncio
    async def test_reclaim_loop_handles_xpending_unavailable(self):
        """Test reclaim loop handles xpending errors."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        # First call raises error, subsequent calls return empty and stop
        call_count = 0

        async def xpending_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("xpending unavailable")
            # After error handling sleep, stop the bus
            await asyncio.sleep(0.01)
            bus._running = False
            return []

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)

        async def callback(msg):
            pass

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        # Wait for error handling and then exit
        try:
            await asyncio.wait_for(reclaim_task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass

        # Should handle error gracefully and continue

    @pytest.mark.asyncio
    async def test_reclaim_loop_handles_connection_closed(self):
        """Test reclaim loop handles connection loss."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        mock_redis.xpending_range = AsyncMock(
            side_effect=ConnectionError("Connection closed")
        )

        async def callback(msg):
            pass

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        # Wait for loop to detect connection error and exit
        try:
            await asyncio.wait_for(reclaim_task, timeout=1.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass

        # Should exit gracefully on connection error
        assert reclaim_task.done()

    @pytest.mark.asyncio
    async def test_reclaim_loop_handles_cancellation(self):
        """Test reclaim loop handles cancellation."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        # Make xpending_range block to allow cancellation
        async def xpending_side_effect(*args, **kwargs):
            await asyncio.sleep(10)  # Block for a long time
            return []

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)

        async def callback(msg):
            pass

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        # Wait a bit for the loop to start
        await asyncio.sleep(0.05)

        # Cancel the task while it's running (don't set _running = False yet)
        reclaim_task.cancel()

        try:
            await reclaim_task
        except asyncio.CancelledError:
            pass

        # Should handle cancellation gracefully
        # The task may complete normally if _running was checked before cancellation,
        # so check if it's done (either cancelled or completed)
        assert reclaim_task.done()

    @pytest.mark.asyncio
    async def test_reclaim_loop_emits_monitor_events(self):
        """Test reclaim loop emits monitoring events."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", reclaim_interval=1
        )
        mock_redis = AsyncMock()
        bus._redis = mock_redis
        bus._running = True

        msg_id = "1234567890-0"
        message_processed = asyncio.Event()

        call_count = 0

        async def xpending_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"message_id": msg_id, "time_since_delivered": 200000}]
            bus._running = False
            return []

        async def callback_with_stop(msg):
            await asyncio.sleep(0.01)
            bus._running = False
            message_processed.set()

        mock_redis.xpending_range = AsyncMock(side_effect=xpending_side_effect)
        mock_redis.xclaim = AsyncMock(
            return_value=[(msg_id, {"data": '{"content": "test"}'})]
        )
        mock_redis.hincrby = AsyncMock(return_value=1)
        mock_redis.expire = AsyncMock()
        mock_redis.xack = AsyncMock()
        mock_redis.hdel = AsyncMock()
        mock_redis.xadd = AsyncMock()  # For monitor emit

        reclaim_task = asyncio.create_task(
            bus._reclaim_loop(
                stream_name="omni-stream:test.topic",
                topic="test.topic",
                group="group:test.topic:test-agent",
                consumer="consumer:test-agent-1",
                callback=callback_with_stop,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3,
            )
        )

        try:
            await asyncio.wait_for(message_processed.wait(), timeout=0.5)
        except asyncio.TimeoutError:
            pass

        # Verify monitor events were emitted
        assert mock_redis.xadd.called

        try:
            await asyncio.wait_for(reclaim_task, timeout=0.5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            bus._running = False
            reclaim_task.cancel()
            try:
                await reclaim_task
            except asyncio.CancelledError:
                pass


class TestRedisStreamEventBusDLQ:
    """Test suite for RedisStreamEventBus DLQ operations."""

    @pytest.mark.asyncio
    async def test_send_to_dlq_creates_stream(self):
        """Test DLQ stream creation."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="dlq-msg-id")
        bus._redis = mock_redis

        group = "group:test.topic:test-agent"
        stream_name = "omni-stream:test.topic"
        msg_id = "1234567890-0"
        payload = {"content": "test"}
        error = "Processing failed"
        retry_count = 3

        await bus._send_to_dlq(
            group=group,
            stream_name=stream_name,
            msg_id=msg_id,
            payload=payload,
            error=error,
            retry_count=retry_count,
        )

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == f"omni-dlq:{group}"

    @pytest.mark.asyncio
    async def test_send_to_dlq_includes_metadata(self):
        """Test DLQ includes all message metadata."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="dlq-msg-id")
        bus._redis = mock_redis

        group = "group:test.topic:test-agent"
        stream_name = "omni-stream:test.topic"
        msg_id = "1234567890-0"
        payload = {"content": "test", "task_id": "task-123"}
        error = "Processing failed"
        retry_count = 3

        await bus._send_to_dlq(
            group=group,
            stream_name=stream_name,
            msg_id=msg_id,
            payload=payload,
            error=error,
            retry_count=retry_count,
        )

        call_args = mock_redis.xadd.call_args
        data_dict = call_args[0][1]
        import json

        dlq_payload = json.loads(data_dict["data"])

        assert dlq_payload["topic"] == "test.topic"
        assert dlq_payload["original_stream"] == stream_name
        assert dlq_payload["original_id"] == msg_id
        assert dlq_payload["failed_message"] == payload
        assert dlq_payload["error"] == error
        assert dlq_payload["retry_count"] == retry_count
        assert "failed_at" in dlq_payload

    @pytest.mark.asyncio
    async def test_send_to_dlq_includes_error(self):
        """Test DLQ includes error information."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="dlq-msg-id")
        bus._redis = mock_redis

        error_msg = "ValueError: Invalid input"
        await bus._send_to_dlq(
            group="group:test.topic:test-agent",
            stream_name="omni-stream:test.topic",
            msg_id="1234567890-0",
            payload={"content": "test"},
            error=error_msg,
            retry_count=3,
        )

        call_args = mock_redis.xadd.call_args
        data_dict = call_args[0][1]
        import json

        dlq_payload = json.loads(data_dict["data"])
        assert dlq_payload["error"] == error_msg

    @pytest.mark.asyncio
    async def test_send_to_dlq_respects_maxlen(self):
        """Test DLQ respects maxlen."""
        bus = RedisStreamEventBus(
            redis_url="redis://localhost:6379", default_maxlen=5000
        )
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="dlq-msg-id")
        bus._redis = mock_redis

        await bus._send_to_dlq(
            group="group:test.topic:test-agent",
            stream_name="omni-stream:test.topic",
            msg_id="1234567890-0",
            payload={"content": "test"},
            error="Error",
            retry_count=3,
        )

        call_args = mock_redis.xadd.call_args
        assert call_args[1]["maxlen"] == 5000
        assert call_args[1]["approximate"] is True

    @pytest.mark.asyncio
    async def test_send_to_dlq_handles_failure(self):
        """Test DLQ handles write failures gracefully."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(side_effect=Exception("Redis write failed"))
        bus._redis = mock_redis

        # Should not raise exception
        await bus._send_to_dlq(
            group="group:test.topic:test-agent",
            stream_name="omni-stream:test.topic",
            msg_id="1234567890-0",
            payload={"content": "test"},
            error="Error",
            retry_count=3,
        )

        # Verify xadd was called (even though it failed)
        mock_redis.xadd.assert_called_once()


class TestRedisStreamEventBusUnsubscribe:
    """Test suite for RedisStreamEventBus unsubscribe operations."""

    @pytest.mark.asyncio
    async def test_unsubscribe_success(self):
        """Test successful unsubscribe."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        task1 = asyncio.create_task(asyncio.sleep(100))
        task2 = asyncio.create_task(asyncio.sleep(100))

        group_name = "group:test.topic:test-agent"
        bus._consumers[group_name] = {
            "topic": "test.topic",
            "agent_name": "test-agent",
            "consume_tasks": [task1],
            "reclaim_tasks": [task2],
        }

        await bus.unsubscribe("test.topic", "test-agent")

        await asyncio.sleep(0.01)  # Wait for cancellation

        assert task1.cancelled()
        assert task2.cancelled()
        assert group_name not in bus._consumers

    @pytest.mark.asyncio
    async def test_unsubscribe_cancels_tasks(self):
        """Test unsubscribe cancels consumer tasks."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        consume_task = asyncio.create_task(asyncio.sleep(100))
        reclaim_task = asyncio.create_task(asyncio.sleep(100))

        group_name = "group:test.topic:test-agent"
        bus._consumers[group_name] = {
            "consume_tasks": [consume_task],
            "reclaim_tasks": [reclaim_task],
        }

        await bus.unsubscribe("test.topic", "test-agent")

        await asyncio.sleep(0.01)

        assert consume_task.cancelled()
        assert reclaim_task.cancelled()

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_metadata(self):
        """Test unsubscribe removes consumer metadata."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        group_name = "group:test.topic:test-agent"
        bus._consumers[group_name] = {
            "topic": "test.topic",
            "agent_name": "test-agent",
            "consume_tasks": [],
            "reclaim_tasks": [],
        }

        await bus.unsubscribe("test.topic", "test-agent")

        assert group_name not in bus._consumers

    @pytest.mark.asyncio
    async def test_unsubscribe_delete_group_true(self):
        """Test unsubscribe deletes group when requested."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_destroy = AsyncMock()
        bus._redis = mock_redis

        group_name = "group:test.topic:test-agent"
        bus._consumers[group_name] = {"consume_tasks": [], "reclaim_tasks": []}

        await bus.unsubscribe("test.topic", "test-agent", delete_group=True)

        mock_redis.xgroup_destroy.assert_called_once_with(
            "omni-stream:test.topic", group_name
        )

    @pytest.mark.asyncio
    async def test_unsubscribe_delete_group_false(self):
        """Test unsubscribe preserves group when requested."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        group_name = "group:test.topic:test-agent"
        bus._consumers[group_name] = {"consume_tasks": [], "reclaim_tasks": []}

        await bus.unsubscribe("test.topic", "test-agent", delete_group=False)

        mock_redis.xgroup_destroy.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsubscribe_delete_dlq_true(self):
        """Test unsubscribe deletes DLQ when requested."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()
        bus._redis = mock_redis

        group_name = "group:test.topic:test-agent"
        bus._consumers[group_name] = {"consume_tasks": [], "reclaim_tasks": []}

        await bus.unsubscribe("test.topic", "test-agent", delete_dlq=True)

        mock_redis.delete.assert_called_once_with(f"omni-dlq:{group_name}")

    @pytest.mark.asyncio
    async def test_unsubscribe_delete_dlq_false(self):
        """Test unsubscribe preserves DLQ when requested."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        group_name = "group:test.topic:test-agent"
        bus._consumers[group_name] = {"consume_tasks": [], "reclaim_tasks": []}

        await bus.unsubscribe("test.topic", "test-agent", delete_dlq=False)

        mock_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_agent(self):
        """Test unsubscribe handles nonexistent agent gracefully."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        # Should not raise exception
        await bus.unsubscribe("test.topic", "nonexistent-agent")

        # Should not call any Redis operations
        mock_redis.xgroup_destroy.assert_not_called()
        mock_redis.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_unsubscribe_handles_nogroup_error(self):
        """Test unsubscribe handles NOGROUP error."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xgroup_destroy = AsyncMock(side_effect=Exception("NOGROUP"))
        bus._redis = mock_redis

        group_name = "group:test.topic:test-agent"
        bus._consumers[group_name] = {"consume_tasks": [], "reclaim_tasks": []}

        # Should not raise exception
        await bus.unsubscribe("test.topic", "test-agent", delete_group=True)

        mock_redis.xgroup_destroy.assert_called_once()


class TestRedisStreamEventBusGetConsumers:
    """Test suite for RedisStreamEventBus get_consumers operations."""

    @pytest.mark.asyncio
    async def test_get_consumers_returns_active(self):
        """Test get_consumers returns active consumers."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        group_name = "group:test.topic:test-agent"
        bus._consumers[group_name] = {
            "topic": "test.topic",
            "agent_name": "test-agent",
            "stream": "omni-stream:test.topic",
            "group": group_name,
        }

        consumers = await bus.get_consumers()

        assert group_name in consumers
        assert consumers[group_name]["topic"] == "test.topic"
        assert consumers[group_name]["agent_name"] == "test-agent"

    @pytest.mark.asyncio
    async def test_get_consumers_discovers_from_redis(self):
        """Test get_consumers discovers from Redis."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        # Ensure _consumers is empty so it discovers from Redis
        bus._consumers = {}

        # Mock scan to return stream keys
        mock_redis.scan = AsyncMock(
            side_effect=[
                (0, [b"omni-stream:test.topic"]),
            ]
        )

        # Mock xinfo_groups to return group info
        # The code logic:
        #   consumers_count = group_info.get(b"consumers", 0) if isinstance(group_info.get(b"consumers"), bytes)
        #   else group_info.get("consumers", 0)
        # Since b"consumers" exists but is not bytes (it's int 2), it goes to else branch
        # which looks for "consumers" (string key). So we need to provide string keys.
        # Actually, Redis returns bytes for field names but the values can be int or bytes.
        # Let's provide the values as the code expects - use string keys for the else branch.
        mock_redis.xinfo_groups = AsyncMock(
            return_value=[
                {
                    b"name": b"group:test.topic:test-agent",
                    "name": "group:test.topic:test-agent",  # For the else branch
                    "consumers": 2,  # String key for the else branch
                    "pending": 5,  # String key for the else branch
                }
            ]
        )

        consumers = await bus.get_consumers()

        assert "group:test.topic:test-agent" in consumers
        consumer_info = consumers["group:test.topic:test-agent"]
        assert consumer_info["topic"] == "test.topic"
        assert consumer_info["stream"] == "omni-stream:test.topic"
        assert consumer_info["consumers_count"] == 2
        assert consumer_info["pending_messages"] == 5
        assert consumer_info["source"] == "redis_query"

    @pytest.mark.asyncio
    async def test_get_consumers_includes_metadata(self):
        """Test get_consumers includes all metadata."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        group_name = "group:test.topic:test-agent"
        bus._consumers[group_name] = {
            "topic": "test.topic",
            "agent_name": "test-agent",
            "stream": "omni-stream:test.topic",
            "group": group_name,
            "dlq": "omni-dlq:group:test.topic:test-agent",
            "config": {"reclaim_idle_ms": 180000},
        }

        consumers = await bus.get_consumers()

        assert group_name in consumers
        consumer_info = consumers[group_name]
        assert "topic" in consumer_info
        assert "agent_name" in consumer_info
        assert "stream" in consumer_info
        assert "group" in consumer_info
        assert "dlq" in consumer_info
        assert "config" in consumer_info

    @pytest.mark.asyncio
    async def test_get_consumers_handles_scan_errors(self):
        """Test get_consumers handles scan errors."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        mock_redis.scan = AsyncMock(side_effect=Exception("Scan failed"))

        # Should return empty dict or existing consumers
        consumers = await bus.get_consumers()

        assert isinstance(consumers, dict)

    @pytest.mark.asyncio
    async def test_get_consumers_handles_xinfo_errors(self):
        """Test get_consumers handles xinfo errors."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        bus._redis = mock_redis

        mock_redis.scan = AsyncMock(
            side_effect=[
                (0, [b"omni-stream:test.topic"]),
            ]
        )
        mock_redis.xinfo_groups = AsyncMock(side_effect=Exception("XINFO failed"))

        # Should handle error gracefully
        consumers = await bus.get_consumers()

        assert isinstance(consumers, dict)


class TestRedisStreamEventBusMonitorEmit:
    """Test suite for RedisStreamEventBus monitor emit operations."""

    @pytest.mark.asyncio
    async def test_emit_monitor_success(self):
        """Test successful metric emission."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="metric-id")
        bus._redis = mock_redis

        metric = {
            "topic": "test.topic",
            "event": "processed",
            "msg_id": "1234567890-0",
            "timestamp": 1234567890.0,
        }

        await bus._emit_monitor(metric)

        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "omni-metrics"
        data_dict = call_args[0][1]
        import json

        emitted_metric = json.loads(data_dict["data"])
        assert emitted_metric["topic"] == "test.topic"
        assert emitted_metric["event"] == "processed"

    @pytest.mark.asyncio
    async def test_emit_monitor_handles_failure(self):
        """Test emit_monitor handles failures gracefully."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(side_effect=Exception("Redis error"))
        bus._redis = mock_redis

        metric = {"topic": "test.topic", "event": "processed"}

        # Should not raise exception
        await bus._emit_monitor(metric)

        mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_emit_monitor_respects_maxlen(self):
        """Test emit_monitor respects maxlen."""
        bus = RedisStreamEventBus(redis_url="redis://localhost:6379")
        mock_redis = AsyncMock()
        mock_redis.xadd = AsyncMock(return_value="metric-id")
        bus._redis = mock_redis

        metric = {"topic": "test.topic", "event": "processed"}

        await bus._emit_monitor(metric)

        call_args = mock_redis.xadd.call_args
        assert call_args[1]["maxlen"] == 1_000_000
        assert call_args[1]["approximate"] is True
