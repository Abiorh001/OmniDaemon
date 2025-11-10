"""
Abstract base class for all storage backends.

Defines the contract that all storage implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class BaseStore(ABC):
    """
    Abstract storage interface for OmniDaemon.

    This abstract base class defines the contract that all storage backends must
    implement. It provides a unified interface for managing agents, results, metrics,
    and configuration across different storage implementations (JSON, Redis, etc.).

    All storage backends must implement all abstract methods to ensure compatibility
    with the OmniDaemon system.

    Note:
        All methods are async and should be implemented as coroutines.
    """

    @abstractmethod
    async def connect(self) -> None:
        """
        Establish connection to the storage backend.

        This method should initialize the connection to the underlying storage system.
        It should be idempotent - calling it multiple times should be safe.

        Raises:
            ConnectionError: If connection to the storage backend fails
        """
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """
        Close connection and cleanup resources.

        This method should gracefully close all connections, flush any pending writes,
        and release resources. It should be idempotent.

        Note:
            After calling close(), the storage should be reconnected via connect()
            before use.
        """
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Check storage backend health and status.

        This method performs a health check operation to verify the storage backend
        is accessible and functioning correctly.

        Returns:
            Dictionary containing health status information:
                - status: "healthy" or "unhealthy"
                - backend: Storage backend type (e.g., "json", "redis")
                - Additional backend-specific fields (latency, version, etc.)
        """
        raise NotImplementedError

    @abstractmethod
    async def add_agent(self, topic: str, agent_data: Dict[str, Any]) -> None:
        """
        Add or update an agent for a topic.

        This method implements upsert behavior - if an agent with the same name
        exists for the topic, it will be replaced with the new data.

        Args:
            topic: The topic name the agent subscribes to
            agent_data: Dictionary containing agent metadata:
                - name: Agent name/identifier (required)
                - callback_name: Optional callback function name
                - tools: Optional list of tools available to the agent
                - description: Optional agent description
                - config: Optional agent configuration dictionary

        Raises:
            ValueError: If agent_data is missing required fields (e.g., 'name')
        """
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

    @abstractmethod
    async def save_result(
        self, task_id: str, result: Dict[str, Any], ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Save task result with optional time-to-live.

        This method stores the result of a completed task, optionally with an
        expiration time. Results can be retrieved later using get_result().

        Args:
            task_id: Unique task identifier
            result: Dictionary containing task result data
            ttl_seconds: Optional time-to-live in seconds. If None, the result
                        will not expire automatically. If specified, the result
                        will be automatically deleted after this duration.
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
        raise NotImplementedError

    @abstractmethod
    async def delete_result(self, task_id: str) -> bool:
        """
        Delete a task result.

        Args:
            task_id: The task ID

        Returns:
            True if deleted, False if not found
        """
        raise NotImplementedError

    @abstractmethod
    async def list_results(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List recent task results.

        Args:
            limit: Maximum number of results to return

        Returns:
            List of result dictionaries
        """
        raise NotImplementedError

    @abstractmethod
    async def save_metric(self, metric_data: Dict[str, Any]) -> None:
        """
        Save a metric event for monitoring and analytics.

        This method stores a metric event that can be used for monitoring agent
        performance, tracking events, and generating analytics.

        Args:
            metric_data: Dictionary containing metric information:
                - topic: The topic name
                - agent: The agent name
                - event: Event type (e.g., "task_received", "task_processed", "task_failed")
                - timestamp: Event timestamp
                - Additional event-specific fields (processing_time_sec, error, etc.)
        """
        raise NotImplementedError

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
        raise NotImplementedError

    @abstractmethod
    async def save_config(self, key: str, value: Any) -> None:
        """
        Save a configuration value.

        This method stores a configuration key-value pair that persists across
        sessions. Values are automatically JSON-serialized.

        Args:
            key: Configuration key (string identifier)
            value: Configuration value (any JSON-serializable type)
        """
        raise NotImplementedError

    @abstractmethod
    async def get_config(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a configuration value.

        This method retrieves a previously stored configuration value. If the
        key doesn't exist, it returns the default value.

        Args:
            key: Configuration key to retrieve
            default: Default value to return if key is not found

        Returns:
            The configuration value (deserialized from JSON) or the default value
        """
        pass

    @abstractmethod
    async def clear_agents(self) -> int:
        """
        Delete all agent registrations.

        Returns:
            Number of agents deleted
        """
        raise NotImplementedError

    @abstractmethod
    async def clear_results(self) -> int:
        """
        Delete all task results.

        Returns:
            Number of results deleted
        """
        raise NotImplementedError

    @abstractmethod
    async def clear_metrics(self) -> int:
        """
        Delete all metrics.

        Returns:
            Number of metrics deleted
        """
        raise NotImplementedError

    @abstractmethod
    async def clear_all(self) -> Dict[str, int]:
        """
        Clear all data from storage.

        This method removes all agents, results, metrics, and configuration
        from the storage backend. Use with caution!

        Returns:
            Dictionary with counts of deleted items by category:
                - agents: Number of agents deleted
                - results: Number of results deleted
                - metrics: Number of metrics deleted
                - config: Number of config entries deleted
        """
        raise NotImplementedError
