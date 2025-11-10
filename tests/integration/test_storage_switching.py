"""Integration tests for storage backend switching."""

import pytest
import pytest_asyncio
import tempfile
import shutil
import json
from unittest.mock import AsyncMock

from omnidaemon.sdk import OmniDaemonSDK
from omnidaemon.storage.json_store import JSONStore
from omnidaemon.schemas import EventEnvelope, PayloadBase, AgentConfig


@pytest_asyncio.fixture
async def event_bus():
    """Create a mocked event bus that doesn't block."""
    bus = AsyncMock()
    bus.connect = AsyncMock()
    bus.close = AsyncMock()

    # Make publish return the task ID from the event payload
    async def mock_publish(event_payload, maxlen=None):
        return event_payload.get("id", "task-123")

    bus.publish = AsyncMock(side_effect=mock_publish)

    bus.subscribe = AsyncMock()  # Don't start consume loops
    bus.unsubscribe = AsyncMock()
    bus.get_consumers = AsyncMock(return_value={})
    bus._running = False
    bus._connected = True
    yield bus


@pytest.fixture
def storage_dir():
    """Create a temporary storage directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


class TestStorageBackendSwitching:
    """Test suite for storage backend switching scenarios."""

    @pytest.mark.asyncio
    async def test_json_to_redis_migration(self, event_bus, storage_dir):
        """Test switching from JSON to Redis storage."""
        # Start with JSON store
        json_store = JSONStore(storage_dir=storage_dir)
        await json_store.connect()

        sdk_json = OmniDaemonSDK(event_bus=event_bus, store=json_store)

        # Register an agent with JSON store
        async def agent_callback(message):
            return {"processed": True}

        # Register agent - this will call subscribe which is mocked
        await sdk_json.register_agent(
            AgentConfig(
                topic="migration.topic", callback=agent_callback, name="migration-agent"
            )
        )

        # Verify agent is stored in JSON
        agents = await json_store.list_all_agents()
        assert "migration.topic" in agents
        assert len(agents["migration.topic"]) > 0

        await json_store.close()

        # Switch to Redis store (simulated - would need RedisStore implementation)
        # For now, we verify JSON data persists
        json_store2 = JSONStore(storage_dir=storage_dir)
        await json_store2.connect()

        # Verify data still exists
        agents2 = await json_store2.list_all_agents()
        assert "migration.topic" in agents2

        await json_store2.close()

    @pytest.mark.asyncio
    async def test_redis_to_json_migration(self, event_bus, storage_dir):
        """Test switching from Redis to JSON storage."""
        # This test would require a RedisStore implementation
        # For now, we test that JSON store can be used as replacement

        json_store = JSONStore(storage_dir=storage_dir)
        await json_store.connect()

        sdk = OmniDaemonSDK(event_bus=event_bus, store=json_store)

        # Register agent
        async def agent_callback(message):
            return {"processed": True}

        # Register agent - this will call subscribe which is mocked
        await sdk.register_agent(
            AgentConfig(
                topic="migration2.topic",
                callback=agent_callback,
                name="migration2-agent",
            )
        )

        # Verify agent is stored
        agents = await json_store.list_all_agents()
        assert "migration2.topic" in agents

        await json_store.close()

    @pytest.mark.asyncio
    async def test_data_persistence_across_restarts(self, event_bus, storage_dir):
        """Test data persists across runner restarts."""
        # First run: register agent and publish task
        json_store1 = JSONStore(storage_dir=storage_dir)
        await json_store1.connect()

        sdk1 = OmniDaemonSDK(event_bus=event_bus, store=json_store1)

        async def agent_callback(message):
            return {"result": "persisted"}

        # Register agent - this will call subscribe which is mocked
        await sdk1.register_agent(
            AgentConfig(
                topic="persist.topic", callback=agent_callback, name="persist-agent"
            )
        )

        # Publish a task
        event = EventEnvelope(
            topic="persist.topic",
            payload=PayloadBase(content=json.dumps({"test": "data"})),
        )
        task_id = await sdk1.publish_task(event)

        # Save a result
        await json_store1.save_result(task_id, {"result": "test"})

        await sdk1.shutdown()
        await json_store1.close()

        # Simulate restart: create new SDK with same storage
        json_store2 = JSONStore(storage_dir=storage_dir)
        await json_store2.connect()

        sdk2 = OmniDaemonSDK(event_bus=event_bus, store=json_store2)

        # Verify agent still exists
        agents = await json_store2.list_all_agents()
        assert "persist.topic" in agents

        # Verify result still exists
        result = await json_store2.get_result(task_id)
        assert result is not None
        assert result.get("result") == "test"

        await sdk2.shutdown()
        await json_store2.close()
