"""Unit tests for BaseAgentRunner."""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch
from omnidaemon.agent_runner.runner import BaseAgentRunner


class TestBaseAgentRunnerInitialization:
    """Test suite for BaseAgentRunner initialization."""

    @pytest.mark.asyncio
    async def test_runner_init_with_dependencies(self):
        """Test runner initialization with event bus and store."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        assert runner.event_bus == mock_event_bus
        assert runner.store == mock_store
        assert runner.runner_id is not None
        assert runner.event_bus_connected is False
        assert runner._running is False

    @pytest.mark.asyncio
    async def test_runner_init_generates_id(self):
        """Test runner generates unique runner_id."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()

        runner1 = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner2 = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        assert runner1.runner_id != runner2.runner_id
        assert isinstance(runner1.runner_id, str)
        assert isinstance(runner2.runner_id, str)

    @pytest.mark.asyncio
    async def test_runner_init_custom_id(self):
        """Test runner accepts custom runner_id."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        custom_id = "custom-runner-id-123"

        runner = BaseAgentRunner(
            event_bus=mock_event_bus, store=mock_store, runner_id=custom_id
        )

        assert runner.runner_id == custom_id

    @pytest.mark.asyncio
    async def test_runner_init_not_connected(self):
        """Test runner starts disconnected."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        assert runner.event_bus_connected is False
        assert runner._running is False


