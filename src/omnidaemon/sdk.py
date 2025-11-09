from typing import Dict, Any, Callable, List, Optional
import logging
import uuid
import time
import json
from omnidaemon.agent_runner.runner import BaseAgentRunner
from omnidaemon.event_bus import event_bus as default_event_bus
from omnidaemon.event_bus.base import BaseEventBus
from omnidaemon.storage import store as default_store
from omnidaemon.storage.base import BaseStore
from omnidaemon.schemas import AgentConfig, EventEnvelope, PayloadBase
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class OmniDaemonSDK:
    """
    App-facing SDK for OmniDaemon with Dependency Injection.

    Allows publishing tasks and registering agent callbacks.
    All data operations (agents, results, metrics) go through unified storage.

    Dependencies are injected via constructor:
    - event_bus: Messaging layer (from module-level instance)
    - store: Storage layer (from module-level instance)
    """

    def __init__(
        self,
        event_bus: Optional[BaseEventBus] = None,
        store: Optional[BaseStore] = None,
    ):
        self.event_bus = event_bus or default_event_bus
        self.store = store or default_store
        self.runner = BaseAgentRunner(
            event_bus=self.event_bus,
            store=self.store,
        )
        self._agents: List[Dict] = []
        self._start_time = None
        self._is_running = False

    async def publish_task(self, event_envelope: EventEnvelope) -> str:
        try:
            topic = event_envelope.topic
            payload = event_envelope.payload
            content = payload.content
            webhook = payload.webhook
            reply_to = payload.reply_to
            task_id = event_envelope.id or str(uuid.uuid4())
            correlation_id = event_envelope.correlation_id
            tenant_id = event_envelope.tenant_id
            source = event_envelope.source
            causation_id = event_envelope.causation_id

            event_payload_schema = EventEnvelope(
                topic=topic,
                id=task_id,
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                source=source,
                payload=PayloadBase(
                    content=content, webhook=webhook, reply_to=reply_to
                ),
                causation_id=causation_id,
            )
            publish_event = {
                k: v
                for k, v in event_payload_schema.model_dump().items()
                if v is not None
            }
            publish_event["payload"] = event_payload_schema.payload.model_dump()
            task_id = await self.runner.publish(event_payload=publish_event)
            return task_id
        except ValidationError as ve:
            logger.error(f"EventEnvelope validation error: {ve}")
            raise
        except Exception as e:
            logger.error(f"Error parsing EventEnvelope: {e}")
            raise

    async def register_agent(self, agent_config: AgentConfig):
        """
        Register an agent to a topic with a callback and metadata.

        All agent data is persisted to unified storage via DI.
        Metrics are tracked automatically in storage when agent runs.
        """
        try:
            name = agent_config.name
            topic = agent_config.topic
            callback = agent_config.callback
            tools = agent_config.tools
            description = agent_config.description
            config = agent_config.config
            sub_config = {k: v for k, v in config.model_dump().items() if v is not None}
            logger.info(
                f"Registering agent '{name}' on topic '{topic}', config={sub_config}"
            )

            subscription = {
                "callback": callback,
                "callback_name": callback.__name__,
                "name": name,
                "tools": tools,
                "description": description,
                "config": sub_config,
            }

            await self.runner.register_handler(topic=topic, subscription=subscription)

        except ValidationError as ve:
            logger.error(f"AgentConfig validation error: {ve}")
            raise
        except Exception as e:
            logger.error(f"Error registering agent '{agent_config.name}': {e}")
            raise

    async def list_agents(self):
        """
        Return all agents with metadata and status, grouped by topic.
        Uses injected storage (DI).
        """
        all_agents = await self.store.list_all_agents()

        result = {}
        for topic, agents in all_agents.items():
            result[topic] = [
                {
                    "name": agent["name"],
                    "tools": agent.get("tools", []),
                    "description": agent.get("description", ""),
                    "callback": agent.get("callback_name", ""),
                    "config": agent.get("config", {}),
                }
                for agent in agents
            ]

        return result

    async def get_agent(self, topic: str, agent_name: str):
        """
        Return full agent info by topic and name.
        """
        agent = await self.store.get_agent(topic, agent_name)
        if agent:
            agent["callback"] = agent.get("callback_name", "")
        return agent

    async def unsubscribe_agent(self, topic: str, agent_name: str) -> bool:
        """
        Temporarily stop agent processing (pause).

        This stops the agent from consuming new messages but keeps:
        - Consumer group intact (messages continue to queue)
        - DLQ preserved (failed messages kept)
        - Agent data in storage (can resume by restarting runner)

        Use this for temporary maintenance or debugging.
        To resume, simply restart the runner.

        Args:
            topic: The topic
            agent_name: The agent name

        Returns:
            True if unsubscribed, False if not found
        """
        try:
            await self.event_bus.unsubscribe(
                topic=topic, agent_name=agent_name, delete_group=False, delete_dlq=False
            )
            logger.info(f"Unsubscribed agent '{agent_name}' from topic '{topic}'")
            return True
        except Exception as e:
            logger.warning(f"Failed to unsubscribe agent '{agent_name}': {e}")
            return False

    async def delete_agent(
        self,
        topic: str,
        agent_name: str,
        delete_group: bool = True,
        delete_dlq: bool = False,
    ) -> bool:
        """
        Permanently remove agent (complete cleanup).

        This does a full cleanup:
        - Stops processing (unsubscribes)
        - Deletes consumer group from Redis (default)
        - Optionally deletes DLQ
        - Removes agent data from storage
        - Agent cannot be resumed

        Args:
            topic: The topic
            agent_name: The agent name
            delete_group: If True, delete consumer group from Redis (default: True)
            delete_dlq: If True, also delete the DLQ (default: False)

        Returns:
            True if deleted, False if not found
        """
        try:
            await self.event_bus.unsubscribe(
                topic=topic,
                agent_name=agent_name,
                delete_group=delete_group,
                delete_dlq=delete_dlq,
            )
            logger.info(f"Unsubscribed and cleaning up agent '{agent_name}'")
        except Exception as e:
            logger.warning(f"Failed to unsubscribe during delete: {e}")

        deleted = await self.store.delete_agent(topic, agent_name)
        if deleted:
            logger.info(f"Deleted agent '{agent_name}' from storage")
        return deleted

    async def delete_topic(self, topic: str) -> int:
        """
        Delete all agents for a topic.

        Args:
            topic: The topic

        Returns:
            Number of agents deleted
        """
        return await self.store.delete_topic(topic)

    async def health(self):
        """
        Return health info about the runner and infrastructure.


        """
        all_agents = await self.store.list_all_agents()
        agents_list = await self.list_agents()

        event_bus_type = self.event_bus.__class__.__name__

        event_bus_connected = self.runner.event_bus is not None

        storage_healthy = False
        storage_status = {}
        try:
            storage_status = await self.store.health_check()
            storage_healthy = storage_status.get("status") == "healthy"
        except Exception as e:
            storage_status = {"status": "error", "error": str(e)}

        active_consumers = {}
        has_active_consumers = False
        try:
            if hasattr(self.event_bus, "get_consumers"):
                active_consumers = await self.event_bus.get_consumers()

                for group_name, group_info in active_consumers.items():
                    consumers_count = group_info.get("consumers_count", 0)
                    if consumers_count > 0:
                        has_active_consumers = True
                        break

                if not has_active_consumers and len(active_consumers) > 0:
                    for group_info in active_consumers.values():
                        if group_info.get("task") is not None:
                            has_active_consumers = True
                            break
        except Exception as e:
            logger.debug(f"Failed to check active consumers: {e}")

        stored_start_time = await self.store.get_config(
            "_omnidaemon_start_time", default=None
        )
        stored_runner_id = await self.store.get_config(
            "_omnidaemon_runner_id", default=None
        )

        if stored_start_time and has_active_consumers:
            uptime_seconds = time.time() - stored_start_time
        else:
            uptime_seconds = 0

        registered_count = sum(len(agents) for agents in all_agents.values())

        if stored_start_time is not None and registered_count > 0:
            status = "running"
        elif registered_count > 0 and stored_start_time is None:
            status = "stopped"
        elif registered_count == 0 and event_bus_connected and storage_healthy:
            status = "ready"
        elif event_bus_connected or storage_healthy:
            status = "degraded"
        else:
            status = "down"

        return {
            "runner_id": stored_runner_id or self.runner.runner_id,
            "status": status,
            "is_running": self._is_running,
            "runner_running": self.runner._running,
            "has_active_consumers": has_active_consumers,
            "event_bus_connected": event_bus_connected,
            "event_bus_type": event_bus_type,
            "storage_healthy": storage_healthy,
            "storage_status": storage_status,
            "subscribed_topics": list(all_agents.keys()),
            "agents": agents_list,
            "registered_agents_count": registered_count,
            "active_consumers": active_consumers,
            "uptime_seconds": uptime_seconds,
        }

    async def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Get task result from unified storage.

        Results are automatically saved by runner with 24h TTL.
        """
        return await self.store.get_result(task_id)

    async def list_results(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List recent task results.

        Args:
            limit: Maximum number of results to return (default: 100)

        Returns:
            List of result dictionaries with task_id and result data
        """
        return await self.store.list_results(limit=limit)

    async def delete_result(self, task_id: str) -> bool:
        """
        Delete a specific task result.

        Args:
            task_id: The task ID to delete

        Returns:
            True if deleted, False if not found
        """
        return await self.store.delete_result(task_id)

    async def start(self):
        """Start the agent runner and begin processing tasks."""
        if not self._is_running:
            self._start_time = time.time()
            self._is_running = True
            logger.info("Starting OmniDaemon SDK...")
        await self.runner.start()

    async def stop(self):
        """Stop the agent runner but keep connections alive."""
        logger.info("Stopping OmniDaemon SDK...")
        await self.runner.stop()
        self._is_running = False

    async def shutdown(self):
        """
        Gracefully shutdown all components.

        This method should be called on exit to:
        - Stop the runner
        - Close event bus connection
        - Close storage connection
        - Clean up resources
        """
        print("Shutting down OmniDaemon SDK...")

        try:
            await self.stop()
        except Exception as e:
            logger.error(f"Error stopping runner: {e}")

        try:
            if self.event_bus:
                await self.event_bus.close()
                logger.info("Event bus closed")
        except Exception as e:
            logger.error(f"Error closing event bus: {e}")

        try:
            if self.store:
                await self.store.close()
                logger.info("Storage closed")
        except Exception as e:
            logger.error(f"Error closing storage: {e}")

        self._is_running = False
        logger.info("OmniDaemon SDK shutdown complete")

    async def metrics(self, topic: Optional[str] = None, limit: int = 1000):
        """
        Return detailed task processing metrics from unified storage.

        Metrics are automatically tracked by runner and saved to storage.

        Args:
            topic: Optional topic filter
            limit: Maximum number of metrics to retrieve

        Returns:
            Dict with aggregated metrics by topic and agent
        """
        raw_metrics = await self.store.get_metrics(topic=topic, limit=limit)

        result = {}
        for metric in raw_metrics:
            topic_name = metric.get("topic")
            agent_name = metric.get("agent")
            event = metric.get("event")

            if not topic_name or not agent_name:
                continue

            if topic_name not in result:
                result[topic_name] = {}

            if agent_name not in result[topic_name]:
                result[topic_name][agent_name] = {
                    "tasks_received": 0,
                    "tasks_processed": 0,
                    "tasks_failed": 0,
                    "total_processing_time": 0.0,
                    "processing_times": [],
                }

            agent_stats = result[topic_name][agent_name]

            if event == "task_received":
                agent_stats["tasks_received"] += 1
            elif event == "task_processed":
                agent_stats["tasks_processed"] += 1
                processing_time = metric.get("processing_time_sec", 0)
                agent_stats["total_processing_time"] += processing_time
                agent_stats["processing_times"].append(processing_time)
            elif event == "task_failed":
                agent_stats["tasks_failed"] += 1

        for topic_name, agents in result.items():
            for agent_name, stats in agents.items():
                if stats["tasks_processed"] > 0:
                    avg_time = stats["total_processing_time"] / stats["tasks_processed"]
                    stats["avg_processing_time_sec"] = round(avg_time, 3)
                else:
                    stats["avg_processing_time_sec"] = 0.0

                del stats["processing_times"]
                stats["total_processing_time"] = round(
                    stats["total_processing_time"], 3
                )

        return result

    async def clear_agents(self) -> int:
        """
        Delete all agent registrations.

        Returns:
            Number of agents deleted
        """
        return await self.store.clear_agents()

    async def clear_results(self) -> int:
        """
        Delete all task results.

        Returns:
            Number of results deleted
        """
        return await self.store.clear_results()

    async def clear_metrics(self) -> int:
        """
        Delete all metrics.

        Returns:
            Number of metrics deleted
        """
        return await self.store.clear_metrics()

    async def clear_all(self) -> Dict[str, int]:
        """
        Clear all data from storage (agents, results, metrics, config).

        WARNING: This operation is irreversible!

        Returns:
            Dictionary with counts of deleted items by category
        """
        return await self.store.clear_all()

    async def save_config(self, key: str, value: Any) -> None:
        """
        Save a configuration value.

        Args:
            key: Configuration key
            value: Configuration value (will be JSON-serialized)
        """
        return await self.store.save_config(key, value)

    async def get_config(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a configuration value.

        Args:
            key: Configuration key
            default: Default value if not found

        Returns:
            Configuration value or default
        """
        return await self.store.get_config(key, default)

    async def storage_health(self) -> Dict[str, Any]:
        """
        Get storage backend health information.

        Returns:
            Dictionary with storage status, backend type, and metrics
        """
        return await self.store.health_check()

    async def list_streams(self) -> List[Dict[str, Any]]:
        """
        List all Redis streams and their message counts.

        Only works with RedisStreamEventBus. Fails gracefully otherwise.

        Returns:
            List of dicts with 'stream' and 'length' keys

        Raises:
            ValueError: If event bus is not RedisStreamEventBus
        """
        if not hasattr(self.event_bus, "_redis"):
            raise ValueError("Event bus monitoring only works with Redis Streams")

        if not self.event_bus._redis:
            await self.event_bus.connect()

        keys = await self.event_bus._redis.keys("omni-stream:*")
        keys = [k.decode() if isinstance(k, bytes) else k for k in keys]

        streams = []
        for stream_key in keys:
            length = await self.event_bus._redis.xlen(stream_key)
            streams.append({"stream": stream_key, "length": length})

        return streams

    async def inspect_stream(
        self, stream: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Inspect recent messages in a Redis stream.

        Args:
            stream: Stream name (with or without 'omni-stream:' prefix)
            limit: Maximum number of messages to retrieve

        Returns:
            List of message dicts with 'id' and 'data' keys

        Raises:
            ValueError: If event bus is not RedisStreamEventBus
        """
        if not hasattr(self.event_bus, "_redis"):
            raise ValueError("Event bus monitoring only works with Redis Streams")

        if not self.event_bus._redis:
            await self.event_bus.connect()

        stream_key = (
            f"omni-stream:{stream}" if not stream.startswith("omni-stream:") else stream
        )

        entries = await self.event_bus._redis.xrevrange(stream_key, count=limit)

        messages = []
        for msg_id, fields in entries:
            msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
            data_field = fields.get(b"data") or fields.get("data", b"")
            data_str = (
                data_field.decode() if isinstance(data_field, bytes) else data_field
            )

            try:
                data = json.loads(data_str)
            except:
                data = data_str

            messages.append({"id": msg_id_str, "data": data})

        return messages

    async def list_groups(self, stream: str) -> List[Dict[str, Any]]:
        """
        List consumer groups for a Redis stream.

        Args:
            stream: Stream name (with or without 'omni-stream:' prefix)

        Returns:
            List of group dicts with name, consumers, pending, last_delivered_id

        Raises:
            ValueError: If event bus is not RedisStreamEventBus
        """
        if not hasattr(self.event_bus, "_redis"):
            raise ValueError("Event bus monitoring only works with Redis Streams")

        if not self.event_bus._redis:
            await self.event_bus.connect()

        stream_key = (
            f"omni-stream:{stream}" if not stream.startswith("omni-stream:") else stream
        )

        try:
            groups_info = await self.event_bus._redis.xinfo_groups(stream_key)
        except Exception as e:
            logger.warning(f"Failed to get groups for {stream_key}: {e}")
            return []

        groups = []
        for g in groups_info:
            name = g.get("name", b"")
            name = name.decode() if isinstance(name, bytes) else name
            consumers = g.get("consumers", 0)
            pending = g.get("pending", 0)
            last_id = g.get("last-delivered-id", b"")
            last_id = last_id.decode() if isinstance(last_id, bytes) else last_id

            groups.append(
                {
                    "name": name,
                    "consumers": consumers,
                    "pending": pending,
                    "last_delivered_id": last_id,
                }
            )

        return groups

    async def inspect_dlq(self, topic: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Inspect dead-letter queue entries for a topic.

        Args:
            topic: Topic name
            limit: Maximum number of entries to retrieve

        Returns:
            List of DLQ message dicts with 'id' and 'data' keys

        Raises:
            ValueError: If event bus is not RedisStreamEventBus
        """
        if not hasattr(self.event_bus, "_redis"):
            raise ValueError("Event bus monitoring only works with Redis Streams")

        if not self.event_bus._redis:
            await self.event_bus.connect()

        all_dlq = await self.event_bus._redis.keys("omni-dlq:*")
        per_topic_dlq = await self.event_bus._redis.keys(f"omni-dlq:group:{topic}:*")
        dlq_keys = set(all_dlq).intersection(set(per_topic_dlq))

        if not dlq_keys:
            return []

        dlq_key = dlq_keys.pop()
        entries = await self.event_bus._redis.xrevrange(dlq_key, count=limit)

        messages = []
        for msg_id, data in entries:
            msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
            messages.append({"id": msg_id_str, "data": data})

        return messages

    async def get_bus_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive stats across all topics and consumer groups.

        Returns:
            Dict with timestamp, topics (with stream length, groups, DLQ), and redis_info

        Raises:
            ValueError: If event bus is not RedisStreamEventBus
        """
        if not hasattr(self.event_bus, "_redis"):
            raise ValueError("Event bus monitoring only works with Redis Streams")

        if not self.event_bus._redis:
            await self.event_bus.connect()

        stream_keys = await self.event_bus._redis.keys("omni-stream:*")
        stream_keys = [k.decode() if isinstance(k, bytes) else k for k in stream_keys]

        snapshot = {"timestamp": time.time(), "topics": {}}

        for stream_key in stream_keys:
            topic = stream_key.replace("omni-stream:", "", 1)

            length = await self.event_bus._redis.xlen(stream_key)

            groups = []
            dlq_total = 0
            try:
                group_infos = await self.event_bus._redis.xinfo_groups(stream_key)
                for g in group_infos:
                    name = (
                        g.get("name", "").decode()
                        if isinstance(g.get("name"), bytes)
                        else g.get("name", "")
                    )
                    consumers = g.get("consumers", 0)
                    pending = g.get("pending", 0)
                    last_id = (
                        g.get("last-delivered-id", b"").decode()
                        if isinstance(g.get("last-delivered-id"), bytes)
                        else g.get("last-delivered-id", "")
                    )

                    dlq_key = f"dlq:{name}"
                    try:
                        dlq_len = await self.event_bus._redis.xlen(dlq_key)
                        dlq_total += dlq_len
                    except:
                        dlq_len = 0

                    groups.append(
                        {
                            "name": name,
                            "consumers": consumers,
                            "pending": pending,
                            "last_delivered_id": last_id,
                            "dlq": dlq_len,
                        }
                    )
            except Exception as e:
                logger.warning(f"Failed to get groups for {stream_key}: {e}")

            snapshot["topics"][topic] = {
                "length": length,
                "dlq_total": dlq_total,
                "groups": groups,
            }

        redis_info = {"used_memory_human": "-"}
        try:
            info = await self.event_bus._redis.info()
            redis_info["used_memory_human"] = info.get("used_memory_human", "-")
        except:
            pass

        return {"snapshot": snapshot, "redis_info": redis_info}
