import asyncio
import logging
import time
from typing import Optional, Dict, Any, Callable
from uuid import uuid4
import aiohttp
from omnidaemon.event_bus.base import BaseEventBus
from omnidaemon.storage.base import BaseStore

logger = logging.getLogger(__name__)


class BaseAgentRunner:
    """
    Base agent runner with dependency injection.

    All data operations (agents, results, metrics) go through the unified store.

    - Supports multiple topic subscriptions and agent callbacks.
    - Each callback can be an async or sync function.
    - Uses injected event bus and storage instances (DI).
    - All persistence handled by unified storage layer.
    """

    def __init__(
        self,
        event_bus: BaseEventBus,
        store: BaseStore,
        runner_id: Optional[str] = None,
    ):
        self.runner_id = runner_id or str(uuid4())
        self.event_bus = event_bus
        self.store = store
        self.event_bus_connected = False
        self._running = False

    async def register_handler(self, topic: str, subscription: Dict[str, Any]):
        """
        Register an agent handler for a given topic.
        Automatically subscribes to the topic on the event bus.
        Uses injected storage for persistence.
        """
        if not self.event_bus_connected:
            await self.event_bus.connect()
            await self.store.connect()
            self.event_bus_connected = True

        await self.store.add_agent(topic=topic, agent_data=subscription)

        agent_name = subscription.get("name")
        agent_callback = subscription.get("callback")
        general_callback = await self._make_agent_callback(
            topic=topic, agent_name=agent_name, agent_callback=agent_callback
        )
        config = subscription.get("config")
        await self.event_bus.subscribe(
            topic=topic, callback=general_callback, config=config, agent_name=agent_name
        )

        existing_start_time = await self.store.get_config(
            "_omnidaemon_start_time", default=None
        )
        if existing_start_time is None:
            current_time = time.time()
            await self.store.save_config("_omnidaemon_start_time", current_time)
            await self.store.save_config("_omnidaemon_runner_id", self.runner_id)
            logger.info(f"[Runner {self.runner_id}] Started at {current_time}")

        logger.info(
            f"[Runner {self.runner_id}] Registered agent '{agent_name}' on topic '{topic}'"
        )
        print(
            f"[Runner {self.runner_id}] Registered agent '{agent_name}' on topic '{topic}'"
        )

    async def _make_agent_callback(
        self, topic: str, agent_name: str, agent_callback: Callable
    ):
        """
        Returns a callback that runs the agent and tracks metrics in store.

        All metrics are saved to unified storage for persistence and querying.
        """

        async def agent_wrapper(message: Dict[str, Any]):
            if "topic" not in message:
                message = {**message, "topic": topic}
            message["agent"] = agent_name

            # Track task received
            await self.store.save_metric(
                {
                    "topic": topic,
                    "agent": agent_name,
                    "runner_id": self.runner_id,
                    "event": "task_received",
                    "task_id": message.get("task_id"),
                    "timestamp": time.time(),
                }
            )

            try:
                logger.debug(
                    f"[Runner {self.runner_id}] Handling message on '{topic}' with {agent_name}"
                )
                start_time = time.time()
                result = await self._maybe_await(agent_callback(message))
                processing_time = time.time() - start_time

                await self._send_response(message, result)

                # Track successful processing
                await self.store.save_metric(
                    {
                        "topic": topic,
                        "agent": agent_name,
                        "runner_id": self.runner_id,
                        "event": "task_processed",
                        "task_id": message.get("task_id"),
                        "processing_time_sec": processing_time,
                        "timestamp": time.time(),
                    }
                )

            except Exception as e:
                # Track failure
                await self.store.save_metric(
                    {
                        "topic": topic,
                        "agent": agent_name,
                        "runner_id": self.runner_id,
                        "event": "task_failed",
                        "task_id": message.get("task_id"),
                        "error": str(e),
                        "timestamp": time.time(),
                    }
                )
                logger.exception(
                    f"[Runner {self.runner_id}] Error in agent '{agent_name}': {e}"
                )
                raise

        return agent_wrapper

    async def publish(self, event_payload: Dict[str, Any]) -> str:
        """
        publish to the event bus
        """
        if not self.event_bus_connected:
            await self.event_bus.connect()
            self.event_bus_connected = True
        task_id = await self.event_bus.publish(event_payload=event_payload)
        return task_id

    async def _send_response(self, message: Dict[str, Any], result: Any):
        """
        Send response via webhook, reply-to topic, and save to store.

        All results are saved to unified storage with 24h TTL.
        """
        webhook_url = message.get("webhook")
        reply_to = message.get("reply_to")
        task_id = message.get("task_id")

        response_payload = {**message}
        response_payload.update(
            {
                "runner_id": self.runner_id,
                "status": "completed",
                "result": result,
                "timestamp": time.time(),
            }
        )
        if task_id:
            try:
                await self.store.save_result(
                    task_id=task_id, result=response_payload, ttl_seconds=86400
                )
                logger.info(f"Result saved to store for task {task_id}")
            except Exception as e:
                logger.error(f"Failed to save result for {task_id}: {e}")

        # Send webhook if requested
        if webhook_url:
            MAX_RETRIES = 3
            BACKOFF_FACTOR = 2

            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            webhook_url,
                            json={"payload": response_payload},
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as resp:
                            logger.info(
                                f"Webhook sent to {webhook_url} [status={resp.status}]"
                            )
                            break
                except Exception as e:
                    logger.error(
                        f"Webhook attempt {attempt}/{MAX_RETRIES} failed for task {task_id}: {e}"
                    )
                    if attempt < MAX_RETRIES:
                        delay = BACKOFF_FACTOR**attempt
                        logger.info(f"Retrying in {delay} seconds...")
                        await asyncio.sleep(delay)
                    else:
                        logger.critical(
                            f"Webhook failed permanently for task {task_id} after {MAX_RETRIES} attempts"
                        )

            logger.info(f"Task {task_id} completed. Webhook delivery finalized.")
        # publish the new event as response
        if reply_to:
            new_task_id = await self.publish_response(message, result)
            logger.info(f"Response published with task_id: {new_task_id}")

        else:
            logger.debug(f"Task {task_id} completed (no webhook). Result stored.")

    async def publish_response(self, message: dict, result: str) -> Optional[str]:
        """
        Publish a new EventEnvelope as a response to a previous task/message.

        - `message`: Original EventEnvelope dict
        - `result`: The output/content to include in the new payload

        Returns the new task_id of the published event.
        """
        reply_to = message.get("reply_to")
        if not reply_to:
            return

        new_event = {
            "id": str(uuid4()),
            "topic": reply_to,
            "payload": {
                "content": result,
                "webhook": message.get("webhook"),
                "reply_to": None,
            },
            "tenant_id": message.get("tenant_id"),
            "correlation_id": message.get("correlation_id"),
            "causation_id": message.get("task_id"),
            "source": message.get("source"),
            "delivery_attempts": 1,
        }
        new_task_id = await self.publish(event_payload=new_event)
        return new_task_id

    async def start(self):
        """Start listening for all registered topics."""
        if self._running:
            logger.warning(f"[Runner {self.runner_id}] Already running.")
            return
        self._running = True

        all_agents = await self.store.list_all_agents()
        topics = list(all_agents.keys())

        logger.info(f"[Runner {self.runner_id}] Listening for topics: {topics}")

    async def stop(self):
        """Stop runner and close event bus."""
        try:
            await self.store.save_config("_omnidaemon_start_time", None)
            await self.store.save_config("_omnidaemon_runner_id", None)
            logger.info(f"[Runner {self.runner_id}] Cleared start time from storage")
        except Exception as e:
            logger.warning(f"[Runner {self.runner_id}] Failed to clear start time: {e}")

        if not self._running:
            return

        await self.event_bus.close()
        self._running = False
        logger.info(f"[Runner {self.runner_id}] Stopped.")

    @staticmethod
    async def _maybe_await(result):
        """Await coroutine results automatically."""
        if asyncio.iscoroutine(result):
            return await result
        return result
