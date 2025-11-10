"""Unit tests for OmniDaemonSDK - Complete (Sections 4.1-4.16)."""

import pytest
import time
from unittest.mock import AsyncMock, patch
from pydantic import ValidationError
from omnidaemon.sdk import OmniDaemonSDK
from omnidaemon.schemas import (
    AgentConfig,
    EventEnvelope,
    PayloadBase,
    SubscriptionConfig,
)
from omnidaemon.agent_runner.runner import BaseAgentRunner


class TestOmniDaemonSDKInitialization:
    """Test suite for OmniDaemonSDK initialization."""

    @pytest.mark.asyncio
    async def test_sdk_init_defaults(self):
        """Test SDK initialization with default dependencies."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        with (
            patch("omnidaemon.sdk.default_event_bus", new=mock_bus),
            patch("omnidaemon.sdk.default_store", new=mock_store),
        ):
            sdk = OmniDaemonSDK()

            assert sdk.event_bus is mock_bus
            assert sdk.store is mock_store
            assert isinstance(sdk.runner, BaseAgentRunner)
            assert sdk.runner.event_bus is mock_bus
            assert sdk.runner.store is mock_store
            assert sdk._agents == []
            assert sdk._start_time is None
            assert sdk._is_running is False

    @pytest.mark.asyncio
    async def test_sdk_init_custom_event_bus(self):
        """Test SDK initialization with custom event bus."""
        mock_custom_bus = AsyncMock()
        mock_store = AsyncMock()
        with patch("omnidaemon.sdk.default_store", new=mock_store):
            sdk = OmniDaemonSDK(event_bus=mock_custom_bus)

            assert sdk.event_bus is mock_custom_bus
            assert sdk.store is mock_store
            assert sdk.runner.event_bus is mock_custom_bus

    @pytest.mark.asyncio
    async def test_sdk_init_custom_store(self):
        """Test SDK initialization with custom store."""
        mock_custom_store = AsyncMock()
        mock_bus = AsyncMock()
        with patch("omnidaemon.sdk.default_event_bus", new=mock_bus):
            sdk = OmniDaemonSDK(store=mock_custom_store)

            assert sdk.event_bus is mock_bus
            assert sdk.store is mock_custom_store
            assert sdk.runner.store is mock_custom_store

    @pytest.mark.asyncio
    async def test_sdk_init_creates_runner(self):
        """Test SDK creates BaseAgentRunner."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        assert isinstance(sdk.runner, BaseAgentRunner)
        assert sdk.runner.event_bus is mock_bus
        assert sdk.runner.store is mock_store


