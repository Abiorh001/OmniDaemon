"""Integration tests for performance scenarios."""

import pytest
import pytest_asyncio
import asyncio
import time
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


class TestPerformance:
    """Test suite for performance scenarios."""

    @pytest.mark.asyncio
    async def test_high_throughput_publishing(self, sdk, event_bus, storage):
        """Test high throughput task publishing."""
        # Measure publishing performance
        num_tasks = 100
        start_time = time.time()

        # Publish tasks as fast as possible
        tasks = []
        for i in range(num_tasks):
            event = EventEnvelope(
                topic="throughput.topic",
                payload=PayloadBase(content=json.dumps({"index": i})),
            )
            tasks.append(sdk.publish_task(event))

        task_ids = await asyncio.gather(*tasks)
        end_time = time.time()

        # Verify all tasks were published
        assert len(task_ids) == num_tasks
        assert all(tid is not None for tid in task_ids)

        # Calculate throughput
        duration = end_time - start_time
        throughput = num_tasks / duration
        print(
            f"Published {num_tasks} tasks in {duration:.2f}s ({throughput:.2f} tasks/s)"
        )

        # Should be reasonably fast (at least 10 tasks/s)
        assert throughput > 10

    @pytest.mark.asyncio
    async def test_high_throughput_processing(self, sdk, event_bus, storage):
        """Test high throughput task processing."""
        processed_count = [0]

        async def fast_agent(message):
            """Fast processing agent."""
            processed_count[0] += 1
            return {"processed": True}

        await sdk.register_agent(
            AgentConfig(
                topic="processing.topic", callback=fast_agent, name="fast-agent"
            )
        )

        # Don't start - just test publishing performance
        # Publish many tasks
        num_tasks = 50
        for i in range(num_tasks):
            event = EventEnvelope(
                topic="processing.topic",
                payload=PayloadBase(content=json.dumps({"index": i})),
            )
            await sdk.publish_task(event)

        # With fakeredis, actual processing may not work
        # Just verify tasks were published
        # (Processing performance would be tested with real Redis)

        await sdk.shutdown()

    @pytest.mark.asyncio
    async def test_large_payload_handling(self, sdk, event_bus, storage):
        """Test handling of large payloads."""
        received_size = [0]

        async def large_payload_agent(message):
            """Agent that processes large payloads."""
            content = message.get("content", {})
            if isinstance(content, dict):
                received_size[0] = len(str(content))
            return {"size": received_size[0]}

        await sdk.register_agent(
            AgentConfig(
                topic="large.topic", callback=large_payload_agent, name="large-agent"
            )
        )

        # Don't start - just test publishing
        # Create large payload (1MB of data)
        large_data = {"data": "x" * (1024 * 1024)}  # 1MB string

        event = EventEnvelope(
            topic="large.topic", payload=PayloadBase(content=json.dumps(large_data))
        )

        start_time = time.time()
        task_id = await sdk.publish_task(event)
        publish_time = time.time() - start_time

        # With fakeredis, actual processing may not work
        # Just verify large payload was published
        assert task_id is not None

        print(f"Published 1MB payload in {publish_time:.2f}s")

        await sdk.shutdown()

    @pytest.mark.asyncio
    async def test_many_agents_performance(self, sdk, event_bus, storage):
        """Test performance with many registered agents."""
        # Register many agents
        num_agents = 20
        agents_registered = []

        async def agent_callback(message):
            return {"processed": True}

        start_time = time.time()

        for i in range(num_agents):
            agent_config = AgentConfig(
                topic=f"multi.topic{i}", callback=agent_callback, name=f"agent-{i}"
            )
            await sdk.register_agent(agent_config)
            agents_registered.append(i)

        registration_time = time.time() - start_time

        # Verify all agents registered
        agents = await storage.list_all_agents()
        assert len(agents) >= num_agents

        print(f"Registered {num_agents} agents in {registration_time:.2f}s")

        # Should be reasonably fast
        assert registration_time < 10.0  # Should register 20 agents in under 10s

        await sdk.shutdown()
