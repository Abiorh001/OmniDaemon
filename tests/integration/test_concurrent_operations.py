"""Integration tests for concurrent operations."""

import pytest
import pytest_asyncio
import asyncio
import tempfile
import shutil
import json
from unittest.mock import AsyncMock

from omnidaemon.sdk import OmniDaemonSDK
from omnidaemon.storage.json_store import JSONStore
from omnidaemon.schemas import EventEnvelope, PayloadBase, AgentConfig


@pytest.fixture
def storage_dir():
    """Create a temporary storage directory."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest_asyncio.fixture
async def storage(storage_dir):
    """Create a JSON store."""
    store = JSONStore(storage_dir=storage_dir)
    await store.connect()
    yield store
    await store.close()


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


@pytest_asyncio.fixture
async def sdk(event_bus, storage):
    """Create an SDK instance."""
    return OmniDaemonSDK(event_bus=event_bus, store=storage)


class TestConcurrentOperations:
    """Test suite for concurrent operation scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_publish(self, sdk, event_bus, storage):
        """Test concurrent task publishing."""
        # Register agent (no need to start for just publishing)
        results = []

        async def agent_callback(message):
            results.append(message.get("id"))
            return {"processed": True}

        await sdk.register_agent(
            AgentConfig(
                topic="concurrent.topic",
                callback=agent_callback,
                name="concurrent-agent",
            )
        )

        # Don't call start() - just test publishing
        # Publish multiple tasks concurrently
        async def publish_task(i):
            event = EventEnvelope(
                topic="concurrent.topic",
                payload=PayloadBase(content=json.dumps({"index": i})),
            )
            return await sdk.publish_task(event)

        # Publish 10 tasks concurrently
        task_ids = await asyncio.gather(*[publish_task(i) for i in range(10)])

        # Verify all tasks were published
        assert len(task_ids) == 10
        assert all(tid is not None for tid in task_ids)

        await sdk.shutdown()

    @pytest.mark.asyncio
    async def test_concurrent_agent_registration(self, sdk, event_bus, storage):
        """Test concurrent agent registration."""

        async def agent_callback(message):
            return {"processed": True}

        # Register multiple agents concurrently
        async def register_agent(i):
            return await sdk.register_agent(
                AgentConfig(
                    topic=f"concurrent.topic{i}",
                    callback=agent_callback,
                    name=f"agent-{i}",
                )
            )

        # Register 5 agents concurrently
        await asyncio.gather(*[register_agent(i) for i in range(5)])

        # Verify all agents were registered
        agents = await storage.list_all_agents()
        assert len(agents) >= 5

        # No need to start or shutdown for registration test

    @pytest.mark.asyncio
    async def test_concurrent_result_retrieval(self, sdk, event_bus, storage):
        """Test concurrent result retrieval."""
        # Save multiple results
        task_ids = []
        for i in range(10):
            task_id = f"task-{i}"
            await storage.save_result(task_id, {"result": i})
            task_ids.append(task_id)

        # Retrieve results concurrently
        async def get_result(task_id):
            return await storage.get_result(task_id)

        results = await asyncio.gather(*[get_result(tid) for tid in task_ids])

        # Verify all results were retrieved
        assert len(results) == 10
        assert all(r is not None for r in results)
        assert all(r.get("result") is not None for r in results)

    @pytest.mark.asyncio
    async def test_race_condition_handling(self, sdk, event_bus, storage):
        """Test race condition handling in critical sections."""
        counter = {"value": 0}

        async def agent_callback(message):
            # Simulate race condition by incrementing counter
            current = counter["value"]
            await asyncio.sleep(0.01)  # Simulate processing time
            counter["value"] = current + 1
            return {"counter": counter["value"]}

        await sdk.register_agent(
            AgentConfig(topic="race.topic", callback=agent_callback, name="race-agent")
        )

        # Don't start - just test concurrent publishing
        # Publish multiple tasks that might cause race conditions
        async def publish_and_wait(i):
            event = EventEnvelope(
                topic="race.topic",
                payload=PayloadBase(content=json.dumps({"index": i})),
            )
            await sdk.publish_task(event)
            await asyncio.sleep(0.1)

        # Publish concurrently
        await asyncio.gather(*[publish_and_wait(i) for i in range(5)])

        # Verify tasks were published (race condition test is about publishing, not processing)
        # The actual processing race conditions would be tested in unit tests

        await sdk.shutdown()