class TestOmniDaemonSDKPublishTask:
    """Test suite for OmniDaemonSDK publish_task operations."""

    @pytest.mark.asyncio
    async def test_publish_task_success(self):
        """Test successful task publication."""
        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock(return_value="task-123")
        mock_store = AsyncMock()
        # Create a real runner - it will use event_bus.publish
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        event = EventEnvelope(
            topic="test.topic", payload=PayloadBase(content="test content")
        )

        task_id = await sdk.publish_task(event)

        assert task_id == "task-123"
        mock_bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_task_generates_id(self):
        """Test publish_task generates ID if missing."""
        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock(return_value="generated-id-123")
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Event without explicit ID
        event = EventEnvelope(topic="test.topic", payload=PayloadBase(content="test"))

        task_id = await sdk.publish_task(event)

        assert task_id == "generated-id-123"
        # Verify the event was published with a generated ID
        call_args = mock_bus.publish.call_args
        published_event = call_args[1]["event_payload"]
        assert "id" in published_event

    @pytest.mark.asyncio
    async def test_publish_task_preserves_id(self):
        """Test publish_task preserves provided ID."""
        mock_bus = AsyncMock()
        custom_id = "custom-task-id-456"
        mock_bus.publish = AsyncMock(return_value=custom_id)
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        event = EventEnvelope(
            id=custom_id, topic="test.topic", payload=PayloadBase(content="test")
        )

        task_id = await sdk.publish_task(event)

        assert task_id == custom_id
        call_args = mock_bus.publish.call_args
        published_event = call_args[1]["event_payload"]
        assert published_event["id"] == custom_id

    @pytest.mark.asyncio
    async def test_publish_task_all_fields(self):
        """Test publish_task with all EventEnvelope fields."""
        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock(return_value="task-123")
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        event = EventEnvelope(
            id="task-123",
            topic="test.topic",
            payload=PayloadBase(
                content="test content",
                webhook="https://example.com/webhook",
                reply_to="reply.topic",
            ),
            tenant_id="tenant-123",
            correlation_id="corr-123",
            causation_id="cause-123",
            source="test-source",
        )

        await sdk.publish_task(event)

        call_args = mock_bus.publish.call_args
        published_event = call_args[1]["event_payload"]
        assert published_event["topic"] == "test.topic"
        assert published_event["id"] == "task-123"
        assert published_event["tenant_id"] == "tenant-123"
        assert published_event["correlation_id"] == "corr-123"
        assert published_event["causation_id"] == "cause-123"
        assert published_event["source"] == "test-source"
        assert published_event["payload"]["content"] == "test content"
        assert published_event["payload"]["webhook"] == "https://example.com/webhook"
        assert published_event["payload"]["reply_to"] == "reply.topic"

    @pytest.mark.asyncio
    async def test_publish_task_validation_error(self):
        """Test publish_task handles ValidationError."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Create invalid event (missing required topic)
        with pytest.raises(ValidationError):
            event = EventEnvelope(
                # Missing topic
                payload=PayloadBase(content="test")
            )
            await sdk.publish_task(event)

    @pytest.mark.asyncio
    async def test_publish_task_parsing_error(self):
        """Test publish_task handles parsing errors."""
        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock(side_effect=Exception("Parsing error"))
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        event = EventEnvelope(topic="test.topic", payload=PayloadBase(content="test"))

        with pytest.raises(Exception, match="Parsing error"):
            await sdk.publish_task(event)

    @pytest.mark.asyncio
    async def test_publish_task_minimal_fields(self):
        """Test publish_task with minimal required fields."""
        mock_bus = AsyncMock()
        mock_bus.publish = AsyncMock(return_value="task-123")
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Minimal event - only topic and content
        event = EventEnvelope(
            topic="test.topic", payload=PayloadBase(content="minimal content")
        )

        task_id = await sdk.publish_task(event)

        assert task_id == "task-123"
        call_args = mock_bus.publish.call_args
        published_event = call_args[1]["event_payload"]
        assert published_event["topic"] == "test.topic"
        assert published_event["payload"]["content"] == "minimal content"


class TestOmniDaemonSDKRegisterAgent:
    """Test suite for OmniDaemonSDK register_agent operations."""

    @pytest.mark.asyncio
    async def test_register_agent_success(self):
        """Test successful agent registration."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.register_handler = AsyncMock()

        async def callback(msg):
            return "result"

        agent_config = AgentConfig(
            name="test-agent", topic="test.topic", callback=callback
        )

        await sdk.register_agent(agent_config)

        sdk.runner.register_handler.assert_called_once()
        call_args = sdk.runner.register_handler.call_args
        assert call_args[1]["topic"] == "test.topic"
        subscription = call_args[1]["subscription"]
        assert subscription["name"] == "test-agent"
        assert subscription["callback"] == callback
        assert subscription["callback_name"] == callback.__name__

    @pytest.mark.asyncio
    async def test_register_agent_with_tools(self):
        """Test register_agent with tools."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.register_handler = AsyncMock()

        async def callback(msg):
            return "result"

        agent_config = AgentConfig(
            name="test-agent",
            topic="test.topic",
            callback=callback,
            tools=["tool1", "tool2", "tool3"],
        )

        await sdk.register_agent(agent_config)

        call_args = sdk.runner.register_handler.call_args
        subscription = call_args[1]["subscription"]
        assert subscription["tools"] == ["tool1", "tool2", "tool3"]

    @pytest.mark.asyncio
    async def test_register_agent_with_description(self):
        """Test register_agent with description."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.register_handler = AsyncMock()

        async def callback(msg):
            return "result"

        agent_config = AgentConfig(
            name="test-agent",
            topic="test.topic",
            callback=callback,
            description="Test agent description",
        )

        await sdk.register_agent(agent_config)

        call_args = sdk.runner.register_handler.call_args
        subscription = call_args[1]["subscription"]
        assert subscription["description"] == "Test agent description"

    @pytest.mark.asyncio
    async def test_register_agent_with_config(self):
        """Test register_agent with SubscriptionConfig."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.register_handler = AsyncMock()

        async def callback(msg):
            return "result"

        sub_config = SubscriptionConfig(
            reclaim_idle_ms=300000, dlq_retry_limit=5, consumer_count=3
        )

        agent_config = AgentConfig(
            name="test-agent", topic="test.topic", callback=callback, config=sub_config
        )

        await sdk.register_agent(agent_config)

        call_args = sdk.runner.register_handler.call_args
        subscription = call_args[1]["subscription"]
        config = subscription["config"]
        assert config["reclaim_idle_ms"] == 300000
        assert config["dlq_retry_limit"] == 5
        assert config["consumer_count"] == 3

    @pytest.mark.asyncio
    async def test_register_agent_validation_error(self):
        """Test register_agent handles ValidationError."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Create invalid agent config (missing required topic)
        with pytest.raises(ValidationError):
            agent_config = AgentConfig(
                name="test-agent",
                # Missing topic
                callback=lambda x: x,
            )
            await sdk.register_agent(agent_config)

    @pytest.mark.asyncio
    async def test_register_agent_error_handling(self):
        """Test register_agent error handling."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.register_handler = AsyncMock(
            side_effect=Exception("Registration error")
        )

        async def callback(msg):
            return "result"

        agent_config = AgentConfig(
            name="test-agent", topic="test.topic", callback=callback
        )

        with pytest.raises(Exception, match="Registration error"):
            await sdk.register_agent(agent_config)


class TestOmniDaemonSDKListAgents:
    """Test suite for OmniDaemonSDK list_agents operations."""

    @pytest.mark.asyncio
    async def test_list_agents_success(self):
        """Test successful agent listing."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(
            return_value={
                "topic1": [
                    {
                        "name": "agent1",
                        "tools": ["tool1"],
                        "description": "Agent 1",
                        "callback_name": "callback1",
                        "config": {},
                    }
                ],
                "topic2": [
                    {
                        "name": "agent2",
                        "tools": [],
                        "description": "Agent 2",
                        "callback_name": "callback2",
                        "config": {"consumer_count": 2},
                    }
                ],
            }
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        agents = await sdk.list_agents()

        assert "topic1" in agents
        assert "topic2" in agents
        assert len(agents["topic1"]) == 1
        assert len(agents["topic2"]) == 1
        assert agents["topic1"][0]["name"] == "agent1"
        assert agents["topic2"][0]["name"] == "agent2"

    @pytest.mark.asyncio
    async def test_list_agents_empty(self):
        """Test list_agents with no agents."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(return_value={})

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        agents = await sdk.list_agents()

        assert agents == {}

    @pytest.mark.asyncio
    async def test_list_agents_grouped_by_topic(self):
        """Test list_agents groups by topic."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(
            return_value={
                "topic1": [
                    {
                        "name": "agent1",
                        "callback_name": "cb1",
                        "tools": [],
                        "description": "",
                        "config": {},
                    },
                    {
                        "name": "agent2",
                        "callback_name": "cb2",
                        "tools": [],
                        "description": "",
                        "config": {},
                    },
                ],
                "topic2": [
                    {
                        "name": "agent3",
                        "callback_name": "cb3",
                        "tools": [],
                        "description": "",
                        "config": {},
                    }
                ],
            }
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        agents = await sdk.list_agents()

        assert "topic1" in agents
        assert "topic2" in agents
        assert len(agents["topic1"]) == 2
        assert len(agents["topic2"]) == 1

    @pytest.mark.asyncio
    async def test_list_agents_includes_metadata(self):
        """Test list_agents includes all metadata."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(
            return_value={
                "test.topic": [
                    {
                        "name": "test-agent",
                        "tools": ["tool1", "tool2"],
                        "description": "Test description",
                        "callback_name": "test_callback",
                        "config": {"consumer_count": 2},
                    }
                ]
            }
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        agents = await sdk.list_agents()

        agent = agents["test.topic"][0]
        assert agent["name"] == "test-agent"
        assert agent["tools"] == ["tool1", "tool2"]
        assert agent["description"] == "Test description"
        assert agent["callback"] == "test_callback"
        assert agent["config"] == {"consumer_count": 2}


class TestOmniDaemonSDKGetAgent:
    """Test suite for OmniDaemonSDK get_agent operations."""

    @pytest.mark.asyncio
    async def test_get_agent_success(self):
        """Test successful agent retrieval."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_agent = AsyncMock(
            return_value={
                "name": "test-agent",
                "topic": "test.topic",
                "callback_name": "test_callback",
                "tools": ["tool1"],
                "description": "Test agent",
            }
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        agent = await sdk.get_agent("test.topic", "test-agent")

        assert agent is not None
        assert agent["name"] == "test-agent"
        assert agent["callback"] == "test_callback"
        mock_store.get_agent.assert_called_once_with("test.topic", "test-agent")

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self):
        """Test get_agent returns None if not found."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_agent = AsyncMock(return_value=None)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        agent = await sdk.get_agent("test.topic", "nonexistent-agent")

        assert agent is None

    @pytest.mark.asyncio
    async def test_get_agent_includes_callback_name(self):
        """Test get_agent includes callback_name."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_agent = AsyncMock(
            return_value={
                "name": "test-agent",
                "callback_name": "my_callback",
                "tools": [],
                "description": "",
            }
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        agent = await sdk.get_agent("test.topic", "test-agent")

        assert agent["callback"] == "my_callback"


