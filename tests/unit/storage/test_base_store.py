"""Unit tests for BaseStore abstract interface."""

import pytest
from omnidaemon.storage.base import BaseStore


class MockStore(BaseStore):
    """Concrete implementation for testing BaseStore interface."""

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def health_check(self):
        return {"status": "healthy"}

    async def add_agent(self, topic: str, agent_data: dict) -> None:
        pass

    async def get_agent(self, topic: str, agent_name: str):
        return None

    async def get_agents_by_topic(self, topic: str):
        return []

    async def list_all_agents(self):
        return {}

    async def delete_agent(self, topic: str, agent_name: str) -> bool:
        return False

    async def delete_topic(self, topic: str) -> int:
        return 0

    async def save_result(
        self, task_id: str, result: dict, ttl_seconds: int = None
    ) -> None:
        pass

    async def get_result(self, task_id: str):
        return None

    async def delete_result(self, task_id: str) -> bool:
        return False

    async def list_results(self, limit: int = 100):
        return []

    async def save_metric(self, metric_data: dict) -> None:
        pass

    async def get_metrics(self, topic: str = None, limit: int = 1000):
        return []

    async def save_config(self, key: str, value) -> None:
        pass

    async def get_config(self, key: str, default=None):
        return default

    async def clear_agents(self) -> int:
        return 0

    async def clear_results(self) -> int:
        return 0

    async def clear_metrics(self) -> int:
        return 0

    async def clear_all(self):
        return {"agents": 0, "results": 0, "metrics": 0, "config": 0}


class TestBaseStore:
    """Test suite for BaseStore abstract interface."""

    def test_base_store_is_abstract(self):
        """Verify BaseStore cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseStore()

    def test_base_store_has_connect_method(self):
        """Verify connect() abstract method exists."""
        assert hasattr(BaseStore, "connect")
        assert getattr(BaseStore.connect, "__isabstractmethod__", False)

    def test_base_store_has_close_method(self):
        """Verify close() abstract method exists."""
        assert hasattr(BaseStore, "close")
        assert getattr(BaseStore.close, "__isabstractmethod__", False)

    def test_base_store_has_health_check_method(self):
        """Verify health_check() abstract method exists."""
        assert hasattr(BaseStore, "health_check")
        assert getattr(BaseStore.health_check, "__isabstractmethod__", False)

    def test_base_store_has_agent_methods(self):
        """Verify all agent CRUD methods exist."""
        assert hasattr(BaseStore, "add_agent")
        assert hasattr(BaseStore, "get_agent")
        assert hasattr(BaseStore, "get_agents_by_topic")
        assert hasattr(BaseStore, "list_all_agents")
        assert hasattr(BaseStore, "delete_agent")
        assert hasattr(BaseStore, "delete_topic")
        assert hasattr(BaseStore, "clear_agents")

        # Verify they are abstract
        assert getattr(BaseStore.add_agent, "__isabstractmethod__", False)
        assert getattr(BaseStore.get_agent, "__isabstractmethod__", False)
        assert getattr(BaseStore.get_agents_by_topic, "__isabstractmethod__", False)
        assert getattr(BaseStore.list_all_agents, "__isabstractmethod__", False)
        assert getattr(BaseStore.delete_agent, "__isabstractmethod__", False)
        assert getattr(BaseStore.delete_topic, "__isabstractmethod__", False)
        assert getattr(BaseStore.clear_agents, "__isabstractmethod__", False)

    def test_base_store_has_result_methods(self):
        """Verify all result CRUD methods exist."""
        assert hasattr(BaseStore, "save_result")
        assert hasattr(BaseStore, "get_result")
        assert hasattr(BaseStore, "delete_result")
        assert hasattr(BaseStore, "list_results")
        assert hasattr(BaseStore, "clear_results")

        # Verify they are abstract
        assert getattr(BaseStore.save_result, "__isabstractmethod__", False)
        assert getattr(BaseStore.get_result, "__isabstractmethod__", False)
        assert getattr(BaseStore.delete_result, "__isabstractmethod__", False)
        assert getattr(BaseStore.list_results, "__isabstractmethod__", False)
        assert getattr(BaseStore.clear_results, "__isabstractmethod__", False)

    def test_base_store_has_metric_methods(self):
        """Verify all metric methods exist."""
        assert hasattr(BaseStore, "save_metric")
        assert hasattr(BaseStore, "get_metrics")
        assert hasattr(BaseStore, "clear_metrics")

        # Verify they are abstract
        assert getattr(BaseStore.save_metric, "__isabstractmethod__", False)
        assert getattr(BaseStore.get_metrics, "__isabstractmethod__", False)
        assert getattr(BaseStore.clear_metrics, "__isabstractmethod__", False)

    def test_base_store_has_config_methods(self):
        """Verify all config methods exist."""
        assert hasattr(BaseStore, "save_config")
        assert hasattr(BaseStore, "get_config")

        # Verify they are abstract
        assert getattr(BaseStore.save_config, "__isabstractmethod__", False)
        assert getattr(BaseStore.get_config, "__isabstractmethod__", False)

    @pytest.mark.asyncio
    async def test_concrete_implementation_required(self):
        """Verify concrete implementations must implement all methods."""
        # MockStore implements all methods, so it should work
        store = MockStore()
        await store.connect()
        await store.close()

        # Verify all methods are callable
        await store.health_check()
        await store.add_agent("test", {"name": "test"})
        await store.get_agent("test", "test")
        await store.get_agents_by_topic("test")
        await store.list_all_agents()
        await store.delete_agent("test", "test")
        await store.delete_topic("test")
        await store.save_result("task-1", {"result": "data"})
        await store.get_result("task-1")
        await store.delete_result("task-1")
        await store.list_results()
        await store.save_metric({"event": "test"})
        await store.get_metrics()
        await store.save_config("key", "value")
        await store.get_config("key")
        await store.clear_agents()
        await store.clear_results()
        await store.clear_metrics()
        await store.clear_all()
