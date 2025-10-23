import asyncio
from typing import Dict, Any, Callable, List, Optional
import logging
import signal
import uuid

import time
from omnidaemon.agent_runner.runner import BaseAgentRunner
from omnidaemon.result_store import ResultStore


logger = logging.getLogger(__name__)


class OmniDaemonSDK:
    """
    App-facing SDK for OmniDaemon.
    Allows publishing tasks and registering agent callbacks.
    """

    def __init__(self, result_store: Optional[ResultStore] = None):
        self.runner = BaseAgentRunner(result_store=result_store)
        self._agents: List[Dict] = []
        self._external_result_store = result_store

    # ------------------------
    # Task Publisher
    # ------------------------
    async def publish_task(
        self, topic: str, payload: Dict[str, Any], reply_to: str = None
    ) -> str:
        if "task_id" not in payload:
            payload["task_id"] = str(uuid.uuid4())

        if reply_to:
            payload["reply_to"] = reply_to
        if "topic" not in payload:
            payload["topic"] = topic

        await self.runner.publish(topic, payload)
        logger.info(f"Published task '{payload['task_id']}' to topic '{topic}'")
        return payload["task_id"]

    def agent(
        self,
        topic: str,
        name: Optional[str] = None,
        tools: Optional[List[str]] = None,
        description: str = "",
        active: bool = True,
    ):
        """
        Decorator to register an agent function.
        Usage:
            @sdk.agent(topic="greet.user", name="Greeter")
            async def greet(payload):
                return {"msg": "Hello!"}
        """

        def decorator(func: Callable[[Dict[str, Any]], Any]):
            self._agents.append(
                {
                    "topic": topic,
                    "func": func,
                    "name": name or func.__name__,
                    "tools": tools or [],
                    "description": description,
                    "active": active,
                }
            )
            return func

        return decorator

    # ------------------------
    # Register Agent Callback
    # ------------------------
    async def register_agent(
        self,
        name: str,
        topic: str,
        callback: Callable[[Dict[str, Any]], Any],
        agent_config: Optional[Dict[str, Any]] = None,
        active: bool = True,
    ):
        """
        Register an agent to a topic with a callback.
        """

        if agent_config is None:
            agent_config = {}

        description = agent_config.get("description", "")
        tools = agent_config.get("tools", [])

        subscription = {
            "callback": callback,
            "name": name,
            "tools": tools,
            "description": description,
            "status": "running" if active else "stopped",
        }
        agent_name = subscription.get("name", "unnamed")
        key = (topic, agent_name)
        self.runner._metrics[key] = {
            "tasks_received": 0,
            "tasks_processed": 0,
            "tasks_failed": 0,
            "tasks_skipped": 0,
            "total_processing_time": 0.0,
        }
        await self.runner.register_handler(topic, subscription)

    async def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        if self._external_result_store:
            return await self._external_result_store.get_result(task_id)

    # ------------------------
    # Start / Stop
    # ------------------------
    async def start(self):
        self._start_time = time.time()
        await self.runner.start()

    async def stop(self):
        await self.runner.stop()

    def run(self):
        """
        Start the SDK and run forever (for simple agent scripts).
        Handles KeyboardInterrupt and shuts down cleanly.

        Usage:
            if __name__ == "__main__":
                sdk.run()
        """
        try:
            loop = asyncio.get_running_loop()
            logger.warning(
                "sdk.run() called inside an async context. Use 'await sdk.start()' instead."
            )
            return
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(self._run_forever())
        except KeyboardInterrupt:
            logger.info("Received KeyboardInterrupt. Shutting down...")
        finally:
            try:
                loop.run_until_complete(self.stop())
            except Exception as e:
                logger.error(f"Error during shutdown: {e}")
            loop.close()

    async def _run_forever(self):
        """Start and keep alive."""
        for agent in self._agents:
            await self.register_agent(
                topic=agent["topic"],
                callback=agent["func"],
                name=agent["name"],
                agent_config={
                    "tools": agent["tools"],
                    "description": agent["description"],
                },
                active=agent["active"],
            )
        await self.start()
        logger.info(
            f"OmniDaemon running with {len(self._agents)} agent(s). Press Ctrl+C to stop."
        )
        stop_event = asyncio.Event()

        def _signal_handler():
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, _signal_handler)
        await stop_event.wait()

    # ------------------------
    # Start / Stop Individual Agent
    # ------------------------
    async def start_agent(self, topic: str, agent_name: str):
        for sub in self.runner._handlers.get(topic, []):
            if sub["name"] == agent_name:
                sub["status"] = "running"
                logger.info(f"Started agent '{agent_name}' on topic '{topic}'")
                return
        logger.warning(f"Agent '{agent_name}' not found on topic '{topic}'")

    async def stop_agent(self, topic: str, agent_name: str):
        for sub in self.runner._handlers.get(topic, []):
            if sub["name"] == agent_name:
                sub["status"] = "stopped"
                logger.info(f"⏹ Stopped agent '{agent_name}' on topic '{topic}'")
                return
        logger.warning(f"Agent '{agent_name}' not found on topic '{topic}'")

    # ------------------------
    # Start / Stop All Agents
    # ------------------------
    async def start_all_agents(self):
        for topic_subs in self.runner._handlers.values():
            for sub in topic_subs:
                sub["status"] = "running"
        logger.info("Started all agents")

    async def stop_all_agents(self):
        for topic_subs in self.runner._handlers.values():
            for sub in topic_subs:
                sub["status"] = "stopped"
        logger.info("Stopped all agents")

    # ------------------------
    # List Agents / Dashboard
    # ------------------------
    def list_agents(self):
        """
        Return all agents with metadata and status, grouped by topic.
        """
        result = {}
        for topic, subs in self.runner._handlers.items():
            result[topic] = [
                {
                    "name": sub["name"],
                    "tools": sub["tools"],
                    "description": sub["description"],
                    "status": sub["status"],
                }
                for sub in subs
            ]
        return result

    def get_agent(self, topic: str, agent_name: str):
        """
        Return full agent info by topic and name.
        """
        for sub in self.runner._handlers.get(topic, []):
            if sub["name"] == agent_name:
                return sub
        return None

    def health(self):
        """Return health info about the runner."""
        return {
            "runner_id": self.runner.runner_id,
            "status": "running" if self.runner._running else "stopped",
            "event_bus_connected": self.runner.bus is not None,
            "subscribed_topics": list(self.runner._handlers.keys()),
            "active_agents": sum(
                1
                for subs in self.runner._handlers.values()
                for sub in subs
                if sub.get("status") == "running"
            ),
            "uptime_seconds": time.time() - getattr(self, "_start_time", 0),
        }

    def metrics(self):
        """Return detailed task processing metrics."""
        result = {}
        for (topic, agent_name), stats in self.runner._metrics.items():
            if topic not in result:
                result[topic] = {}
            avg_time = 0.0
            if stats["tasks_processed"] > 0:
                avg_time = stats["total_processing_time"] / stats["tasks_processed"]
            result[topic][agent_name] = {
                "tasks_received": stats["tasks_received"],
                "tasks_processed": stats["tasks_processed"],
                "tasks_failed": stats["tasks_failed"],
                "tasks_skipped": stats["tasks_skipped"],
                "avg_processing_time_sec": round(avg_time, 3),
                "total_processing_time": round(stats["total_processing_time"], 3),
            }
        return result