class TestOmniDaemonSDKUnsubscribeAgent:
    """Test suite for OmniDaemonSDK unsubscribe_agent operations."""

    @pytest.mark.asyncio
    async def test_unsubscribe_agent_success(self):
        """Test successful agent unsubscribe."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        result = await sdk.unsubscribe_agent("test.topic", "test-agent")

        assert result is True
        mock_bus.unsubscribe.assert_called_once_with(
            topic="test.topic",
            agent_name="test-agent",
            delete_group=False,
            delete_dlq=False,
        )

    @pytest.mark.asyncio
    async def test_unsubscribe_agent_not_found(self):
        """Test unsubscribe_agent handles not found."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock(side_effect=Exception("Agent not found"))

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        result = await sdk.unsubscribe_agent("test.topic", "nonexistent-agent")

        assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_agent_preserves_group(self):
        """Test unsubscribe_agent preserves group."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.unsubscribe_agent("test.topic", "test-agent")

        call_args = mock_bus.unsubscribe.call_args
        assert call_args[1]["delete_group"] is False

    @pytest.mark.asyncio
    async def test_unsubscribe_agent_preserves_dlq(self):
        """Test unsubscribe_agent preserves DLQ."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.unsubscribe_agent("test.topic", "test-agent")

        call_args = mock_bus.unsubscribe.call_args
        assert call_args[1]["delete_dlq"] is False


class TestOmniDaemonSDKDeleteAgent:
    """Test suite for OmniDaemonSDK delete_agent operations."""

    @pytest.mark.asyncio
    async def test_delete_agent_success(self):
        """Test successful agent deletion."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock()
        mock_store.delete_agent = AsyncMock(return_value=True)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        result = await sdk.delete_agent("test.topic", "test-agent")

        assert result is True
        mock_bus.unsubscribe.assert_called_once()
        mock_store.delete_agent.assert_called_once_with("test.topic", "test-agent")

    @pytest.mark.asyncio
    async def test_delete_agent_deletes_group(self):
        """Test delete_agent deletes group by default."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock()
        mock_store.delete_agent = AsyncMock(return_value=True)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.delete_agent("test.topic", "test-agent")

        call_args = mock_bus.unsubscribe.call_args
        assert call_args[1]["delete_group"] is True

    @pytest.mark.asyncio
    async def test_delete_agent_preserves_group(self):
        """Test delete_agent preserves group when requested."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock()
        mock_store.delete_agent = AsyncMock(return_value=True)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.delete_agent("test.topic", "test-agent", delete_group=False)

        call_args = mock_bus.unsubscribe.call_args
        assert call_args[1]["delete_group"] is False

    @pytest.mark.asyncio
    async def test_delete_agent_deletes_dlq(self):
        """Test delete_agent deletes DLQ when requested."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock()
        mock_store.delete_agent = AsyncMock(return_value=True)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.delete_agent("test.topic", "test-agent", delete_dlq=True)

        call_args = mock_bus.unsubscribe.call_args
        assert call_args[1]["delete_dlq"] is True

    @pytest.mark.asyncio
    async def test_delete_agent_preserves_dlq(self):
        """Test delete_agent preserves DLQ by default."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock()
        mock_store.delete_agent = AsyncMock(return_value=True)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.delete_agent("test.topic", "test-agent")

        call_args = mock_bus.unsubscribe.call_args
        assert call_args[1]["delete_dlq"] is False

    @pytest.mark.asyncio
    async def test_delete_agent_removes_from_storage(self):
        """Test delete_agent removes from storage."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock()
        mock_store.delete_agent = AsyncMock(return_value=True)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.delete_agent("test.topic", "test-agent")

        mock_store.delete_agent.assert_called_once_with("test.topic", "test-agent")

    @pytest.mark.asyncio
    async def test_delete_agent_not_found(self):
        """Test delete_agent handles not found."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock()
        mock_store.delete_agent = AsyncMock(return_value=False)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        result = await sdk.delete_agent("test.topic", "nonexistent-agent")

        assert result is False


class TestOmniDaemonSDKDeleteTopic:
    """Test suite for OmniDaemonSDK delete_topic operations."""

    @pytest.mark.asyncio
    async def test_delete_topic_success(self):
        """Test successful topic deletion."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.delete_topic = AsyncMock(return_value=3)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        count = await sdk.delete_topic("test.topic")

        assert count == 3
        mock_store.delete_topic.assert_called_once_with("test.topic")

    @pytest.mark.asyncio
    async def test_delete_topic_returns_count(self):
        """Test delete_topic returns agent count."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.delete_topic = AsyncMock(return_value=5)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        count = await sdk.delete_topic("test.topic")

        assert count == 5

    @pytest.mark.asyncio
    async def test_delete_topic_empty(self):
        """Test delete_topic with no agents."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.delete_topic = AsyncMock(return_value=0)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        count = await sdk.delete_topic("empty.topic")

        assert count == 0


