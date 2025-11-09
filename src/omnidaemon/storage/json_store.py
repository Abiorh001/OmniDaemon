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
    File-based storage using JSON.

    Thread-safe with atomic file writes.
    Good for development, testing, and single-instance deployments.
    """

    def __init__(self, storage_dir: str = ".omnidaemon_data"):
        """
        Initialize JSON storage.

        Args:
            storage_dir: Directory to store JSON files
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

    async def connect(self) -> None:
        """Load data from files."""
        if self._connected:
            return

        with self._lock:
            self._load_agents()
            self._load_results()
            self._load_metrics()
            self._load_config()
            self._connected = True

    async def close(self) -> None:
        """Flush all data to disk."""
        with self._lock:
            self._save_agents()
            self._save_results()
            self._save_metrics()
            self._save_config()
            self._connected = False

    async def health_check(self) -> Dict[str, Any]:
        """Check storage health."""
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

    def _load_agents(self):
        """Load agents from file."""
        if self.agents_file.exists():
            try:
                with open(self.agents_file, "r", encoding="utf-8") as f:
                    self._agents = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                self._agents = {}

    def _save_agents(self):
        """Save agents to file atomically."""
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
        Add or update an agent.remove old, add new
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
        """Get a specific agent."""
        with self._lock:
            for agent in self._agents.get(topic, []):
                if agent.get("name") == agent_name:
                    return agent.copy()
            return None

    async def get_agents_by_topic(self, topic: str) -> List[Dict[str, Any]]:
        """Get all agents for a topic."""
        with self._lock:
            return [a.copy() for a in self._agents.get(topic, [])]

    async def list_all_agents(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all agents grouped by topic."""
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
        """Save task result."""
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
        """Get task result, checking expiration."""
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
        """Save a metric event."""
        with self._lock:
            metric_data["saved_at"] = time.time()
            self._metrics.append(metric_data)

            if len(self._metrics) > 10000:
                self._metrics = self._metrics[-10000:]

            self._save_metrics()

    async def get_metrics(
        self, topic: Optional[str] = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get metrics, optionally filtered by topic."""
        with self._lock:
            metrics = self._metrics

            if topic:
                metrics = [m for m in metrics if m.get("topic") == topic]

            return list(reversed(metrics[-limit:]))

    async def save_config(self, key: str, value: Any) -> None:
        """Save configuration value."""
        with self._lock:
            self._config[key] = value
            self._save_config()

    async def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
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
        """Clear all data."""
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
