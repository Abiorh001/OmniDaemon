"""Unit tests for JSONStore implementation."""

import pytest
import json
import tempfile
import shutil
import time
import os
from pathlib import Path
from omnidaemon.storage.json_store import JSONStore


@pytest.fixture
def temp_storage_dir():
    """Create a temporary storage directory for tests."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def store(temp_storage_dir):
    """Create a JSONStore instance for testing."""
    return JSONStore(storage_dir=temp_storage_dir)


class TestJSONStoreInitialization:
    """Test suite for JSONStore initialization."""

    def test_json_store_init_default_dir(self):
        """Test initialization with default directory."""
        store = JSONStore()
        assert store.storage_dir == Path(".omnidaemon_data")
        assert store.storage_dir.exists()

    def test_json_store_init_custom_dir(self, temp_storage_dir):
        """Test initialization with custom directory."""
        store = JSONStore(storage_dir=temp_storage_dir)
        assert store.storage_dir == Path(temp_storage_dir)
        assert store.storage_dir.exists()

    def test_json_store_init_creates_dir(self, temp_storage_dir):
        """Test initialization creates directory if needed."""
        new_dir = os.path.join(temp_storage_dir, "new_dir")
        JSONStore(storage_dir=new_dir)
        assert Path(new_dir).exists()

    @pytest.mark.asyncio
    async def test_json_store_init_loads_existing_data(self, temp_storage_dir):
        """Test initialization loads existing data."""
        # Create existing data files
        agents_file = Path(temp_storage_dir) / "agents.json"
        agents_file.write_text(json.dumps({"test.topic": [{"name": "test-agent"}]}))

        store = JSONStore(storage_dir=temp_storage_dir)
        await store.connect()

        agents = await store.get_agents_by_topic("test.topic")
        assert len(agents) == 1
        assert agents[0]["name"] == "test-agent"


class TestJSONStoreConnection:
    """Test suite for JSONStore connection operations."""

    @pytest.mark.asyncio
    async def test_connect_loads_all_data(self, store, temp_storage_dir):
        """Test connect loads all data files."""
        # Create data files
        agents_file = Path(temp_storage_dir) / "agents.json"
        results_file = Path(temp_storage_dir) / "results.json"
        metrics_file = Path(temp_storage_dir) / "metrics.json"
        config_file = Path(temp_storage_dir) / "config.json"

        agents_file.write_text(json.dumps({"topic1": [{"name": "agent1"}]}))
        results_file.write_text(json.dumps({"task1": {"result": {"data": "test"}}}))
        metrics_file.write_text(json.dumps([{"event": "test"}]))
        config_file.write_text(json.dumps({"key": "value"}))

        await store.connect()

        assert len(await store.get_agents_by_topic("topic1")) == 1
        assert await store.get_result("task1") is not None
        assert len(await store.get_metrics()) == 1
        assert await store.get_config("key") == "value"

    @pytest.mark.asyncio
    async def test_connect_idempotent(self, store):
        """Test multiple connect() calls are safe."""
        await store.connect()
        await store.connect()
        await store.connect()

        # Should not raise exception
        assert store._connected

    @pytest.mark.asyncio
    async def test_close_saves_all_data(self, store):
        """Test close saves all data files."""
        await store.connect()
        await store.add_agent("test.topic", {"name": "test-agent"})
        await store.save_result("task-1", {"result": "data"})
        await store.save_metric({"event": "test"})
        await store.save_config("key", "value")

        await store.close()

        # Verify files exist and contain data
        assert store.agents_file.exists()
        assert store.results_file.exists()
        assert store.metrics_file.exists()
        assert store.config_file.exists()

    @pytest.mark.asyncio
    async def test_close_atomic_writes(self, store):
        """Test close uses atomic file writes."""
        await store.connect()
        await store.add_agent("test.topic", {"name": "test-agent"})

        await store.close()

        # Verify no .tmp files remain
        tmp_files = list(store.storage_dir.glob("*.tmp"))
        assert len(tmp_files) == 0


class TestJSONStoreHealthCheck:
    """Test suite for JSONStore health check operations."""

    @pytest.mark.asyncio
    async def test_health_check_success(self, store):
        """Test successful health check."""
        await store.connect()
        health = await store.health_check()

        assert health["status"] == "healthy"
        assert health["backend"] == "json"

    @pytest.mark.asyncio
    async def test_health_check_includes_status(self, store):
        """Test health_check includes status."""
        await store.connect()
        health = await store.health_check()

        assert "status" in health
        assert health["status"] in ["healthy", "unhealthy"]

    @pytest.mark.asyncio
    async def test_health_check_includes_counts(self, store):
        """Test health_check includes data counts."""
        await store.connect()
        await store.add_agent("test.topic", {"name": "agent1"})
        await store.save_result("task-1", {"result": "data"})
        await store.save_metric({"event": "test"})

        health = await store.health_check()

        assert "agents_count" in health
        assert "results_count" in health
        assert "metrics_count" in health
        assert health["agents_count"] == 1
        assert health["results_count"] == 1
        assert health["metrics_count"] == 1

    @pytest.mark.asyncio
    async def test_health_check_handles_errors(self, store, temp_storage_dir):
        """Test health_check handles file errors."""
        # Make storage directory read-only to cause write error
        os.chmod(temp_storage_dir, 0o444)

        try:
            health = await store.health_check()
            assert health["status"] == "unhealthy"
            assert "error" in health
        finally:
            os.chmod(temp_storage_dir, 0o755)


class TestJSONStoreAgentCRUD:
    """Test suite for JSONStore agent CRUD operations."""

    @pytest.mark.asyncio
    async def test_add_agent_success(self, store):
        """Test successful agent addition."""
        await store.connect()
        await store.add_agent(
            "test.topic", {"name": "test-agent", "callback_name": "callback"}
        )

        agent = await store.get_agent("test.topic", "test-agent")
        assert agent is not None
        assert agent["name"] == "test-agent"

    @pytest.mark.asyncio
    async def test_add_agent_upsert(self, store):
        """Test add_agent updates existing agent."""
        await store.connect()
        await store.add_agent(
            "test.topic", {"name": "test-agent", "callback_name": "callback1"}
        )
        await store.add_agent(
            "test.topic", {"name": "test-agent", "callback_name": "callback2"}
        )

        agents = await store.get_agents_by_topic("test.topic")
        assert len(agents) == 1
        assert agents[0]["callback_name"] == "callback2"

    @pytest.mark.asyncio
    async def test_add_agent_creates_topic(self, store):
        """Test add_agent creates topic if needed."""
        await store.connect()
        await store.add_agent("new.topic", {"name": "agent1"})

        agents = await store.get_agents_by_topic("new.topic")
        assert len(agents) == 1

    @pytest.mark.asyncio
    async def test_add_agent_missing_name(self, store):
        """Test add_agent fails without name."""
        await store.connect()

        with pytest.raises(ValueError, match="Agent data must include 'name' field"):
            await store.add_agent("test.topic", {"callback_name": "callback"})

    @pytest.mark.asyncio
    async def test_get_agent_success(self, store):
        """Test successful agent retrieval."""
        await store.connect()
        await store.add_agent("test.topic", {"name": "test-agent", "tools": ["tool1"]})

        agent = await store.get_agent("test.topic", "test-agent")
        assert agent is not None
        assert agent["name"] == "test-agent"
        assert agent["tools"] == ["tool1"]

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, store):
        """Test get_agent returns None if not found."""
        await store.connect()
        agent = await store.get_agent("test.topic", "nonexistent")
        assert agent is None

    @pytest.mark.asyncio
    async def test_get_agents_by_topic_success(self, store):
        """Test successful agents by topic retrieval."""
        await store.connect()
        await store.add_agent("test.topic", {"name": "agent1"})
        await store.add_agent("test.topic", {"name": "agent2"})

        agents = await store.get_agents_by_topic("test.topic")
        assert len(agents) == 2

    @pytest.mark.asyncio
    async def test_get_agents_by_topic_empty(self, store):
        """Test get_agents_by_topic with no agents."""
        await store.connect()
        agents = await store.get_agents_by_topic("test.topic")
        assert agents == []

    @pytest.mark.asyncio
    async def test_list_all_agents_success(self, store):
        """Test successful all agents listing."""
        await store.connect()
        await store.add_agent("topic1", {"name": "agent1"})
        await store.add_agent("topic2", {"name": "agent2"})

        all_agents = await store.list_all_agents()
        assert "topic1" in all_agents
        assert "topic2" in all_agents
        assert len(all_agents["topic1"]) == 1
        assert len(all_agents["topic2"]) == 1

    @pytest.mark.asyncio
    async def test_list_all_agents_empty(self, store):
        """Test list_all_agents with no agents."""
        await store.connect()
        all_agents = await store.list_all_agents()
        assert all_agents == {}

    @pytest.mark.asyncio
    async def test_delete_agent_success(self, store):
        """Test successful agent deletion."""
        await store.connect()
        await store.add_agent("test.topic", {"name": "test-agent"})

        deleted = await store.delete_agent("test.topic", "test-agent")
        assert deleted is True

        agent = await store.get_agent("test.topic", "test-agent")
        assert agent is None

    @pytest.mark.asyncio
    async def test_delete_agent_not_found(self, store):
        """Test delete_agent handles not found."""
        await store.connect()
        deleted = await store.delete_agent("test.topic", "nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_delete_agent_removes_empty_topic(self, store):
        """Test delete_agent removes empty topic."""
        await store.connect()
        await store.add_agent("test.topic", {"name": "test-agent"})
        await store.delete_agent("test.topic", "test-agent")

        all_agents = await store.list_all_agents()
        assert "test.topic" not in all_agents

    @pytest.mark.asyncio
    async def test_delete_topic_success(self, store):
        """Test successful topic deletion."""
        await store.connect()
        await store.add_agent("test.topic", {"name": "agent1"})
        await store.add_agent("test.topic", {"name": "agent2"})

        count = await store.delete_topic("test.topic")
        assert count == 2

        agents = await store.get_agents_by_topic("test.topic")
        assert len(agents) == 0

    @pytest.mark.asyncio
    async def test_delete_topic_returns_count(self, store):
        """Test delete_topic returns agent count."""
        await store.connect()
        await store.add_agent("test.topic", {"name": "agent1"})
        await store.add_agent("test.topic", {"name": "agent2"})
        await store.add_agent("test.topic", {"name": "agent3"})

        count = await store.delete_topic("test.topic")
        assert count == 3

    @pytest.mark.asyncio
    async def test_delete_topic_empty(self, store):
        """Test delete_topic with no agents."""
        await store.connect()
        count = await store.delete_topic("test.topic")
        assert count == 0

    @pytest.mark.asyncio
    async def test_clear_agents_success(self, store):
        """Test successful agents clearing."""
        await store.connect()
        await store.add_agent("topic1", {"name": "agent1"})
        await store.add_agent("topic2", {"name": "agent2"})

        count = await store.clear_agents()
        assert count == 2

        all_agents = await store.list_all_agents()
        assert all_agents == {}


class TestJSONStoreResultCRUD:
    """Test suite for JSONStore result CRUD operations."""

    @pytest.mark.asyncio
    async def test_save_result_success(self, store):
        """Test successful result save."""
        await store.connect()
        await store.save_result("task-1", {"result": "data", "status": "success"})

        result = await store.get_result("task-1")
        assert result is not None
        assert result["result"] == "data"
        assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_save_result_with_ttl(self, store):
        """Test save_result with TTL."""
        await store.connect()
        await store.save_result("task-1", {"result": "data"}, ttl_seconds=1)

        result = await store.get_result("task-1")
        assert result is not None

        # Wait for expiration
        time.sleep(1.1)

        result = await store.get_result("task-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_save_result_without_ttl(self, store):
        """Test save_result without TTL."""
        await store.connect()
        await store.save_result("task-1", {"result": "data"})

        # Wait a bit
        time.sleep(0.1)

        result = await store.get_result("task-1")
        assert result is not None

    @pytest.mark.asyncio
    async def test_get_result_success(self, store):
        """Test successful result retrieval."""
        await store.connect()
        await store.save_result("task-1", {"result": "test data"})

        result = await store.get_result("task-1")
        assert result == {"result": "test data"}

    @pytest.mark.asyncio
    async def test_get_result_expired(self, store):
        """Test get_result returns None for expired results."""
        await store.connect()
        await store.save_result("task-1", {"result": "data"}, ttl_seconds=0.1)

        time.sleep(0.2)

        result = await store.get_result("task-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_result_not_found(self, store):
        """Test get_result returns None if not found."""
        await store.connect()
        result = await store.get_result("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_result_success(self, store):
        """Test successful result deletion."""
        await store.connect()
        await store.save_result("task-1", {"result": "data"})

        deleted = await store.delete_result("task-1")
        assert deleted is True

        result = await store.get_result("task-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_result_not_found(self, store):
        """Test delete_result handles not found."""
        await store.connect()
        deleted = await store.delete_result("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_list_results_success(self, store):
        """Test successful result listing."""
        await store.connect()
        await store.save_result("task-1", {"result": "data1"})
        await store.save_result("task-2", {"result": "data2"})

        results = await store.list_results()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_results_sorted(self, store):
        """Test list_results returns sorted by saved_at."""
        await store.connect()
        await store.save_result("task-1", {"result": "data1"})
        time.sleep(0.01)
        await store.save_result("task-2", {"result": "data2"})

        results = await store.list_results()
        assert results[0]["task_id"] == "task-2"  # Most recent first
        assert results[1]["task_id"] == "task-1"

    @pytest.mark.asyncio
    async def test_list_results_with_limit(self, store):
        """Test list_results respects limit."""
        await store.connect()
        for i in range(10):
            await store.save_result(f"task-{i}", {"result": f"data{i}"})

        results = await store.list_results(limit=5)
        assert len(results) == 5

    @pytest.mark.asyncio
    async def test_clear_results_success(self, store):
        """Test successful results clearing."""
        await store.connect()
        await store.save_result("task-1", {"result": "data1"})
        await store.save_result("task-2", {"result": "data2"})

        count = await store.clear_results()
        assert count == 2

        results = await store.list_results()
        assert len(results) == 0


class TestJSONStoreMetric:
    """Test suite for JSONStore metric operations."""

    @pytest.mark.asyncio
    async def test_save_metric_success(self, store):
        """Test successful metric save."""
        await store.connect()
        await store.save_metric({"topic": "test.topic", "event": "processed"})

        metrics = await store.get_metrics()
        assert len(metrics) == 1
        assert metrics[0]["event"] == "processed"

    @pytest.mark.asyncio
    async def test_save_metric_adds_timestamp(self, store):
        """Test save_metric adds saved_at timestamp."""
        await store.connect()
        await store.save_metric({"topic": "test.topic", "event": "processed"})

        metrics = await store.get_metrics()
        assert "saved_at" in metrics[0]

    @pytest.mark.asyncio
    async def test_save_metric_limits_size(self, store):
        """Test save_metric limits metrics list size."""
        await store.connect()
        # Directly manipulate internal state to test limit without slow file I/O
        # Add 10001 metrics directly to _metrics list (using lock for thread safety)
        with store._lock:
            for i in range(10001):
                store._metrics.append(
                    {
                        "topic": "test.topic",
                        "event": f"event{i}",
                        "saved_at": time.time(),
                    }
                )

        # Now save one more metric - this should trigger the limit check (10001 > 10000)
        await store.save_metric({"topic": "test.topic", "event": "trigger_limit"})

        metrics = await store.get_metrics()
        assert len(metrics) <= 10000
        # Verify the oldest metrics were removed (should be exactly 10000 now)
        with store._lock:
            assert len(store._metrics) == 10000

    @pytest.mark.asyncio
    async def test_get_metrics_success(self, store):
        """Test successful metrics retrieval."""
        await store.connect()
        await store.save_metric({"topic": "test.topic", "event": "event1"})
        await store.save_metric({"topic": "test.topic", "event": "event2"})

        metrics = await store.get_metrics()
        assert len(metrics) == 2

    @pytest.mark.asyncio
    async def test_get_metrics_with_topic_filter(self, store):
        """Test get_metrics with topic filter."""
        await store.connect()
        await store.save_metric({"topic": "topic1", "event": "event1"})
        await store.save_metric({"topic": "topic2", "event": "event2"})

        metrics = await store.get_metrics(topic="topic1")
        assert len(metrics) == 1
        assert metrics[0]["topic"] == "topic1"

    @pytest.mark.asyncio
    async def test_get_metrics_with_limit(self, store):
        """Test get_metrics respects limit."""
        await store.connect()
        for i in range(10):
            await store.save_metric({"topic": "test.topic", "event": f"event{i}"})

        metrics = await store.get_metrics(limit=5)
        assert len(metrics) == 5

    @pytest.mark.asyncio
    async def test_get_metrics_reversed(self, store):
        """Test get_metrics returns reversed order."""
        await store.connect()
        await store.save_metric({"topic": "test.topic", "event": "event1"})
        time.sleep(0.01)
        await store.save_metric({"topic": "test.topic", "event": "event2"})

        metrics = await store.get_metrics()
        assert metrics[0]["event"] == "event2"  # Most recent first

    @pytest.mark.asyncio
    async def test_clear_metrics_success(self, store):
        """Test successful metrics clearing."""
        await store.connect()
        await store.save_metric({"topic": "test.topic", "event": "event1"})
        await store.save_metric({"topic": "test.topic", "event": "event2"})

        count = await store.clear_metrics()
        assert count == 2

        metrics = await store.get_metrics()
        assert len(metrics) == 0


class TestJSONStoreConfig:
    """Test suite for JSONStore config operations."""

    @pytest.mark.asyncio
    async def test_save_config_success(self, store):
        """Test successful config save."""
        await store.connect()
        await store.save_config("key1", "value1")

        value = await store.get_config("key1")
        assert value == "value1"

    @pytest.mark.asyncio
    async def test_get_config_success(self, store):
        """Test successful config retrieval."""
        await store.connect()
        await store.save_config("key1", {"nested": "value"})

        value = await store.get_config("key1")
        assert value == {"nested": "value"}

    @pytest.mark.asyncio
    async def test_get_config_default(self, store):
        """Test get_config returns default if not found."""
        await store.connect()
        value = await store.get_config("nonexistent", default="default_value")
        assert value == "default_value"

    @pytest.mark.asyncio
    async def test_get_config_not_found(self, store):
        """Test get_config returns None if not found and no default."""
        await store.connect()
        value = await store.get_config("nonexistent")
        assert value is None


class TestJSONStoreClearAll:
    """Test suite for JSONStore clear_all operations."""

    @pytest.mark.asyncio
    async def test_clear_all_success(self, store):
        """Test successful clear_all."""
        await store.connect()
        await store.add_agent("test.topic", {"name": "agent1"})
        await store.save_result("task-1", {"result": "data"})
        await store.save_metric({"event": "test"})
        await store.save_config("key", "value")

        counts = await store.clear_all()

        assert counts["agents"] == 1
        assert counts["results"] == 1
        assert counts["metrics"] == 1
        assert counts["config"] == 1

    @pytest.mark.asyncio
    async def test_clear_all_returns_counts(self, store):
        """Test clear_all returns all counts."""
        await store.connect()
        await store.add_agent("topic1", {"name": "agent1"})
        await store.add_agent("topic2", {"name": "agent2"})
        await store.save_result("task-1", {"result": "data"})
        await store.save_metric({"event": "test"})
        await store.save_config("key1", "value1")
        await store.save_config("key2", "value2")

        counts = await store.clear_all()

        assert "agents" in counts
        assert "results" in counts
        assert "metrics" in counts
        assert "config" in counts
        assert counts["agents"] == 2
        assert counts["config"] == 2

    @pytest.mark.asyncio
    async def test_clear_all_removes_config(self, store):
        """Test clear_all removes config."""
        await store.connect()
        await store.save_config("key", "value")

        await store.clear_all()

        value = await store.get_config("key")
        assert value is None


class TestJSONStoreThreadSafety:
    """Test suite for JSONStore thread safety."""

    @pytest.mark.asyncio
    async def test_concurrent_add_agent(self, store):
        """Test concurrent agent additions."""
        await store.connect()

        import asyncio

        async def add_agent(i):
            await store.add_agent("test.topic", {"name": f"agent{i}"})

        tasks = [add_agent(i) for i in range(10)]
        await asyncio.gather(*tasks)

        agents = await store.get_agents_by_topic("test.topic")
        assert len(agents) == 10

    @pytest.mark.asyncio
    async def test_concurrent_save_result(self, store):
        """Test concurrent result saves."""
        await store.connect()

        import asyncio

        async def save_result(i):
            await store.save_result(f"task-{i}", {"result": f"data{i}"})

        tasks = [save_result(i) for i in range(10)]
        await asyncio.gather(*tasks)

        results = await store.list_results()
        assert len(results) == 10

    @pytest.mark.asyncio
    async def test_concurrent_save_metric(self, store):
        """Test concurrent metric saves."""
        await store.connect()

        import asyncio

        async def save_metric(i):
            await store.save_metric({"topic": "test.topic", "event": f"event{i}"})

        tasks = [save_metric(i) for i in range(10)]
        await asyncio.gather(*tasks)

        metrics = await store.get_metrics()
        assert len(metrics) == 10
