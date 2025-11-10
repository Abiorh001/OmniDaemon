"""
JSON-based storage implementation for local development and testing.

Stores all data in JSON files on disk.
"""

import json
import os
from typing import Dict, Any, List, Optional
from threading import RLock
from pathlib import Path
import time

from omnidaemon.storage.base import BaseStore


class JSONStore(BaseStore):
    """
    File-based storage implementation using JSON files.

    This implementation stores all data in JSON files on the local filesystem.
    It provides thread-safe operations with atomic file writes using temporary
    files and atomic replacements.

    Features:
        - Thread-safe: Uses RLock for concurrent access protection
        - Atomic writes: Uses temporary files and os.replace() for atomicity
        - Buffered metrics: Metrics are batched to reduce I/O operations
        - Automatic expiration: Results with TTL are checked on retrieval

    Best for:
        - Development and testing environments
        - Single-instance deployments
        - Local development setups

    Args:
        storage_dir: Directory path to store JSON files (default: ".omnidaemon_data")

    Attributes:
        storage_dir: Path object for the storage directory
        agents_file: Path to agents.json file
        results_file: Path to results.json file
        metrics_file: Path to metrics.json file
        config_file: Path to config.json file
        _agents: In-memory dictionary of agents by topic
        _results: In-memory dictionary of task results
        _metrics: In-memory list of metrics
        _config: In-memory dictionary of configuration
        _lock: Thread lock for synchronization
        _connected: Whether storage is connected
        _metrics_dirty: Whether metrics need to be saved
        _metrics_write_threshold: Number of metrics before auto-save
        _metrics_pending_count: Count of unsaved metrics
    """

    def __init__(self, storage_dir: str = ".omnidaemon_data") -> None:
        """
        Initialize JSON storage backend.

        Args:
            storage_dir: Directory path to store JSON files. Will be created if
                       it doesn't exist (default: ".omnidaemon_data")
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(exist_ok=True)

        self.agents_file = self.storage_dir / "agents.json"
        self.results_file = self.storage_dir / "results.json"
        self.metrics_file = self.storage_dir / "metrics.json"
        self.config_file = self.storage_dir / "config.json"

        self._agents: Dict[str, List[Dict[str, Any]]] = {}
        self._results: Dict[str, Dict[str, Any]] = {}
        self._metrics: List[Dict[str, Any]] = []
        self._config: Dict[str, Any] = {}

        self._lock = RLock()
        self._connected = False

        self._metrics_dirty = False
        self._metrics_write_threshold = 100
        self._metrics_pending_count = 0

    async def connect(self) -> None:
        """
        Load data from JSON files into memory.

        This method reads all JSON files (agents, results, metrics, config) and
        loads them into memory. It is idempotent and thread-safe.

        Note:
            If files don't exist or are corrupted, empty data structures are initialized.
        """
        if self._connected:
            return

        with self._lock:
            self._load_agents()
            self._load_results()
            self._load_metrics()
            self._load_config()
            self._connected = True

    async def close(self) -> None:
        """
        Flush all data to disk and mark as disconnected.

        This method saves all in-memory data (agents, results, metrics, config)
        to their respective JSON files using atomic writes. It ensures all pending
        metrics are written before closing.
        """
        with self._lock:
            self._save_agents()
            self._save_results()
            if self._metrics_dirty or self._metrics_pending_count > 0:
                self._save_metrics()
                self._metrics_dirty = False
                self._metrics_pending_count = 0
            self._save_config()
            self._connected = False

    async def health_check(self) -> Dict[str, Any]:
        """
        Check storage health by testing file system access.

        This method performs a health check by attempting to create and delete
        a test file in the storage directory.

        Returns:
            Dictionary containing:
                - status: "healthy" or "unhealthy"
                - backend: "json"
                - storage_dir: Path to storage directory
                - connected: Whether storage is connected
                - agents_count: Total number of registered agents
                - results_count: Total number of stored results
                - metrics_count: Total number of stored metrics
                - error: Error message if unhealthy
        """
        try:
            test_file = self.storage_dir / ".health_check"
            test_file.write_text("ok")
            test_file.unlink()

            return {
                "status": "healthy",
                "backend": "json",
                "storage_dir": str(self.storage_dir),
                "connected": self._connected,
                "agents_count": sum(len(agents) for agents in self._agents.values()),
                "results_count": len(self._results),
                "metrics_count": len(self._metrics),
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "backend": "json",
                "error": str(e),
            }

    def _load_agents(self) -> None:
        """
        Load agents from agents.json file into memory.

        This is a private method that reads the agents.json file and populates
        the _agents dictionary. If the file doesn't exist or is corrupted, an
        empty dictionary is initialized.
        """
        if self.agents_file.exists():
            try:
                with open(self.agents_file, "r", encoding="utf-8") as f:
                    self._agents = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self._agents = {}

    def _save_agents(self) -> None:
        """
        Save agents to file atomically using temporary file.

        This is a private method that writes the _agents dictionary to agents.json
        using an atomic write pattern (write to temp file, then replace).
        """
        tmp_file = self.agents_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self._agents, f, indent=2, default=str)
        os.replace(tmp_file, self.agents_file)

    def _load_results(self):
        """Load results from file."""
        if self.results_file.exists():
            try:
                with open(self.results_file, "r", encoding="utf-8") as f:
                    self._results = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self._results = {}

    def _save_results(self):
        """Save results to file atomically."""
        tmp_file = self.results_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self._results, f, indent=2, default=str)
        os.replace(tmp_file, self.results_file)

    def _load_metrics(self):
        """Load metrics from file."""
        if self.metrics_file.exists():
            try:
                with open(self.metrics_file, "r", encoding="utf-8") as f:
                    self._metrics = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self._metrics = []

    def _save_metrics(self):
        """Save metrics to file atomically."""
        tmp_file = self.metrics_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self._metrics, f, indent=2, default=str)
        os.replace(tmp_file, self.metrics_file)

    def _load_config(self):
        """Load config from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self._config = {}

    def _save_config(self):
        """Save config to file atomically."""
        tmp_file = self.config_file.with_suffix(".tmp")
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2, default=str)
        os.replace(tmp_file, self.config_file)

    async def add_agent(self, topic: str, agent_data: Dict[str, Any]) -> None:
        """
        Add or update an agent for a topic (upsert behavior).

        This method implements upsert behavior - if an agent with the same name
        exists for the topic, it is removed and replaced with the new data.

        Args:
            topic: The topic name the agent subscribes to
            agent_data: Dictionary containing agent metadata (must include 'name')

        Raises:
            ValueError: If agent_data is missing the 'name' field
        """
        with self._lock:
            agent_name = agent_data.get("name")
            if not agent_name:
                raise ValueError("Agent data must include 'name' field")

            if topic not in self._agents:
                self._agents[topic] = []

            self._agents[topic] = [
                a for a in self._agents[topic] if a.get("name") != agent_name
            ]

            self._agents[topic].append(agent_data)
            self._save_agents()

    async def get_agent(self, topic: str, agent_name: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific agent by topic and name.

        Args:
            topic: The topic name
            agent_name: The agent name/identifier

        Returns:
            A copy of the agent data dictionary, or None if not found
        """
        with self._lock:
            for agent in self._agents.get(topic, []):
                if agent.get("name") == agent_name:
                    return agent.copy()
            return None

    async def get_agents_by_topic(self, topic: str) -> List[Dict[str, Any]]:
        """
        Get all agents subscribed to a topic.

        Args:
            topic: The topic name

        Returns:
            List of agent data dictionaries (copies) for the topic
        """
        with self._lock:
            return [a.copy() for a in self._agents.get(topic, [])]

    async def list_all_agents(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get all registered agents grouped by topic.

        Returns:
            Dictionary mapping topic names to lists of agent data dictionaries
        """
        with self._lock:
            return {
                topic: [a.copy() for a in agents]
                for topic, agents in self._agents.items()
            }

    async def delete_agent(self, topic: str, agent_name: str) -> bool:
        """Delete a specific agent."""
        with self._lock:
            if topic not in self._agents:
                return False

            original_len = len(self._agents[topic])
            self._agents[topic] = [
                a for a in self._agents[topic] if a.get("name") != agent_name
            ]

            if not self._agents[topic]:
                del self._agents[topic]

            deleted = len(self._agents.get(topic, [])) < original_len
            if deleted:
                self._save_agents()

            return deleted

    async def delete_topic(self, topic: str) -> int:
        """Delete all agents for a topic."""
        with self._lock:
            if topic not in self._agents:
                return 0

            count = len(self._agents[topic])
            del self._agents[topic]
            self._save_agents()
            return count

    async def save_result(
        self, task_id: str, result: Dict[str, Any], ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Save task result with optional expiration.

        Args:
            task_id: Unique task identifier
            result: Dictionary containing task result data
            ttl_seconds: Optional time-to-live in seconds. If specified, the result
                        will include an expires_at timestamp for later cleanup.
        """
        with self._lock:
            result_data = {
                "task_id": task_id,
                "result": result,
                "saved_at": time.time(),
            }
            if ttl_seconds:
                result_data["expires_at"] = time.time() + ttl_seconds

            self._results[task_id] = result_data
            self._save_results()

    async def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task result, automatically checking and removing expired results.

        Args:
            task_id: The task ID to retrieve

        Returns:
            The result data dictionary, or None if not found or expired
        """
        with self._lock:
            result_data = self._results.get(task_id)
            if not result_data:
                return None

            expires_at = result_data.get("expires_at")
            if expires_at and time.time() > expires_at:
                del self._results[task_id]
                self._save_results()
                return None

            return result_data["result"]

    async def delete_result(self, task_id: str) -> bool:
        """Delete a task result."""
        with self._lock:
            if task_id in self._results:
                del self._results[task_id]
                self._save_results()
                return True
            return False

    async def list_results(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List recent results."""
        with self._lock:
            sorted_results = sorted(
                self._results.items(),
                key=lambda x: x[1].get("saved_at", 0),
                reverse=True,
            )
            return [
                {"task_id": task_id, **data} for task_id, data in sorted_results[:limit]
            ]

    async def save_metric(self, metric_data: Dict[str, Any]) -> None:
        """
        Save a metric event with buffered writes.

        This method adds a timestamp and appends the metric to the in-memory list.
        Metrics are automatically saved to disk when the threshold is reached,
        or when close() is called.

        Args:
            metric_data: Dictionary containing metric information

        Note:
            - Metrics list is capped at 10,000 entries (oldest are removed)
            - Auto-saves when _metrics_write_threshold (100) metrics are pending
        """
        with self._lock:
            metric_data["saved_at"] = time.time()
            self._metrics.append(metric_data)
            self._metrics_pending_count += 1
            self._metrics_dirty = True

            if len(self._metrics) > 10000:
                self._metrics = self._metrics[-10000:]

            if self._metrics_pending_count >= self._metrics_write_threshold:
                self._save_metrics()
                self._metrics_pending_count = 0
                self._metrics_dirty = False

    async def get_metrics(
        self, topic: Optional[str] = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """
        Get metrics, optionally filtered by topic.

        Args:
            topic: Optional topic name to filter metrics
            limit: Maximum number of metrics to return (default: 1000)

        Returns:
            List of metric dictionaries, most recent first. If topic is specified,
            only metrics for that topic are returned.
        """
        with self._lock:
            metrics = self._metrics

            if topic:
                metrics = [m for m in metrics if m.get("topic") == topic]

            return list(reversed(metrics[-limit:]))

    async def save_config(self, key: str, value: Any) -> None:
        """
        Save a configuration value.

        Args:
            key: Configuration key
            value: Configuration value (will be JSON-serialized)
        """
        with self._lock:
            self._config[key] = value
            self._save_config()

    async def get_config(self, key: str, default: Any = None) -> Any:
        """
        Get a configuration value.

        Args:
            key: Configuration key to retrieve
            default: Default value if key is not found

        Returns:
            The configuration value or the default value
        """
        with self._lock:
            return self._config.get(key, default)

    async def clear_agents(self) -> int:
        """Clear all agents."""
        with self._lock:
            count = sum(len(agents) for agents in self._agents.values())
            self._agents = {}
            self._save_agents()
            return count

    async def clear_results(self) -> int:
        """Clear all results."""
        with self._lock:
            count = len(self._results)
            self._results = {}
            self._save_results()
            return count

    async def clear_metrics(self) -> int:
        """Clear all metrics."""
        with self._lock:
            count = len(self._metrics)
            self._metrics = []
            self._save_metrics()
            return count

    async def clear_all(self) -> Dict[str, int]:
        """
        Clear all data from storage.

        This method removes all agents, results, metrics, and configuration,
        then saves the empty state to disk.

        Returns:
            Dictionary with counts of deleted items by category
        """
        agents_count = await self.clear_agents()
        results_count = await self.clear_results()
        metrics_count = await self.clear_metrics()

        with self._lock:
            config_count = len(self._config)
            self._config = {}
            self._save_config()

        return {
            "agents": agents_count,
            "results": results_count,
            "metrics": metrics_count,
            "config": config_count,
        }