class TestOmniDaemonSDKHealth:
    """Test suite for OmniDaemonSDK health operations."""

    @pytest.mark.asyncio
    async def test_health_running(self):
        """Test health returns 'running' status."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(
            return_value={"topic1": [{"name": "agent1"}]}
        )
        mock_store.get_config = AsyncMock(
            side_effect=lambda key, default=None: {
                "_omnidaemon_start_time": time.time(),
                "_omnidaemon_runner_id": "runner-123",
            }.get(key, default)
        )
        mock_store.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_bus.get_consumers = AsyncMock(return_value={})

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner._running = True
        sdk.runner.event_bus = mock_bus

        health = await sdk.health()

        assert health["status"] == "running"
        assert health["runner_id"] == "runner-123"

    @pytest.mark.asyncio
    async def test_health_stopped(self):
        """Test health returns 'stopped' status."""
        mock_bus = AsyncMock()
        mock_bus.get_consumers = AsyncMock(return_value={})
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(
            return_value={"topic1": [{"name": "agent1"}]}
        )
        mock_store.get_config = AsyncMock(
            side_effect=lambda key, default=None: {
                "_omnidaemon_start_time": None,
                "_omnidaemon_runner_id": None,
            }.get(key, default)
        )
        mock_store.health_check = AsyncMock(return_value={"status": "healthy"})

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus

        health = await sdk.health()

        assert health["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_health_ready(self):
        """Test health returns 'ready' status."""
        mock_bus = AsyncMock()
        mock_bus.get_consumers = AsyncMock(return_value={})
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(return_value={})
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.health_check = AsyncMock(return_value={"status": "healthy"})

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus

        health = await sdk.health()

        assert health["status"] == "ready"

    @pytest.mark.asyncio
    async def test_health_degraded(self):
        """Test health returns 'degraded' status."""
        mock_bus = AsyncMock()
        mock_bus.get_consumers = AsyncMock(return_value={})
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(return_value={})
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.health_check = AsyncMock(return_value={"status": "unhealthy"})

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus  # Connected but storage unhealthy

        health = await sdk.health()

        assert health["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_health_down(self):
        """Test health returns 'down' status."""
        mock_bus = AsyncMock()
        mock_bus.get_consumers = AsyncMock(return_value={})
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(return_value={})
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.health_check = AsyncMock(side_effect=Exception("Storage error"))

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = None

        health = await sdk.health()

        assert health["status"] == "down"

    @pytest.mark.asyncio
    async def test_health_includes_runner_id(self):
        """Test health includes runner_id."""
        mock_bus = AsyncMock()
        mock_bus.get_consumers = AsyncMock(return_value={})
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(return_value={})
        mock_store.get_config = AsyncMock(
            side_effect=lambda key, default=None: {
                "_omnidaemon_runner_id": "custom-runner-456"
            }.get(key, default)
        )
        mock_store.health_check = AsyncMock(return_value={"status": "healthy"})

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus

        health = await sdk.health()

        assert health["runner_id"] == "custom-runner-456"

    @pytest.mark.asyncio
    async def test_health_includes_event_bus_info(self):
        """Test health includes event bus info."""
        mock_bus = AsyncMock()
        mock_bus.__class__.__name__ = "RedisStreamEventBus"
        mock_bus.get_consumers = AsyncMock(return_value={})
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(return_value={})
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.health_check = AsyncMock(return_value={"status": "healthy"})

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus

        health = await sdk.health()

        assert health["event_bus_type"] == "RedisStreamEventBus"
        assert health["event_bus_connected"] is True

    @pytest.mark.asyncio
    async def test_health_includes_storage_info(self):
        """Test health includes storage info."""
        mock_bus = AsyncMock()
        mock_bus.get_consumers = AsyncMock(return_value={})
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(return_value={})
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.health_check = AsyncMock(
            return_value={"status": "healthy", "backend": "redis", "latency_ms": 5}
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus

        health = await sdk.health()

        assert health["storage_healthy"] is True
        assert health["storage_status"]["status"] == "healthy"
        assert health["storage_status"]["backend"] == "redis"

    @pytest.mark.asyncio
    async def test_health_includes_agents(self):
        """Test health includes agent list."""
        mock_bus = AsyncMock()
        mock_bus.get_consumers = AsyncMock(return_value={})
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(
            return_value={
                "topic1": [
                    {
                        "name": "agent1",
                        "callback_name": "cb1",
                        "tools": [],
                        "description": "",
                        "config": {},
                    }
                ]
            }
        )
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.health_check = AsyncMock(return_value={"status": "healthy"})

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus

        health = await sdk.health()

        assert "agents" in health
        assert "topic1" in health["agents"]
        assert len(health["agents"]["topic1"]) == 1

    @pytest.mark.asyncio
    async def test_health_includes_uptime(self):
        """Test health includes uptime calculation."""
        start_time = time.time() - 100  # 100 seconds ago
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(
            return_value={"topic1": [{"name": "agent1"}]}
        )
        mock_store.get_config = AsyncMock(
            side_effect=lambda key, default=None: {
                "_omnidaemon_start_time": start_time,
                "_omnidaemon_runner_id": "runner-123",
            }.get(key, default)
        )
        mock_store.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_bus.get_consumers = AsyncMock(
            return_value={"group1": {"consumers_count": 1}}
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus

        health = await sdk.health()

        assert health["uptime_seconds"] >= 100
        assert health["uptime_seconds"] < 110  # Allow some margin

    @pytest.mark.asyncio
    async def test_health_includes_active_consumers(self):
        """Test health includes active consumers."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(
            return_value={"topic1": [{"name": "agent1"}]}
        )
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_bus.get_consumers = AsyncMock(
            return_value={
                "group:topic1:agent1": {
                    "consumers_count": 2,
                    "topic": "topic1",
                    "agent_name": "agent1",
                }
            }
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus

        health = await sdk.health()

        assert health["has_active_consumers"] is True
        assert "active_consumers" in health

    @pytest.mark.asyncio
    async def test_health_handles_storage_error(self):
        """Test health handles storage errors."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(side_effect=Exception("Storage error"))
        mock_store.get_config = AsyncMock(return_value=None)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Should not raise, but handle gracefully
        with pytest.raises(Exception):
            await sdk.health()


class TestOmniDaemonSDKResultManagement:
    """Test suite for OmniDaemonSDK result management operations."""

    @pytest.mark.asyncio
    async def test_get_result_success(self):
        """Test successful result retrieval."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_result = AsyncMock(
            return_value={
                "task_id": "task-123",
                "result": "processing_result",
                "status": "completed",
            }
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        result = await sdk.get_result("task-123")

        assert result is not None
        assert result["task_id"] == "task-123"
        mock_store.get_result.assert_called_once_with("task-123")

    @pytest.mark.asyncio
    async def test_get_result_not_found(self):
        """Test get_result returns None if not found."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_result = AsyncMock(return_value=None)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        result = await sdk.get_result("nonexistent-task")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_results_success(self):
        """Test successful result listing."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_results = AsyncMock(
            return_value=[
                {"task_id": "task-1", "result": "result1"},
                {"task_id": "task-2", "result": "result2"},
            ]
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        results = await sdk.list_results()

        assert len(results) == 2
        mock_store.list_results.assert_called_once_with(limit=100)

    @pytest.mark.asyncio
    async def test_list_results_with_limit(self):
        """Test list_results respects limit."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_results = AsyncMock(return_value=[])

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.list_results(limit=50)

        mock_store.list_results.assert_called_once_with(limit=50)

    @pytest.mark.asyncio
    async def test_list_results_empty(self):
        """Test list_results with no results."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_results = AsyncMock(return_value=[])

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        results = await sdk.list_results()

        assert results == []

    @pytest.mark.asyncio
    async def test_delete_result_success(self):
        """Test successful result deletion."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.delete_result = AsyncMock(return_value=True)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        result = await sdk.delete_result("task-123")

        assert result is True
        mock_store.delete_result.assert_called_once_with("task-123")

    @pytest.mark.asyncio
    async def test_delete_result_not_found(self):
        """Test delete_result handles not found."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.delete_result = AsyncMock(return_value=False)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        result = await sdk.delete_result("nonexistent-task")

        assert result is False


class TestOmniDaemonSDKStartStopShutdown:
    """Test suite for OmniDaemonSDK start/stop/shutdown operations."""

    @pytest.mark.asyncio
    async def test_start_success(self):
        """Test successful SDK start."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.start = AsyncMock()

        await sdk.start()

        assert sdk._is_running is True
        assert sdk._start_time is not None
        sdk.runner.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_sets_start_time(self):
        """Test start sets _start_time."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.start = AsyncMock()

        before_time = time.time()
        await sdk.start()
        after_time = time.time()

        assert sdk._start_time is not None
        assert before_time <= sdk._start_time <= after_time

    @pytest.mark.asyncio
    async def test_start_sets_is_running(self):
        """Test start sets _is_running flag."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.start = AsyncMock()

        assert sdk._is_running is False
        await sdk.start()
        assert sdk._is_running is True

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        """Test multiple start() calls are safe."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.start = AsyncMock()

        await sdk.start()
        first_start_time = sdk._start_time

        await sdk.start()

        # Should not change start time on second call
        assert sdk._start_time == first_start_time
        assert sdk._is_running is True

    @pytest.mark.asyncio
    async def test_stop_success(self):
        """Test successful SDK stop."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.stop = AsyncMock()
        sdk._is_running = True

        await sdk.stop()

        assert sdk._is_running is False
        sdk.runner.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_clears_is_running(self):
        """Test stop clears _is_running flag."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.stop = AsyncMock()
        sdk._is_running = True

        await sdk.stop()

        assert sdk._is_running is False

    @pytest.mark.asyncio
    async def test_shutdown_success(self):
        """Test successful shutdown."""
        mock_bus = AsyncMock()
        mock_bus.close = AsyncMock()
        mock_store = AsyncMock()
        mock_store.close = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.stop = AsyncMock()
        sdk._is_running = True

        await sdk.shutdown()

        assert sdk._is_running is False
        sdk.runner.stop.assert_called_once()
        mock_bus.close.assert_called_once()
        mock_store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_event_bus(self):
        """Test shutdown closes event bus."""
        mock_bus = AsyncMock()
        mock_bus.close = AsyncMock()
        mock_store = AsyncMock()
        mock_store.close = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.stop = AsyncMock()

        await sdk.shutdown()

        mock_bus.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_closes_storage(self):
        """Test shutdown closes storage."""
        mock_bus = AsyncMock()
        mock_bus.close = AsyncMock()
        mock_store = AsyncMock()
        mock_store.close = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.stop = AsyncMock()

        await sdk.shutdown()

        mock_store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown_handles_errors(self):
        """Test shutdown handles errors gracefully."""
        mock_bus = AsyncMock()
        mock_bus.close = AsyncMock(side_effect=Exception("Bus close error"))
        mock_store = AsyncMock()
        mock_store.close = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.stop = AsyncMock(side_effect=Exception("Stop error"))

        # Should not raise, but handle errors gracefully
        await sdk.shutdown()

        # Should still try to close storage
        mock_store.close.assert_called_once()
        assert sdk._is_running is False


class TestOmniDaemonSDKMetrics:
    """Test suite for OmniDaemonSDK metrics operations."""

    @pytest.mark.asyncio
    async def test_metrics_success(self):
        """Test successful metrics retrieval."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_metrics = AsyncMock(
            return_value=[
                {
                    "topic": "test.topic",
                    "agent": "agent1",
                    "event": "task_received",
                    "timestamp": time.time(),
                },
                {
                    "topic": "test.topic",
                    "agent": "agent1",
                    "event": "task_processed",
                    "processing_time_sec": 0.5,
                    "timestamp": time.time(),
                },
                {
                    "topic": "test.topic",
                    "agent": "agent1",
                    "event": "task_failed",
                    "error": "Test error",
                    "timestamp": time.time(),
                },
            ]
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        metrics = await sdk.metrics()

        assert "test.topic" in metrics
        assert "agent1" in metrics["test.topic"]
        stats = metrics["test.topic"]["agent1"]
        assert stats["tasks_received"] == 1
        assert stats["tasks_processed"] == 1
        assert stats["tasks_failed"] == 1

    @pytest.mark.asyncio
    async def test_metrics_with_topic_filter(self):
        """Test metrics with topic filter."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_metrics = AsyncMock(return_value=[])

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.metrics(topic="test.topic")

        mock_store.get_metrics.assert_called_once_with(topic="test.topic", limit=1000)

    @pytest.mark.asyncio
    async def test_metrics_with_limit(self):
        """Test metrics respects limit."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_metrics = AsyncMock(return_value=[])

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.metrics(limit=500)

        mock_store.get_metrics.assert_called_once_with(topic=None, limit=500)

    @pytest.mark.asyncio
    async def test_metrics_aggregates_by_topic_agent(self):
        """Test metrics aggregates correctly."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_metrics = AsyncMock(
            return_value=[
                {
                    "topic": "topic1",
                    "agent": "agent1",
                    "event": "task_received",
                    "timestamp": time.time(),
                },
                {
                    "topic": "topic1",
                    "agent": "agent2",
                    "event": "task_received",
                    "timestamp": time.time(),
                },
                {
                    "topic": "topic2",
                    "agent": "agent1",
                    "event": "task_received",
                    "timestamp": time.time(),
                },
            ]
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        metrics = await sdk.metrics()

        assert "topic1" in metrics
        assert "topic2" in metrics
        assert "agent1" in metrics["topic1"]
        assert "agent2" in metrics["topic1"]
        assert "agent1" in metrics["topic2"]

    @pytest.mark.asyncio
    async def test_metrics_calculates_avg_time(self):
        """Test metrics calculates average processing time."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_metrics = AsyncMock(
            return_value=[
                {
                    "topic": "test.topic",
                    "agent": "agent1",
                    "event": "task_processed",
                    "processing_time_sec": 1.0,
                    "timestamp": time.time(),
                },
                {
                    "topic": "test.topic",
                    "agent": "agent1",
                    "event": "task_processed",
                    "processing_time_sec": 2.0,
                    "timestamp": time.time(),
                },
                {
                    "topic": "test.topic",
                    "agent": "agent1",
                    "event": "task_processed",
                    "processing_time_sec": 3.0,
                    "timestamp": time.time(),
                },
            ]
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        metrics = await sdk.metrics()

        stats = metrics["test.topic"]["agent1"]
        assert stats["tasks_processed"] == 3
        assert stats["avg_processing_time_sec"] == 2.0  # (1+2+3)/3 = 2.0
        assert stats["total_processing_time"] == 6.0

    @pytest.mark.asyncio
    async def test_metrics_empty(self):
        """Test metrics with no data."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_metrics = AsyncMock(return_value=[])

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        metrics = await sdk.metrics()

        assert metrics == {}


class TestOmniDaemonSDKClearOperations:
    """Test suite for OmniDaemonSDK clear operations."""

    @pytest.mark.asyncio
    async def test_clear_agents_success(self):
        """Test successful agent clearing."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.clear_agents = AsyncMock(return_value=5)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        count = await sdk.clear_agents()

        assert count == 5
        mock_store.clear_agents.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_agents_returns_count(self):
        """Test clear_agents returns count."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.clear_agents = AsyncMock(return_value=10)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        count = await sdk.clear_agents()

        assert count == 10

    @pytest.mark.asyncio
    async def test_clear_results_success(self):
        """Test successful result clearing."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.clear_results = AsyncMock(return_value=20)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        count = await sdk.clear_results()

        assert count == 20
        mock_store.clear_results.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_results_returns_count(self):
        """Test clear_results returns count."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.clear_results = AsyncMock(return_value=15)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        count = await sdk.clear_results()

        assert count == 15

    @pytest.mark.asyncio
    async def test_clear_metrics_success(self):
        """Test successful metrics clearing."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.clear_metrics = AsyncMock(return_value=100)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        count = await sdk.clear_metrics()

        assert count == 100
        mock_store.clear_metrics.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_metrics_returns_count(self):
        """Test clear_metrics returns count."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.clear_metrics = AsyncMock(return_value=50)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        count = await sdk.clear_metrics()

        assert count == 50

    @pytest.mark.asyncio
    async def test_clear_all_success(self):
        """Test successful clear_all."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.clear_all = AsyncMock(
            return_value={"agents": 5, "results": 10, "metrics": 20}
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        counts = await sdk.clear_all()

        assert counts["agents"] == 5
        assert counts["results"] == 10
        assert counts["metrics"] == 20
        mock_store.clear_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_all_returns_counts(self):
        """Test clear_all returns all counts."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.clear_all = AsyncMock(
            return_value={"agents": 3, "results": 7, "metrics": 15, "config": 2}
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        counts = await sdk.clear_all()

        assert len(counts) == 4
        assert counts["agents"] == 3
        assert counts["results"] == 7
        assert counts["metrics"] == 15
        assert counts["config"] == 2


class TestOmniDaemonSDKConfig:
    """Test suite for OmniDaemonSDK config operations."""

    @pytest.mark.asyncio
    async def test_save_config_success(self):
        """Test successful config save."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_config = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.save_config("test_key", "test_value")

        mock_store.save_config.assert_called_once_with("test_key", "test_value")

    @pytest.mark.asyncio
    async def test_get_config_success(self):
        """Test successful config retrieval."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_config = AsyncMock(return_value="config_value")

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        value = await sdk.get_config("test_key")

        assert value == "config_value"
        mock_store.get_config.assert_called_once_with("test_key", None)

    @pytest.mark.asyncio
    async def test_get_config_default(self):
        """Test get_config returns default if not found."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_config = AsyncMock(return_value="default_value")

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        value = await sdk.get_config("nonexistent_key", default="default_value")

        assert value == "default_value"
        mock_store.get_config.assert_called_once_with(
            "nonexistent_key", "default_value"
        )

    @pytest.mark.asyncio
    async def test_get_config_not_found(self):
        """Test get_config returns None if not found and no default."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_config = AsyncMock(return_value=None)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        value = await sdk.get_config("nonexistent_key")

        assert value is None


class TestOmniDaemonSDKStorageHealth:
    """Test suite for OmniDaemonSDK storage health operations."""

    @pytest.mark.asyncio
    async def test_storage_health_success(self):
        """Test successful storage health check."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.health_check = AsyncMock(
            return_value={"status": "healthy", "backend": "redis", "latency_ms": 5}
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        health = await sdk.storage_health()

        assert health["status"] == "healthy"
        assert health["backend"] == "redis"
        mock_store.health_check.assert_called_once()

    @pytest.mark.asyncio
    async def test_storage_health_includes_status(self):
        """Test storage_health includes status."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.health_check = AsyncMock(
            return_value={"status": "degraded", "error": "High latency"}
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        health = await sdk.storage_health()

        assert health["status"] == "degraded"
        assert "error" in health


class TestOmniDaemonSDKStreamMonitoring:
    """Test suite for OmniDaemonSDK stream monitoring operations (Redis only)."""

    @pytest.mark.asyncio
    async def test_list_streams_success(self):
        """Test successful stream listing."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(
            return_value=[b"omni-stream:topic1", b"omni-stream:topic2"]
        )
        mock_redis.xlen = AsyncMock(side_effect=[10, 20])
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        streams = await sdk.list_streams()

        assert len(streams) == 2
        assert streams[0]["stream"] == "omni-stream:topic1"
        assert streams[0]["length"] == 10
        assert streams[1]["stream"] == "omni-stream:topic2"
        assert streams[1]["length"] == 20

    @pytest.mark.asyncio
    async def test_list_streams_not_redis(self):
        """Test list_streams raises error for non-Redis bus."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        # Remove _redis attribute
        del mock_bus._redis

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        with pytest.raises(
            ValueError, match="Event bus monitoring only works with Redis Streams"
        ):
            await sdk.list_streams()

    @pytest.mark.asyncio
    async def test_inspect_stream_success(self):
        """Test successful stream inspection."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xrevrange = AsyncMock(
            return_value=[
                (b"123-0", {b"data": b'{"content": "test1"}'}),
                (b"124-0", {b"data": b'{"content": "test2"}'}),
            ]
        )
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        messages = await sdk.inspect_stream("test.topic", limit=10)

        assert len(messages) == 2
        assert messages[0]["id"] == "123-0"
        assert messages[0]["data"]["content"] == "test1"

    @pytest.mark.asyncio
    async def test_inspect_stream_with_limit(self):
        """Test inspect_stream respects limit."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xrevrange = AsyncMock(return_value=[])
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        await sdk.inspect_stream("test.topic", limit=5)

        mock_redis.xrevrange.assert_called_once()
        call_args = mock_redis.xrevrange.call_args
        assert call_args[1]["count"] == 5

    @pytest.mark.asyncio
    async def test_inspect_stream_handles_prefix(self):
        """Test inspect_stream handles omni-stream: prefix."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xrevrange = AsyncMock(return_value=[])
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Test with prefix
        await sdk.inspect_stream("omni-stream:test.topic")

        call_args = mock_redis.xrevrange.call_args
        assert call_args[0][0] == "omni-stream:test.topic"

        # Test without prefix
        await sdk.inspect_stream("test.topic")

        call_args = mock_redis.xrevrange.call_args
        assert call_args[0][0] == "omni-stream:test.topic"

    @pytest.mark.asyncio
    async def test_list_groups_success(self):
        """Test successful group listing."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xinfo_groups = AsyncMock(
            return_value=[
                {
                    "name": b"group1",
                    "consumers": 2,
                    "pending": 5,
                    "last-delivered-id": b"123-0",
                }
            ]
        )
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        groups = await sdk.list_groups("test.topic")

        assert len(groups) == 1
        assert groups[0]["name"] == "group1"
        assert groups[0]["consumers"] == 2
        assert groups[0]["pending"] == 5

    @pytest.mark.asyncio
    async def test_list_groups_not_redis(self):
        """Test list_groups raises error for non-Redis bus."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        del mock_bus._redis

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        with pytest.raises(
            ValueError, match="Event bus monitoring only works with Redis Streams"
        ):
            await sdk.list_groups("test.topic")

    @pytest.mark.asyncio
    async def test_inspect_dlq_success(self):
        """Test successful DLQ inspection."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[b"omni-dlq:group:test.topic:agent1"])
        mock_redis.xrevrange = AsyncMock(return_value=[(b"123-0", {"data": "test"})])
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        messages = await sdk.inspect_dlq("test.topic")

        assert len(messages) == 1
        assert messages[0]["id"] == "123-0"

    @pytest.mark.asyncio
    async def test_inspect_dlq_empty(self):
        """Test inspect_dlq with empty DLQ."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        messages = await sdk.inspect_dlq("test.topic")

        assert messages == []

    @pytest.mark.asyncio
    async def test_inspect_dlq_not_redis(self):
        """Test inspect_dlq raises error for non-Redis bus."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        del mock_bus._redis

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        with pytest.raises(
            ValueError, match="Event bus monitoring only works with Redis Streams"
        ):
            await sdk.inspect_dlq("test.topic")

    @pytest.mark.asyncio
    async def test_get_bus_stats_success(self):
        """Test successful bus stats retrieval."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[b"omni-stream:topic1"])
        mock_redis.xlen = AsyncMock(return_value=10)
        mock_redis.xinfo_groups = AsyncMock(return_value=[])
        mock_redis.info = AsyncMock(return_value={"used_memory_human": "1.5M"})
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        stats = await sdk.get_bus_stats()

        assert "snapshot" in stats
        assert "redis_info" in stats
        assert "topic1" in stats["snapshot"]["topics"]
        assert stats["redis_info"]["used_memory_human"] == "1.5M"

    @pytest.mark.asyncio
    async def test_get_bus_stats_not_redis(self):
        """Test get_bus_stats raises error for non-Redis bus."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        del mock_bus._redis

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        with pytest.raises(
            ValueError, match="Event bus monitoring only works with Redis Streams"
        ):
            await sdk.get_bus_stats()

    @pytest.mark.asyncio
    async def test_get_bus_stats_includes_redis_info(self):
        """Test get_bus_stats includes Redis info."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_redis.info = AsyncMock(return_value={"used_memory_human": "2.3M"})
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        stats = await sdk.get_bus_stats()

        assert "redis_info" in stats
        assert stats["redis_info"]["used_memory_human"] == "2.3M"


class TestOmniDaemonSDKEdgeCases:
    """Test suite for OmniDaemonSDK edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_publish_task_validation_error_logs(self):
        """Test publish_task logs ValidationError (lines 112-113)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Create invalid event that will raise ValidationError
        with pytest.raises(ValidationError):
            # Missing required topic
            event = EventEnvelope(payload=PayloadBase(content="test"))
            await sdk.publish_task(event)

    @pytest.mark.asyncio
    async def test_register_agent_with_none_config(self):
        """Test register_agent with config=None (line 147)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.register_handler = AsyncMock()

        async def callback(msg):
            return "result"

        agent_config = AgentConfig(
            name="test-agent", topic="test.topic", callback=callback, config=None
        )

        await sdk.register_agent(agent_config)

        call_args = sdk.runner.register_handler.call_args
        subscription = call_args[1]["subscription"]
        assert subscription["config"] == {}  # Should be empty dict when config is None

    @pytest.mark.asyncio
    async def test_register_agent_validation_error_logs(self):
        """Test register_agent logs ValidationError (lines 164-165)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Create invalid agent config that will raise ValidationError
        with pytest.raises(ValidationError):
            agent_config = AgentConfig(
                name="test-agent",
                # Missing required topic
                callback=lambda x: x,
            )
            await sdk.register_agent(agent_config)

    @pytest.mark.asyncio
    async def test_delete_agent_handles_unsubscribe_error(self):
        """Test delete_agent handles unsubscribe exception (lines 276-277)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_bus.unsubscribe = AsyncMock(side_effect=Exception("Unsubscribe failed"))
        mock_store.delete_agent = AsyncMock(return_value=True)

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Should not raise, but continue to delete from storage
        result = await sdk.delete_agent("test.topic", "test-agent")

        assert result is True
        mock_store.delete_agent.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_handles_get_consumers_exception(self):
        """Test health handles get_consumers exception (lines 353-358)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(return_value={})
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.health_check = AsyncMock(return_value={"status": "healthy"})
        mock_bus.get_consumers = AsyncMock(
            side_effect=Exception("Get consumers failed")
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus

        # Should not raise, but handle gracefully
        health = await sdk.health()

        assert health["has_active_consumers"] is False

    @pytest.mark.asyncio
    async def test_health_checks_task_in_consumers(self):
        """Test health checks task in consumers (lines 352-356)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(return_value={})
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.health_check = AsyncMock(return_value={"status": "healthy"})
        # Return consumers with task but no consumers_count
        mock_bus.get_consumers = AsyncMock(
            return_value={
                "group1": {"task": "some_task", "consumers_count": 0},
                "group2": {"consumers_count": 0},
            }
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.event_bus = mock_bus

        health = await sdk.health()

        # Should detect active consumers via task field
        assert health["has_active_consumers"] is True

    @pytest.mark.asyncio
    async def test_shutdown_handles_store_close_error(self):
        """Test shutdown handles store.close exception (lines 487-488)."""
        mock_bus = AsyncMock()
        mock_bus.close = AsyncMock()
        mock_store = AsyncMock()
        mock_store.close = AsyncMock(side_effect=Exception("Store close failed"))
        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)
        sdk.runner.stop = AsyncMock()

        # Should not raise, but handle gracefully
        await sdk.shutdown()

        assert sdk._is_running is False
        mock_store.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_skips_missing_topic_or_agent(self):
        """Test metrics skips metrics with missing topic or agent (line 528)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.get_metrics = AsyncMock(
            return_value=[
                {"topic": "topic1", "agent": "agent1", "event": "task_received"},
                {
                    "topic": None,
                    "agent": "agent1",
                    "event": "task_received",
                },  # Missing topic
                {
                    "topic": "topic2",
                    "agent": None,
                    "event": "task_received",
                },  # Missing agent
                {"topic": "topic3", "agent": "agent3", "event": "task_received"},
            ]
        )

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        metrics = await sdk.metrics()

        # Should only include metrics with both topic and agent
        assert "topic1" in metrics
        assert "topic3" in metrics
        assert "topic2" not in metrics  # Missing agent, should be skipped

    @pytest.mark.asyncio
    async def test_list_streams_auto_connects(self):
        """Test list_streams auto-connects if not connected (line 655)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_redis.xlen = AsyncMock()
        mock_bus._redis = None  # Not connected
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Set _redis after connect is called
        def connect_side_effect():
            mock_bus._redis = mock_redis

        mock_bus.connect.side_effect = connect_side_effect

        await sdk.list_streams()

        mock_bus.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_inspect_stream_raises_for_non_redis(self):
        """Test inspect_stream raises ValueError for non-Redis bus (line 684)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        # Remove _redis attribute
        if hasattr(mock_bus, "_redis"):
            delattr(mock_bus, "_redis")

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        with pytest.raises(
            ValueError, match="Event bus monitoring only works with Redis Streams"
        ):
            await sdk.inspect_stream("test.topic")

    @pytest.mark.asyncio
    async def test_inspect_stream_auto_connects(self):
        """Test inspect_stream auto-connects if not connected (line 687)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xrevrange = AsyncMock(return_value=[])
        mock_bus._redis = None  # Not connected
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Set _redis after connect is called
        def connect_side_effect():
            mock_bus._redis = mock_redis

        mock_bus.connect.side_effect = connect_side_effect

        await sdk.inspect_stream("test.topic")

        mock_bus.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_inspect_stream_handles_json_decode_error(self):
        """Test inspect_stream handles JSON decode errors (lines 705-706)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xrevrange = AsyncMock(
            return_value=[
                (b"123-0", {b"data": b"invalid json"}),
                (b"124-0", {b"data": b'{"valid": "json"}'}),
            ]
        )
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        messages = await sdk.inspect_stream("test.topic")

        # Should handle invalid JSON gracefully
        assert len(messages) == 2
        # Invalid JSON should be returned as string
        assert isinstance(messages[0]["data"], str)
        # Valid JSON should be parsed
        assert isinstance(messages[1]["data"], dict)

    @pytest.mark.asyncio
    async def test_list_groups_auto_connects(self):
        """Test list_groups auto-connects if not connected (line 729)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xinfo_groups = AsyncMock(return_value=[])
        mock_bus._redis = None  # Not connected
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Set _redis after connect is called
        def connect_side_effect():
            mock_bus._redis = mock_redis

        mock_bus.connect.side_effect = connect_side_effect

        await sdk.list_groups("test.topic")

        mock_bus.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_groups_handles_xinfo_error(self):
        """Test list_groups handles xinfo_groups exception (lines 737-739)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.xinfo_groups = AsyncMock(side_effect=Exception("XINFO failed"))
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        groups = await sdk.list_groups("test.topic")

        # Should return empty list on error
        assert groups == []

    @pytest.mark.asyncio
    async def test_inspect_dlq_auto_connects(self):
        """Test inspect_dlq auto-connects if not connected (line 779)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_bus._redis = None  # Not connected
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Set _redis after connect is called
        def connect_side_effect():
            mock_bus._redis = mock_redis

        mock_bus.connect.side_effect = connect_side_effect

        await sdk.inspect_dlq("test.topic")

        mock_bus.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_bus_stats_auto_connects(self):
        """Test get_bus_stats auto-connects if not connected (line 812)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_redis.info = AsyncMock(return_value={"used_memory_human": "1M"})
        mock_bus._redis = None  # Not connected
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        # Set _redis after connect is called
        def connect_side_effect():
            mock_bus._redis = mock_redis

        mock_bus.connect.side_effect = connect_side_effect

        await sdk.get_bus_stats()

        mock_bus.connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_bus_stats_handles_xinfo_error(self):
        """Test get_bus_stats handles xinfo_groups exception (lines 858-859)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[b"omni-stream:topic1"])
        mock_redis.xlen = AsyncMock(return_value=10)
        mock_redis.xinfo_groups = AsyncMock(side_effect=Exception("XINFO failed"))
        mock_redis.info = AsyncMock(return_value={"used_memory_human": "1M"})
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        stats = await sdk.get_bus_stats()

        # Should handle error gracefully
        assert "topic1" in stats["snapshot"]["topics"]
        assert stats["snapshot"]["topics"]["topic1"]["groups"] == []

    @pytest.mark.asyncio
    async def test_get_bus_stats_handles_dlq_error(self):
        """Test get_bus_stats handles DLQ xlen exception (lines 843-847)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[b"omni-stream:topic1"])
        mock_redis.xlen = AsyncMock(
            side_effect=[10, Exception("DLQ xlen failed")]
        )  # Stream length, then DLQ error
        mock_redis.xinfo_groups = AsyncMock(
            return_value=[
                {
                    "name": b"group1",
                    "consumers": 1,
                    "pending": 0,
                    "last-delivered-id": b"123-0",
                }
            ]
        )
        mock_redis.info = AsyncMock(return_value={"used_memory_human": "1M"})
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        stats = await sdk.get_bus_stats()

        # Should handle DLQ error gracefully
        assert "topic1" in stats["snapshot"]["topics"]
        groups = stats["snapshot"]["topics"]["topic1"]["groups"]
        assert len(groups) == 1
        assert groups[0]["dlq"] == 0  # Should default to 0 on error

    @pytest.mark.asyncio
    async def test_get_bus_stats_handles_redis_info_error(self):
        """Test get_bus_stats handles redis.info exception (lines 873-874)."""
        mock_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.keys = AsyncMock(return_value=[])
        mock_redis.info = AsyncMock(side_effect=Exception("Redis info failed"))
        mock_bus._redis = mock_redis
        mock_bus.connect = AsyncMock()

        sdk = OmniDaemonSDK(event_bus=mock_bus, store=mock_store)

        stats = await sdk.get_bus_stats()

        # Should handle error gracefully and use default
        assert stats["redis_info"]["used_memory_human"] == "-"