class TestBaseAgentRunnerRegisterHandler:
    """Test suite for BaseAgentRunner register_handler operations."""

    @pytest.mark.asyncio
    async def test_register_handler_success(self):
        """Test successful handler registration."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.add_agent = AsyncMock()
        mock_event_bus.subscribe = AsyncMock()
        mock_event_bus.connect = AsyncMock()
        mock_store.connect = AsyncMock()
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.save_config = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def callback(msg):
            return "result"

        subscription = {"name": "test-agent", "callback": callback, "config": {}}

        await runner.register_handler("test.topic", subscription)

        mock_store.add_agent.assert_called_once()
        mock_event_bus.subscribe.assert_called_once()
        assert runner.event_bus_connected is True

    @pytest.mark.asyncio
    async def test_register_handler_auto_connects(self):
        """Test register_handler auto-connects dependencies."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.add_agent = AsyncMock()
        mock_event_bus.subscribe = AsyncMock()
        mock_event_bus.connect = AsyncMock()
        mock_store.connect = AsyncMock()
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.save_config = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        assert runner.event_bus_connected is False

        async def callback(msg):
            return "result"

        subscription = {"name": "test-agent", "callback": callback}

        await runner.register_handler("test.topic", subscription)

        mock_event_bus.connect.assert_called_once()
        mock_store.connect.assert_called_once()
        assert runner.event_bus_connected is True

    @pytest.mark.asyncio
    async def test_register_handler_stores_agent(self):
        """Test register_handler stores agent in storage."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.add_agent = AsyncMock()
        mock_event_bus.subscribe = AsyncMock()
        mock_event_bus.connect = AsyncMock()
        mock_store.connect = AsyncMock()
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.save_config = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def callback(msg):
            return "result"

        subscription = {"name": "test-agent", "callback": callback}

        await runner.register_handler("test.topic", subscription)

        mock_store.add_agent.assert_called_once_with(
            topic="test.topic", agent_data=subscription
        )

    @pytest.mark.asyncio
    async def test_register_handler_subscribes_to_bus(self):
        """Test register_handler subscribes to event bus."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.add_agent = AsyncMock()
        mock_event_bus.subscribe = AsyncMock()
        mock_event_bus.connect = AsyncMock()
        mock_store.connect = AsyncMock()
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.save_config = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def callback(msg):
            return "result"

        subscription = {
            "name": "test-agent",
            "callback": callback,
            "config": {"consumer_count": 2},
        }

        await runner.register_handler("test.topic", subscription)

        mock_event_bus.subscribe.assert_called_once()
        call_args = mock_event_bus.subscribe.call_args
        assert call_args[1]["topic"] == "test.topic"
        assert call_args[1]["agent_name"] == "test-agent"
        assert call_args[1]["config"] == {"consumer_count": 2}

    @pytest.mark.asyncio
    async def test_register_handler_sets_start_time(self):
        """Test register_handler sets start time on first call."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.add_agent = AsyncMock()
        mock_event_bus.subscribe = AsyncMock()
        mock_event_bus.connect = AsyncMock()
        mock_store.connect = AsyncMock()
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.save_config = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def callback(msg):
            return "result"

        subscription = {"name": "test-agent", "callback": callback}

        await runner.register_handler("test.topic", subscription)

        # Should save start time and runner_id
        assert mock_store.save_config.call_count == 2
        save_calls = [call[0][0] for call in mock_store.save_config.call_args_list]
        assert "_omnidaemon_start_time" in save_calls
        assert "_omnidaemon_runner_id" in save_calls

    @pytest.mark.asyncio
    async def test_register_handler_sets_runner_id(self):
        """Test register_handler sets runner_id in storage."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.add_agent = AsyncMock()
        mock_event_bus.subscribe = AsyncMock()
        mock_event_bus.connect = AsyncMock()
        mock_store.connect = AsyncMock()
        mock_store.get_config = AsyncMock(return_value=None)
        mock_store.save_config = AsyncMock()

        runner = BaseAgentRunner(
            event_bus=mock_event_bus, store=mock_store, runner_id="custom-runner-123"
        )

        async def callback(msg):
            return "result"

        subscription = {"name": "test-agent", "callback": callback}

        await runner.register_handler("test.topic", subscription)

        # Check that runner_id was saved
        save_calls = mock_store.save_config.call_args_list
        runner_id_call = [
            call for call in save_calls if call[0][0] == "_omnidaemon_runner_id"
        ]
        assert len(runner_id_call) == 1
        assert runner_id_call[0][0][1] == "custom-runner-123"

    @pytest.mark.asyncio
    async def test_register_handler_multiple_agents(self):
        """Test registering multiple agents."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.add_agent = AsyncMock()
        mock_event_bus.subscribe = AsyncMock()
        mock_event_bus.connect = AsyncMock()
        mock_store.connect = AsyncMock()
        mock_store.get_config = AsyncMock(return_value=time.time())  # Already started
        mock_store.save_config = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def callback1(msg):
            return "result1"

        async def callback2(msg):
            return "result2"

        subscription1 = {"name": "agent-1", "callback": callback1}
        subscription2 = {"name": "agent-2", "callback": callback2}

        await runner.register_handler("topic1", subscription1)
        await runner.register_handler("topic2", subscription2)

        assert mock_store.add_agent.call_count == 2
        assert mock_event_bus.subscribe.call_count == 2

    @pytest.mark.asyncio
    async def test_register_handler_same_topic_different_agents(self):
        """Test multiple agents on same topic."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.add_agent = AsyncMock()
        mock_event_bus.subscribe = AsyncMock()
        mock_event_bus.connect = AsyncMock()
        mock_store.connect = AsyncMock()
        mock_store.get_config = AsyncMock(return_value=time.time())
        mock_store.save_config = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def callback1(msg):
            return "result1"

        async def callback2(msg):
            return "result2"

        subscription1 = {"name": "agent-1", "callback": callback1}
        subscription2 = {"name": "agent-2", "callback": callback2}

        await runner.register_handler("test.topic", subscription1)
        await runner.register_handler("test.topic", subscription2)

        assert mock_store.add_agent.call_count == 2
        assert mock_event_bus.subscribe.call_count == 2

    @pytest.mark.asyncio
    async def test_register_handler_different_topics(self):
        """Test agents on different topics."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.add_agent = AsyncMock()
        mock_event_bus.subscribe = AsyncMock()
        mock_event_bus.connect = AsyncMock()
        mock_store.connect = AsyncMock()
        mock_store.get_config = AsyncMock(return_value=time.time())
        mock_store.save_config = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def callback(msg):
            return "result"

        subscription = {"name": "test-agent", "callback": callback}

        await runner.register_handler("topic1", subscription)
        await runner.register_handler("topic2", subscription)

        assert mock_store.add_agent.call_count == 2
        assert mock_event_bus.subscribe.call_count == 2


class TestBaseAgentRunnerAgentCallbackWrapper:
    """Test suite for BaseAgentRunner agent callback wrapper."""

    @pytest.mark.asyncio
    async def test_agent_wrapper_calls_callback(self):
        """Test wrapper calls agent callback."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        callback_called = []

        async def agent_callback(msg):
            callback_called.append(msg)
            return "callback_result"

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=agent_callback
        )

        message = {"task_id": "task-123", "content": "test message"}

        await wrapper(message)

        assert len(callback_called) == 1
        assert callback_called[0]["content"] == "test message"

    @pytest.mark.asyncio
    async def test_agent_wrapper_tracks_task_received(self):
        """Test wrapper tracks task_received metric."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(
            event_bus=mock_event_bus, store=mock_store, runner_id="test-runner"
        )

        async def agent_callback(msg):
            return "result"

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=agent_callback
        )

        message = {"task_id": "task-123", "content": "test"}

        await wrapper(message)

        # Check that task_received metric was saved
        metric_calls = mock_store.save_metric.call_args_list
        received_metrics = [
            call for call in metric_calls if call[0][0].get("event") == "task_received"
        ]
        assert len(received_metrics) == 1
        assert received_metrics[0][0][0]["topic"] == "test.topic"
        assert received_metrics[0][0][0]["agent"] == "test-agent"
        assert received_metrics[0][0][0]["runner_id"] == "test-runner"

    @pytest.mark.asyncio
    async def test_agent_wrapper_tracks_task_processed(self):
        """Test wrapper tracks task_processed metric."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def agent_callback(msg):
            await asyncio.sleep(0.01)  # Simulate processing time
            return "result"

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=agent_callback
        )

        message = {"task_id": "task-123", "content": "test"}

        await wrapper(message)

        # Check that task_processed metric was saved
        metric_calls = mock_store.save_metric.call_args_list
        processed_metrics = [
            call for call in metric_calls if call[0][0].get("event") == "task_processed"
        ]
        assert len(processed_metrics) == 1
        assert "processing_time_sec" in processed_metrics[0][0][0]

    @pytest.mark.asyncio
    async def test_agent_wrapper_tracks_processing_time(self):
        """Test wrapper tracks processing time."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def agent_callback(msg):
            await asyncio.sleep(0.05)  # Simulate processing
            return "result"

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=agent_callback
        )

        message = {"task_id": "task-123", "content": "test"}

        await wrapper(message)

        # Check processing time was tracked
        metric_calls = mock_store.save_metric.call_args_list
        processed_metrics = [
            call for call in metric_calls if call[0][0].get("event") == "task_processed"
        ]
        assert len(processed_metrics) == 1
        processing_time = processed_metrics[0][0][0]["processing_time_sec"]
        assert processing_time >= 0.05

    @pytest.mark.asyncio
    async def test_agent_wrapper_tracks_task_failed(self):
        """Test wrapper tracks task_failed metric."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def agent_callback(msg):
            raise ValueError("Test error")

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=agent_callback
        )

        message = {"task_id": "task-123", "content": "test"}

        with pytest.raises(ValueError):
            await wrapper(message)

        # Check that task_failed metric was saved
        metric_calls = mock_store.save_metric.call_args_list
        failed_metrics = [
            call for call in metric_calls if call[0][0].get("event") == "task_failed"
        ]
        assert len(failed_metrics) == 1
        assert failed_metrics[0][0][0]["error"] == "Test error"

    @pytest.mark.asyncio
    async def test_agent_wrapper_handles_async_callback(self):
        """Test wrapper handles async callbacks."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def async_callback(msg):
            await asyncio.sleep(0.01)
            return "async_result"

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=async_callback
        )

        message = {"task_id": "task-123", "content": "test"}

        result = await wrapper(message)

        # Should complete successfully
        assert result is None  # Wrapper doesn't return, but callback executed

    @pytest.mark.asyncio
    async def test_agent_wrapper_handles_sync_callback(self):
        """Test wrapper handles sync callbacks."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        def sync_callback(msg):
            return "sync_result"

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=sync_callback
        )

        message = {"task_id": "task-123", "content": "test"}

        await wrapper(message)

        # Should complete successfully with sync callback

    @pytest.mark.asyncio
    async def test_agent_wrapper_adds_topic_to_message(self):
        """Test wrapper adds topic if missing."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        received_message = None

        async def agent_callback(msg):
            nonlocal received_message
            received_message = msg
            return "result"

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=agent_callback
        )

        message = {
            "task_id": "task-123",
            "content": "test",
            # Missing topic
        }

        await wrapper(message)

        assert received_message is not None
        assert received_message["topic"] == "test.topic"

    @pytest.mark.asyncio
    async def test_agent_wrapper_adds_agent_name(self):
        """Test wrapper adds agent name to message."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        received_message = None

        async def agent_callback(msg):
            nonlocal received_message
            received_message = msg
            return "result"

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=agent_callback
        )

        message = {"task_id": "task-123", "content": "test"}

        await wrapper(message)

        assert received_message is not None
        assert received_message["agent"] == "test-agent"

    @pytest.mark.asyncio
    async def test_agent_wrapper_handles_callback_exception(self):
        """Test wrapper handles callback exceptions."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def agent_callback(msg):
            raise RuntimeError("Callback exception")

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=agent_callback
        )

        message = {"task_id": "task-123", "content": "test"}

        with pytest.raises(RuntimeError, match="Callback exception"):
            await wrapper(message)

        # Should track failure
        metric_calls = mock_store.save_metric.call_args_list
        failed_metrics = [
            call for call in metric_calls if call[0][0].get("event") == "task_failed"
        ]
        assert len(failed_metrics) == 1

    @pytest.mark.asyncio
    async def test_agent_wrapper_sends_response(self):
        """Test wrapper sends response after processing."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_metric = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        async def agent_callback(msg):
            return "callback_result"

        wrapper = await runner._make_agent_callback(
            topic="test.topic", agent_name="test-agent", agent_callback=agent_callback
        )

        message = {"task_id": "task-123", "content": "test"}

        await wrapper(message)

        # Should save result
        mock_store.save_result.assert_called_once()
        call_args = mock_store.save_result.call_args
        assert call_args[1]["task_id"] == "task-123"
        assert call_args[1]["ttl_seconds"] == 86400


