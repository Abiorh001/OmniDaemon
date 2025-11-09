"""
Abstract base class for all storage backends.

Defines the contract that all storage implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseStore(ABC):
    """
    Abstract storage interface for OmniDaemon.

    All storage backends (JSON, Redis) must implement these methods.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the storage backend."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close connection and cleanup resources."""
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Check storage backend health.

        Returns:
            Dict with status, latency, etc.
        """
        pass

    @abstractmethod
    async def add_agent(self, topic: str, agent_data: Dict[str, Any]) -> None:
        """
        Add or update an agent for a topic.

        If agent with same name exists, it replaces it (upsert behavior).

        Args:
            topic: The topic the agent subscribes to
            agent_data: Agent metadata (name, callback_name, tools, description, config)
        """
        pass

    @abstractmethod
    async def get_agent(self, topic: str, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific agent by topic and name.

        Args:
            topic: The topic
            agent_name: The agent name

        Returns:
            Agent data or None if not found
        """
        pass

    @abstractmethod
    async def get_agents_by_topic(self, topic: str) -> List[Dict[str, Any]]:
        """
        Get all agents subscribed to a topic.

        Args:
            topic: The topic

        Returns:
            List of agent data dictionaries
        """
        pass

    @abstractmethod
    async def list_all_agents(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all registered agents grouped by topic.

        Returns:
            Dictionary mapping topics to lists of agents
        """
        pass

    @abstractmethod
    async def delete_agent(self, topic: str, agent_name: str) -> bool:
        """
        Delete a specific agent.

        Args:
            topic: The topic
            agent_name: The agent name

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def delete_topic(self, topic: str) -> int:
        """
        Delete all agents for a topic.

        Args:
            topic: The topic

        Returns:
            Number of agents deleted
        """
        pass

    @abstractmethod
    async def save_result(
        self, task_id: str, result: Dict[str, Any], ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Save task result.

        Args:
            task_id: Unique task identifier
            result: Task result data
            ttl_seconds: Optional TTL for auto-expiration (None = no expiration)
        """
        pass

    @abstractmethod
    async def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve task result.

        Args:
            task_id: The task ID

        Returns:
            Result data or None if not found
        """
        pass

    @abstractmethod
    async def delete_result(self, task_id: str) -> bool:
        """
        Delete a task result.

        Args:
            task_id: The task ID

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def list_results(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List recent task results.

        Args:
            limit: Maximum number of results to return

        Returns:
            List of result dictionaries
        """
        pass

    @abstractmethod
    async def save_metric(self, metric_data: Dict[str, Any]) -> None:
        """
        Save a metric event.

        Args:
            metric_data: Metric information (topic, event, timestamp, etc.)
        """
        pass

    @abstractmethod
    async def get_metrics(
        self, topic: Optional[str] = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Retrieve metrics.

        Args:
            topic: Optional topic filter
            limit: Maximum number of metrics to return

        Returns:
            List of metric dictionaries
        """
        pass

    @abstractmethod
    async def save_config(self, key: str, value: Any) -> None:
        """
        Save a configuration value.

        Args:
            key: Configuration key
            value: Configuration value (will be JSON-serialized)
        """
        pass

    @abstractmethod
    async def get_config(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a configuration value.

        Args:
            key: Configuration key
            default: Default value if not found

        Returns:
            Configuration value or default
        """
        pass

    @abstractmethod
    async def clear_agents(self) -> int:
        """
        Delete all agent registrations.

        Returns:
            Number of agents deleted
        """
        pass

    @abstractmethod
    async def clear_results(self) -> int:
        """
        Delete all task results.

        Returns:
            Number of results deleted
        """
        pass

    @abstractmethod
    async def clear_metrics(self) -> int:
        """
        Delete all metrics.

        Returns:
            Number of metrics deleted
        """
        pass

    @abstractmethod
    async def clear_all(self) -> Dict[str, int]:
        """
        Clear all data from storage.

        Returns:
            Dictionary with counts of deleted items by category
        """
        pass
