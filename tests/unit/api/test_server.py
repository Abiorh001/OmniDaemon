"""Unit tests for API Server."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from omnidaemon.api.server import create_app, start_api_server


class TestAPIServerAppCreation:
    """Test suite for API app creation."""

    def test_create_app_success(self):
        """Test app creation success."""
        mock_sdk = MagicMock()
        app = create_app(mock_sdk)

        assert app is not None
        assert app.title == "OmniDaemon Control Plane API"

    def test_create_app_includes_title(self):
        """Test app includes title."""
        mock_sdk = MagicMock()
        app = create_app(mock_sdk)

        assert app.title == "OmniDaemon Control Plane API"

    def test_create_app_includes_description(self):
        """Test app includes description."""
        mock_sdk = MagicMock()
        app = create_app(mock_sdk)

        assert "HTTP API to manage agents" in app.description


class TestAPIServerPublishTaskEndpoint:
    """Test suite for publish task endpoint."""

    @pytest.mark.asyncio
    async def test_publish_task_success(self):
        """Test POST /publish-tasks success."""
        mock_sdk = MagicMock()
        mock_sdk.publish_task = AsyncMock(return_value="task-123")
        app = create_app(mock_sdk)
        client = TestClient(app)

        event_data = {"topic": "test.topic", "payload": {"content": "test content"}}

        response = client.post("/publish-tasks", json=event_data)

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task-123"
        assert data["status"] == "published"
        mock_sdk.publish_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_task_returns_task_id(self):
        """Test publish task returns task_id."""
        mock_sdk = MagicMock()
        mock_sdk.publish_task = AsyncMock(return_value="custom-task-id")
        app = create_app(mock_sdk)
        client = TestClient(app)

        event_data = {"topic": "test.topic", "payload": {"content": "test"}}

        response = client.post("/publish-tasks", json=event_data)

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "custom-task-id"

    @pytest.mark.asyncio
    async def test_publish_task_validation_error(self):
        """Test publish task with validation error."""
        mock_sdk = MagicMock()
        from pydantic import ValidationError

        mock_sdk.publish_task = AsyncMock(
            side_effect=ValidationError.from_exception_data(
                "EventEnvelope",
                [{"type": "missing", "loc": ("topic",), "msg": "Field required"}],
            )
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        # Invalid event - missing topic
        event_data = {"payload": {"content": "test"}}

        response = client.post("/publish-tasks", json=event_data)

        # FastAPI will validate before calling the endpoint
        assert response.status_code in [400, 422]  # Validation error

    @pytest.mark.asyncio
    async def test_publish_task_server_error(self):
        """Test publish task with server error."""
        mock_sdk = MagicMock()
        mock_sdk.publish_task = AsyncMock(side_effect=Exception("Server error"))
        app = create_app(mock_sdk)
        client = TestClient(app)

        event_data = {"topic": "test.topic", "payload": {"content": "test"}}

        response = client.post("/publish-tasks", json=event_data)

        assert response.status_code == 500
        assert "Failed to publish task" in response.json()["detail"]


class TestAPIServerAgentEndpoints:
    """Test suite for agent endpoints."""

    @pytest.mark.asyncio
    async def test_list_agents_success(self):
        """Test GET /agents success."""
        mock_sdk = MagicMock()
        mock_sdk.list_agents = AsyncMock(
            return_value={
                "topic1": [
                    {
                        "name": "agent1",
                        "tools": [],
                        "description": "",
                        "callback": "cb1",
                        "config": {},
                    }
                ]
            }
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/agents")

        assert response.status_code == 200
        data = response.json()
        assert "topic1" in data
        mock_sdk.list_agents.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_agent_success(self):
        """Test GET /agents/{topic}/{name} success."""
        mock_sdk = MagicMock()
        mock_sdk.get_agent = AsyncMock(
            return_value={
                "name": "test-agent",
                "topic": "test.topic",
                "callback": "test_callback",
            }
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/agents/test.topic/test-agent")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-agent"
        mock_sdk.get_agent.assert_called_once_with(
            topic="test.topic", agent_name="test-agent"
        )

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self):
        """Test GET /agents/{topic}/{name} not found."""
        mock_sdk = MagicMock()
        mock_sdk.get_agent = AsyncMock(return_value=None)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/agents/test.topic/nonexistent-agent")

        assert response.status_code == 404
        assert "Agent not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_unsubscribe_agent_success(self):
        """Test POST /agents/{topic}/{name}/unsubscribe success."""
        mock_sdk = MagicMock()
        mock_sdk.unsubscribe_agent = AsyncMock(return_value=True)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.post("/agents/test.topic/test-agent/unsubscribe")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unsubscribed"
        assert data["topic"] == "test.topic"
        assert data["agent"] == "test-agent"
        mock_sdk.unsubscribe_agent.assert_called_once_with(
            topic="test.topic", agent_name="test-agent"
        )

    @pytest.mark.asyncio
    async def test_unsubscribe_agent_not_found(self):
        """Test unsubscribe agent not found."""
        mock_sdk = MagicMock()
        mock_sdk.unsubscribe_agent = AsyncMock(return_value=False)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.post("/agents/test.topic/nonexistent-agent/unsubscribe")

        assert response.status_code == 404
        assert "Agent not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_delete_agent_success(self):
        """Test DELETE /agents/{topic}/{name} success."""
        mock_sdk = MagicMock()
        mock_sdk.delete_agent = AsyncMock(return_value=True)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.delete("/agents/test.topic/test-agent")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["cleanup"]["storage_deleted"] is True
        assert data["cleanup"]["consumer_group_deleted"] is True
        assert data["cleanup"]["dlq_deleted"] is False
        mock_sdk.delete_agent.assert_called_once_with(
            topic="test.topic",
            agent_name="test-agent",
            delete_group=True,
            delete_dlq=False,
        )

    @pytest.mark.asyncio
    async def test_delete_agent_with_params(self):
        """Test delete agent with query parameters."""
        mock_sdk = MagicMock()
        mock_sdk.delete_agent = AsyncMock(return_value=True)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.delete(
            "/agents/test.topic/test-agent?delete_group=false&delete_dlq=true"
        )

        assert response.status_code == 200
        data = response.json()
        assert data["cleanup"]["consumer_group_deleted"] is False
        assert data["cleanup"]["dlq_deleted"] is True
        mock_sdk.delete_agent.assert_called_once_with(
            topic="test.topic",
            agent_name="test-agent",
            delete_group=False,
            delete_dlq=True,
        )

    @pytest.mark.asyncio
    async def test_delete_agent_not_found(self):
        """Test delete agent not found."""
        mock_sdk = MagicMock()
        mock_sdk.delete_agent = AsyncMock(return_value=False)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.delete("/agents/test.topic/nonexistent-agent")

        assert response.status_code == 404
        assert "Agent not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_delete_topic_success(self):
        """Test DELETE /agents/topic/{topic} success."""
        mock_sdk = MagicMock()
        mock_sdk.delete_topic = AsyncMock(return_value=3)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.delete("/agents/topic/test.topic")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["topic"] == "test.topic"
        assert data["agents_deleted"] == 3
        mock_sdk.delete_topic.assert_called_once_with(topic="test.topic")


class TestAPIServerHealthEndpoint:
    """Test suite for health endpoint."""

    @pytest.mark.asyncio
    async def test_health_success(self):
        """Test GET /health success."""
        mock_sdk = MagicMock()
        mock_sdk.health = AsyncMock(
            return_value={
                "status": "running",
                "runner_id": "runner-123",
                "is_running": True,
            }
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "running"
        mock_sdk.health.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_returns_full_data(self):
        """Test health returns full health data."""
        mock_sdk = MagicMock()
        health_data = {
            "status": "running",
            "runner_id": "runner-123",
            "is_running": True,
            "event_bus_connected": True,
            "storage_healthy": True,
            "agents": {},
            "uptime_seconds": 100,
        }
        mock_sdk.health = AsyncMock(return_value=health_data)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data == health_data
        mock_sdk.health.assert_called_once()


class TestAPIServerTaskEndpoints:
    """Test suite for task endpoints."""

    @pytest.mark.asyncio
    async def test_get_task_result_success(self):
        """Test GET /tasks/{task_id} success."""
        mock_sdk = MagicMock()
        mock_sdk.get_result = AsyncMock(
            return_value={
                "task_id": "task-123",
                "result": "processing_result",
                "status": "completed",
            }
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/tasks/task-123")

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task-123"
        mock_sdk.get_result.assert_called_once_with("task-123")

    @pytest.mark.asyncio
    async def test_get_task_result_not_found(self):
        """Test get task result not found."""
        mock_sdk = MagicMock()
        mock_sdk.get_result = AsyncMock(return_value=None)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/tasks/nonexistent-task")

        assert response.status_code == 404
        assert "Task not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_results_success(self):
        """Test GET /tasks success."""
        mock_sdk = MagicMock()
        mock_sdk.list_results = AsyncMock(
            return_value=[
                {"task_id": "task-1", "result": "result1"},
                {"task_id": "task-2", "result": "result2"},
            ]
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/tasks")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        mock_sdk.list_results.assert_called_once_with(limit=100)

    @pytest.mark.asyncio
    async def test_list_results_with_limit(self):
        """Test list results with limit parameter."""
        mock_sdk = MagicMock()
        mock_sdk.list_results = AsyncMock(return_value=[])
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/tasks?limit=50")

        assert response.status_code == 200
        mock_sdk.list_results.assert_called_once_with(limit=50)

    @pytest.mark.asyncio
    async def test_delete_result_success(self):
        """Test DELETE /tasks/{task_id} success."""
        mock_sdk = MagicMock()
        mock_sdk.delete_result = AsyncMock(return_value=True)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.delete("/tasks/task-123")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"
        assert data["task_id"] == "task-123"
        mock_sdk.delete_result.assert_called_once_with("task-123")

    @pytest.mark.asyncio
    async def test_delete_result_not_found(self):
        """Test delete result not found."""
        mock_sdk = MagicMock()
        mock_sdk.delete_result = AsyncMock(return_value=False)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.delete("/tasks/nonexistent-task")

        assert response.status_code == 404
        assert "Task result not found" in response.json()["detail"]


class TestAPIServerMetricsEndpoint:
    """Test suite for metrics endpoint."""

    @pytest.mark.asyncio
    async def test_metrics_success(self):
        """Test GET /metrics success."""
        mock_sdk = MagicMock()
        mock_sdk.metrics = AsyncMock(
            return_value={
                "test.topic": {
                    "agent1": {
                        "tasks_received": 10,
                        "tasks_processed": 8,
                        "tasks_failed": 2,
                    }
                }
            }
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/metrics")

        assert response.status_code == 200
        data = response.json()
        assert "test.topic" in data
        mock_sdk.metrics.assert_called_once_with(topic=None, limit=1000)

    @pytest.mark.asyncio
    async def test_metrics_with_topic_filter(self):
        """Test metrics with topic parameter."""
        mock_sdk = MagicMock()
        mock_sdk.metrics = AsyncMock(return_value={})
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/metrics?topic=test.topic")

        assert response.status_code == 200
        mock_sdk.metrics.assert_called_once_with(topic="test.topic", limit=1000)

    @pytest.mark.asyncio
    async def test_metrics_with_limit(self):
        """Test metrics with limit parameter."""
        mock_sdk = MagicMock()
        mock_sdk.metrics = AsyncMock(return_value={})
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/metrics?limit=500")

        assert response.status_code == 200
        mock_sdk.metrics.assert_called_once_with(topic=None, limit=500)


class TestAPIServerStorageEndpoints:
    """Test suite for storage endpoints."""

    @pytest.mark.asyncio
    async def test_storage_health_success(self):
        """Test GET /storage/health success."""
        mock_sdk = MagicMock()
        mock_sdk.storage_health = AsyncMock(
            return_value={"status": "healthy", "backend": "redis"}
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/storage/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        mock_sdk.storage_health.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_agents_success(self):
        """Test DELETE /storage/agents success."""
        mock_sdk = MagicMock()
        mock_sdk.clear_agents = AsyncMock(return_value=5)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.delete("/storage/agents")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cleared"
        assert data["agents_deleted"] == 5
        mock_sdk.clear_agents.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_results_success(self):
        """Test DELETE /storage/results success."""
        mock_sdk = MagicMock()
        mock_sdk.clear_results = AsyncMock(return_value=10)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.delete("/storage/results")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cleared"
        assert data["results_deleted"] == 10
        mock_sdk.clear_results.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_metrics_success(self):
        """Test DELETE /storage/metrics success."""
        mock_sdk = MagicMock()
        mock_sdk.clear_metrics = AsyncMock(return_value=20)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.delete("/storage/metrics")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cleared"
        assert data["metrics_deleted"] == 20
        mock_sdk.clear_metrics.assert_called_once()

    @pytest.mark.asyncio
    async def test_clear_all_success(self):
        """Test DELETE /storage/all success."""
        mock_sdk = MagicMock()
        mock_sdk.clear_all = AsyncMock(
            return_value={"agents": 5, "results": 10, "metrics": 20}
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.delete("/storage/all")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "cleared"
        assert data["deleted_counts"]["agents"] == 5
        mock_sdk.clear_all.assert_called_once()


class TestAPIServerConfigEndpoints:
    """Test suite for config endpoints."""

    @pytest.mark.asyncio
    async def test_save_config_success(self):
        """Test POST /config/{key} success."""
        mock_sdk = MagicMock()
        mock_sdk.save_config = AsyncMock()
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.post("/config/test_key", json={"value": "test_value"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "saved"
        assert data["key"] == "test_key"
        mock_sdk.save_config.assert_called_once_with("test_key", "test_value")

    @pytest.mark.asyncio
    async def test_get_config_success(self):
        """Test GET /config/{key} success."""
        mock_sdk = MagicMock()
        mock_sdk.get_config = AsyncMock(return_value="config_value")
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/config/test_key")

        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "test_key"
        assert data["value"] == "config_value"
        mock_sdk.get_config.assert_called_once_with("test_key", default=None)

    @pytest.mark.asyncio
    async def test_get_config_with_default(self):
        """Test get config with default parameter."""
        mock_sdk = MagicMock()
        mock_sdk.get_config = AsyncMock(return_value="default_value")
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/config/nonexistent_key?default=default_value")

        assert response.status_code == 200
        mock_sdk.get_config.assert_called_once_with(
            "nonexistent_key", default="default_value"
        )


class TestAPIServerBusEndpoints:
    """Test suite for bus endpoints (Redis only)."""

    @pytest.mark.asyncio
    async def test_list_streams_success(self):
        """Test GET /bus/streams success."""
        mock_sdk = MagicMock()
        mock_sdk.list_streams = AsyncMock(
            return_value=[
                {"stream": "omni-stream:topic1", "length": 10},
                {"stream": "omni-stream:topic2", "length": 20},
            ]
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/bus/streams")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        mock_sdk.list_streams.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_streams_not_redis(self):
        """Test list streams with non-Redis bus."""
        mock_sdk = MagicMock()
        mock_sdk.list_streams = AsyncMock(
            side_effect=ValueError("Event bus monitoring only works with Redis Streams")
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/bus/streams")

        assert response.status_code == 400
        assert "Redis Streams" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_inspect_stream_success(self):
        """Test GET /bus/inspect/{stream} success."""
        mock_sdk = MagicMock()
        mock_sdk.inspect_stream = AsyncMock(
            return_value=[
                {"id": "123-0", "data": {"content": "test1"}},
                {"id": "124-0", "data": {"content": "test2"}},
            ]
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/bus/inspect/test.topic")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        mock_sdk.inspect_stream.assert_called_once_with("test.topic", limit=10)

    @pytest.mark.asyncio
    async def test_inspect_stream_with_limit(self):
        """Test inspect stream with limit parameter."""
        mock_sdk = MagicMock()
        mock_sdk.inspect_stream = AsyncMock(return_value=[])
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/bus/inspect/test.topic?limit=5")

        assert response.status_code == 200
        mock_sdk.inspect_stream.assert_called_once_with("test.topic", limit=5)

    @pytest.mark.asyncio
    async def test_list_groups_success(self):
        """Test GET /bus/groups/{stream} success."""
        mock_sdk = MagicMock()
        mock_sdk.list_groups = AsyncMock(
            return_value=[
                {
                    "name": "group1",
                    "consumers": 2,
                    "pending": 5,
                    "last_delivered_id": "123-0",
                }
            ]
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/bus/groups/test.topic")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        mock_sdk.list_groups.assert_called_once_with("test.topic")

    @pytest.mark.asyncio
    async def test_inspect_dlq_success(self):
        """Test GET /bus/dlq/{topic} success."""
        mock_sdk = MagicMock()
        mock_sdk.inspect_dlq = AsyncMock(
            return_value=[{"id": "123-0", "data": {"error": "test error"}}]
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/bus/dlq/test.topic")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        mock_sdk.inspect_dlq.assert_called_once_with("test.topic", limit=10)

    @pytest.mark.asyncio
    async def test_get_bus_stats_success(self):
        """Test GET /bus/stats success."""
        mock_sdk = MagicMock()
        mock_sdk.get_bus_stats = AsyncMock(
            return_value={
                "snapshot": {"timestamp": 1234567890, "topics": {}},
                "redis_info": {"used_memory_human": "1.5M"},
            }
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/bus/stats")

        assert response.status_code == 200
        data = response.json()
        assert "snapshot" in data
        assert "redis_info" in data
        mock_sdk.get_bus_stats.assert_called_once()


class TestAPIServerErrorHandling:
    """Test suite for error handling."""

    @pytest.mark.asyncio
    async def test_api_handles_validation_errors(self):
        """Test API handles validation errors."""
        mock_sdk = MagicMock()

        # SDK raises ValueError (ValidationError is a ValueError subclass)
        mock_sdk.publish_task = AsyncMock(
            side_effect=ValueError("Invalid topic format")
        )
        app = create_app(mock_sdk)
        client = TestClient(app)

        # Valid event structure, but SDK will raise ValueError
        event_data = {"topic": "test.topic", "payload": {"content": "test"}}

        response = client.post("/publish-tasks", json=event_data)

        # ValueError is caught by ValueError handler, returns 400
        assert response.status_code == 400
        assert "Invalid event" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_api_handles_server_errors(self):
        """Test API handles server errors."""
        mock_sdk = MagicMock()
        mock_sdk.get_agent = AsyncMock(side_effect=Exception("Internal server error"))
        app = create_app(mock_sdk)
        client = TestClient(app)

        # This will cause an unhandled exception
        # Note: FastAPI will catch it, but the endpoint might not have explicit error handling
        # Let's test with an endpoint that has error handling
        mock_sdk.list_streams = AsyncMock(side_effect=Exception("Server error"))
        response = client.get("/bus/streams")

        assert response.status_code == 500
        assert "Failed to list streams" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_api_handles_not_found(self):
        """Test API handles not found errors."""
        mock_sdk = MagicMock()
        mock_sdk.get_agent = AsyncMock(return_value=None)
        app = create_app(mock_sdk)
        client = TestClient(app)

        response = client.get("/agents/test.topic/nonexistent")

        assert response.status_code == 404
        assert "Agent not found" in response.json()["detail"]


class TestAPIServerStart:
    """Test suite for server start function."""

    @pytest.mark.asyncio
    async def test_start_api_server_success(self):
        """Test start_api_server function."""
        mock_sdk = MagicMock()

        with (
            patch("uvicorn.Server") as mock_server_class,
            patch("uvicorn.Config") as mock_config_class,
        ):
            mock_server = AsyncMock()
            mock_server.serve = AsyncMock()
            mock_server_class.return_value = mock_server
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config

            await start_api_server(mock_sdk, host="127.0.0.1", port=8000)

            mock_config_class.assert_called_once()
            mock_server_class.assert_called_once_with(mock_config)
            mock_server.serve.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_api_server_custom_host_port(self):
        """Test start_api_server with custom host/port."""
        mock_sdk = MagicMock()

        with (
            patch("uvicorn.Server") as mock_server_class,
            patch("uvicorn.Config") as mock_config_class,
        ):
            mock_server = AsyncMock()
            mock_server.serve = AsyncMock()
            mock_server_class.return_value = mock_server
            mock_config = MagicMock()
            mock_config_class.return_value = mock_config

            await start_api_server(mock_sdk, host="0.0.0.0", port=9000)

            call_args = mock_config_class.call_args
            assert call_args[1]["host"] == "0.0.0.0"
            assert call_args[1]["port"] == 9000