class TestBaseAgentRunnerPublish:
    """Test suite for BaseAgentRunner publish operations."""

    @pytest.mark.asyncio
    async def test_publish_success(self):
        """Test successful event publication."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_event_bus.publish = AsyncMock(return_value="task-123")
        mock_event_bus.connect = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner.event_bus_connected = True

        event_payload = {
            "id": "task-123",
            "topic": "test.topic",
            "payload": {"content": "test"},
        }

        task_id = await runner.publish(event_payload)

        assert task_id == "task-123"
        mock_event_bus.publish.assert_called_once_with(event_payload=event_payload)

    @pytest.mark.asyncio
    async def test_publish_auto_connects(self):
        """Test publish auto-connects if needed."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_event_bus.publish = AsyncMock(return_value="task-123")
        mock_event_bus.connect = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        assert runner.event_bus_connected is False

        event_payload = {
            "id": "task-123",
            "topic": "test.topic",
            "payload": {"content": "test"},
        }

        await runner.publish(event_payload)

        mock_event_bus.connect.assert_called_once()
        assert runner.event_bus_connected is True

    @pytest.mark.asyncio
    async def test_publish_returns_task_id(self):
        """Test publish returns task ID."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_event_bus.publish = AsyncMock(return_value="custom-task-id")
        mock_event_bus.connect = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner.event_bus_connected = True

        event_payload = {
            "id": "custom-task-id",
            "topic": "test.topic",
            "payload": {"content": "test"},
        }

        task_id = await runner.publish(event_payload)

        assert task_id == "custom-task-id"


class TestBaseAgentRunnerSendResponse:
    """Test suite for BaseAgentRunner send_response operations."""

    @pytest.mark.asyncio
    async def test_send_response_saves_result(self):
        """Test send_response saves result to storage."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        message = {"task_id": "task-123", "content": "test"}
        result = "processing_result"

        await runner._send_response(message, result)

        mock_store.save_result.assert_called_once()
        call_args = mock_store.save_result.call_args
        assert call_args[1]["task_id"] == "task-123"
        assert call_args[1]["ttl_seconds"] == 86400
        saved_result = call_args[1]["result"]
        assert saved_result["result"] == "processing_result"
        assert saved_result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_send_response_with_ttl(self):
        """Test send_response saves with TTL."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        message = {"task_id": "task-123", "content": "test"}
        result = "result"

        await runner._send_response(message, result)

        call_args = mock_store.save_result.call_args
        assert call_args[1]["ttl_seconds"] == 86400  # 24 hours

    @pytest.mark.asyncio
    async def test_send_response_webhook_success(self):
        """Test send_response calls webhook successfully."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        message = {
            "task_id": "task-123",
            "content": "test",
            "webhook": "https://example.com/webhook",
        }
        result = "result"

        # Create proper async context manager mocks
        # session.post() returns a response object that is an async context manager
        mock_resp = AsyncMock()
        mock_resp.status = 200
        # Make mock_resp an async context manager
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        # session.post() should return the response object directly (not a coroutine)
        mock_session_instance = AsyncMock()
        mock_session_instance.post = MagicMock(
            return_value=mock_resp
        )  # Not AsyncMock, regular MagicMock
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock(return_value=None)

        # Make ClientSession return our mock instance when called
        mock_client_session_class = MagicMock(return_value=mock_session_instance)

        with patch(
            "omnidaemon.agent_runner.runner.aiohttp.ClientSession",
            mock_client_session_class,
        ):
            await runner._send_response(message, result)

            # Should be called once and break out of retry loop
            mock_session_instance.post.assert_called_once()
            call_args = mock_session_instance.post.call_args
            assert call_args[0][0] == "https://example.com/webhook"

    @pytest.mark.asyncio
    async def test_send_response_webhook_retries(self):
        """Test send_response retries webhook on failure."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        message = {
            "task_id": "task-123",
            "content": "test",
            "webhook": "https://example.com/webhook",
        }
        result = "result"

        call_count = 0

        def post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Network error")
            # Success on second attempt
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_resp.__aexit__ = AsyncMock(return_value=None)
            return mock_resp

        # Create proper async context manager mocks
        mock_session_instance = AsyncMock()
        # post() is not async, it returns the response object directly
        mock_session_instance.post = MagicMock(side_effect=post_side_effect)
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock(return_value=None)

        # Make ClientSession return our mock instance when called
        mock_client_session_class = MagicMock(return_value=mock_session_instance)

        with (
            patch(
                "omnidaemon.agent_runner.runner.aiohttp.ClientSession",
                mock_client_session_class,
            ),
            patch("asyncio.sleep", return_value=None),
        ):  # Skip actual sleep in tests
            await runner._send_response(message, result)

            # Should retry (called more than once, but breaks on success)
            assert mock_session_instance.post.call_count >= 2

    @pytest.mark.asyncio
    async def test_send_response_webhook_max_retries(self):
        """Test send_response respects max retries."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        message = {
            "task_id": "task-123",
            "content": "test",
            "webhook": "https://example.com/webhook",
        }
        result = "result"

        # Create proper async context manager mocks
        mock_session_instance = AsyncMock()

        # post() is not async, it returns the response object directly
        # But we want it to raise an exception when used in async with
        def post_side_effect(*args, **kwargs):
            raise Exception("Network error")

        mock_session_instance.post = MagicMock(side_effect=post_side_effect)
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock(return_value=None)

        # Make ClientSession return our mock instance when called
        mock_client_session_class = MagicMock(return_value=mock_session_instance)

        with (
            patch(
                "omnidaemon.agent_runner.runner.aiohttp.ClientSession",
                mock_client_session_class,
            ),
            patch("asyncio.sleep", return_value=None),
        ):  # Skip actual sleep in tests
            await runner._send_response(message, result)

            # Should retry max 3 times (one for each attempt)
            assert mock_session_instance.post.call_count == 3

    @pytest.mark.asyncio
    async def test_send_response_webhook_backoff(self):
        """Test send_response uses exponential backoff."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        message = {
            "task_id": "task-123",
            "content": "test",
            "webhook": "https://example.com/webhook",
        }
        result = "result"

        sleep_times = []

        async def tracked_sleep(delay):
            sleep_times.append(delay)

        # Create proper async context manager mocks
        mock_session_instance = AsyncMock()

        # post() is not async, it returns the response object directly
        # But we want it to raise an exception when used in async with
        def post_side_effect(*args, **kwargs):
            raise Exception("Network error")

        mock_session_instance.post = MagicMock(side_effect=post_side_effect)
        mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
        mock_session_instance.__aexit__ = AsyncMock(return_value=None)

        # Make ClientSession return our mock instance when called
        mock_client_session_class = MagicMock(return_value=mock_session_instance)

        with (
            patch(
                "omnidaemon.agent_runner.runner.aiohttp.ClientSession",
                mock_client_session_class,
            ),
            patch("asyncio.sleep", side_effect=tracked_sleep),
        ):
            await runner._send_response(message, result)

            # Should have exponential backoff delays
            # First retry: 2^1 = 2, second retry: 2^2 = 4
            assert len(sleep_times) == 2
            assert sleep_times[0] == 2  # 2^1
            assert sleep_times[1] == 4  # 2^2

    @pytest.mark.asyncio
    async def test_send_response_reply_to(self):
        """Test send_response publishes to reply_to topic."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_result = AsyncMock()
        mock_event_bus.publish = AsyncMock(return_value="reply-task-id")
        mock_event_bus.connect = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner.event_bus_connected = True

        message = {"task_id": "task-123", "content": "test", "reply_to": "reply.topic"}
        result = "result"

        with patch(
            "omnidaemon.agent_runner.runner.BaseAgentRunner.publish_response"
        ) as mock_publish_response:
            mock_publish_response.return_value = "reply-task-id"
            await runner._send_response(message, result)

            mock_publish_response.assert_called_once_with(message, result)

    @pytest.mark.asyncio
    async def test_send_response_no_webhook_no_reply(self):
        """Test send_response with no webhook/reply."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_result = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        message = {
            "task_id": "task-123",
            "content": "test",
            # No webhook, no reply_to
        }
        result = "result"

        await runner._send_response(message, result)

        # Should still save result
        mock_store.save_result.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_response_handles_storage_error(self):
        """Test send_response handles storage errors."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_result = AsyncMock(side_effect=Exception("Storage error"))

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        message = {"task_id": "task-123", "content": "test"}
        result = "result"

        # Should not raise, just log error
        await runner._send_response(message, result)

        # Should continue processing even if storage fails
        mock_store.save_result.assert_called_once()


class TestBaseAgentRunnerPublishResponse:
    """Test suite for BaseAgentRunner publish_response operations."""

    @pytest.mark.asyncio
    async def test_publish_response_success(self):
        """Test successful response publication."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_event_bus.publish = AsyncMock(return_value="new-task-id")
        mock_event_bus.connect = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner.event_bus_connected = True

        message = {
            "task_id": "original-task-id",
            "topic": "original.topic",
            "reply_to": "reply.topic",
            "correlation_id": "corr-123",
            "source": "test-source",
        }
        result = "response_content"

        new_task_id = await runner.publish_response(message, result)

        assert new_task_id == "new-task-id"
        mock_event_bus.publish.assert_called_once()
        call_args = mock_event_bus.publish.call_args
        event_payload = call_args[1]["event_payload"]
        assert event_payload["topic"] == "reply.topic"
        assert event_payload["payload"]["content"] == "response_content"

    @pytest.mark.asyncio
    async def test_publish_response_creates_new_event(self):
        """Test publish_response creates new EventEnvelope."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_event_bus.publish = AsyncMock(return_value="new-task-id")
        mock_event_bus.connect = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner.event_bus_connected = True

        message = {"task_id": "original-task-id", "reply_to": "reply.topic"}
        result = "response"

        await runner.publish_response(message, result)

        mock_event_bus.publish.assert_called_once()
        call_args = mock_event_bus.publish.call_args
        event_payload = call_args[1]["event_payload"]
        assert "id" in event_payload
        assert event_payload["topic"] == "reply.topic"
        assert event_payload["payload"]["content"] == "response"

    @pytest.mark.asyncio
    async def test_publish_response_sets_causation_id(self):
        """Test publish_response sets causation_id."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_event_bus.publish = AsyncMock(return_value="new-task-id")
        mock_event_bus.connect = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner.event_bus_connected = True

        message = {"task_id": "original-task-id", "reply_to": "reply.topic"}
        result = "response"

        await runner.publish_response(message, result)

        call_args = mock_event_bus.publish.call_args
        event_payload = call_args[1]["event_payload"]
        assert event_payload["causation_id"] == "original-task-id"

    @pytest.mark.asyncio
    async def test_publish_response_preserves_correlation_id(self):
        """Test publish_response preserves correlation_id."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_event_bus.publish = AsyncMock(return_value="new-task-id")
        mock_event_bus.connect = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner.event_bus_connected = True

        message = {
            "task_id": "original-task-id",
            "reply_to": "reply.topic",
            "correlation_id": "corr-123",
        }
        result = "response"

        await runner.publish_response(message, result)

        call_args = mock_event_bus.publish.call_args
        event_payload = call_args[1]["event_payload"]
        assert event_payload["correlation_id"] == "corr-123"

    @pytest.mark.asyncio
    async def test_publish_response_no_reply_to(self):
        """Test publish_response returns None if no reply_to."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        message = {
            "task_id": "original-task-id"
            # No reply_to
        }
        result = "response"

        new_task_id = await runner.publish_response(message, result)

        assert new_task_id is None
        mock_event_bus.publish.assert_not_called()


class TestBaseAgentRunnerStartStop:
    """Test suite for BaseAgentRunner start/stop operations."""

    @pytest.mark.asyncio
    async def test_start_success(self):
        """Test successful runner start."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(
            return_value={"topic1": {"agent1": {}}, "topic2": {"agent2": {}}}
        )

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        await runner.start()

        assert runner._running is True
        mock_store.list_all_agents.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_loads_agents(self):
        """Test start loads agents from storage."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(
            return_value={
                "topic1": {"agent1": {"name": "agent1"}},
                "topic2": {"agent2": {"name": "agent2"}},
            }
        )

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        await runner.start()

        mock_store.list_all_agents.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_idempotent(self):
        """Test multiple start() calls are safe."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.list_all_agents = AsyncMock(return_value={})

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)

        await runner.start()
        assert runner._running is True

        # Second call should not raise error
        await runner.start()
        assert runner._running is True

    @pytest.mark.asyncio
    async def test_stop_success(self):
        """Test successful runner stop."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_config = AsyncMock()
        mock_event_bus.close = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner._running = True

        await runner.stop()

        assert runner._running is False
        mock_event_bus.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_clears_start_time(self):
        """Test stop clears start time from storage."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_config = AsyncMock()
        mock_event_bus.close = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner._running = True

        await runner.stop()

        # Should clear start time and runner_id
        assert mock_store.save_config.call_count == 2
        save_calls = [call[0][0] for call in mock_store.save_config.call_args_list]
        assert "_omnidaemon_start_time" in save_calls
        assert "_omnidaemon_runner_id" in save_calls

    @pytest.mark.asyncio
    async def test_stop_closes_event_bus(self):
        """Test stop closes event bus."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_config = AsyncMock()
        mock_event_bus.close = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner._running = True

        await runner.stop()

        mock_event_bus.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_idempotent(self):
        """Test multiple stop() calls are safe."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_config = AsyncMock()
        mock_event_bus.close = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner._running = True

        await runner.stop()
        await runner.stop()
        await runner.stop()

        # Should not raise errors
        assert runner._running is False

    @pytest.mark.asyncio
    async def test_stop_handles_storage_error(self):
        """Test stop handles storage errors gracefully."""
        mock_event_bus = AsyncMock()
        mock_store = AsyncMock()
        mock_store.save_config = AsyncMock(side_effect=Exception("Storage error"))
        mock_event_bus.close = AsyncMock()

        runner = BaseAgentRunner(event_bus=mock_event_bus, store=mock_store)
        runner._running = True

        # Should not raise, just log warning
        await runner.stop()

        # Should still close event bus
        mock_event_bus.close.assert_called_once()
        assert runner._running is False


class TestBaseAgentRunnerUtility:
    """Test suite for BaseAgentRunner utility methods."""

    @pytest.mark.asyncio
    async def test_maybe_await_coroutine(self):
        """Test _maybe_await handles coroutines."""

        async def coro_func():
            await asyncio.sleep(0.01)
            return "coro_result"

        result = await BaseAgentRunner._maybe_await(coro_func())

        assert result == "coro_result"

    @pytest.mark.asyncio
    async def test_maybe_await_non_coroutine(self):
        """Test _maybe_await handles non-coroutines."""

        def sync_func():
            return "sync_result"

        result = await BaseAgentRunner._maybe_await(sync_func())

        assert result == "sync_result"
