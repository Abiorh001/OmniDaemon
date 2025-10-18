import asyncio
import logging
from typing import Optional, Dict, Any, List, Optional, Tuple
from uuid import uuid4
import aiohttp
from omnidaemon.event_bus.factory import EventBusFactory
from omnidaemon.result_store import ResultStore

logger = logging.getLogger(__name__)


class BaseAgentRunner:
    """
     - Supports multiple topic subscriptions and agent callbacks.
    - Each callback can be an async or sync function.
    - Uses a single event bus instance per runner process.
    """

    def __init__(
        self,
        runner_id: Optional[str] = None,
        result_store: Optional[ResultStore] = None,
    ):
        self.runner_id = runner_id or str(uuid4())
        self.bus = None
        self._running = False
        self._handlers: Dict[str, List[Dict[str, Any]]] = {}
        self.result_store = result_store
        self._metrics: Dict[Tuple, Any] = {}

    async def register_handler(self, topic: str, subscription: Dict[str, Any]):
        """
        Register an agent handler for a given topic.
        Automatically subscribes to the topic on the event bus.
        """
        if not self.bus:
            self.bus = await EventBusFactory.get_event_bus()
            await self.bus.connect()

        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(subscription)
        await self.bus.subscribe(topic, self._dispatch_message)
        logger.info(f"[Runner {self.runner_id}] Subscribed to topic '{topic}'")

    async def _dispatch_message(self, message: Dict[str, Any]):
        """Dispatch incoming message to all handlers for the topic concurrently."""
        topic = message.get("topic")
        if not topic:
            logger.warning(
                f"[Runner {self.runner_id}] Message missing topic: {message}"
            )
            return

        subscriptions = self._handlers.get(topic)
        if not subscriptions:
            logger.warning(f"[Runner {self.runner_id}] No handler for topic: {topic}")
            return

        async def run_handler(sub):
            key = (topic, sub.get("name"))
            self._metrics[key]["tasks_received"] += 1
            if sub.get("status") != "running":
                self._metrics[key]["tasks_skipped"] += 1
                logger.debug(
                    f"Skipping stopped agent '{sub.get('name')}' on topic '{topic}'"
                )
                return
            callback = sub["callback"]
            try:
                logger.debug(
                    f"[Runner {self.runner_id}] Handling message on '{topic}' with {sub.get('name')}: {message}"
                )
                start_time = asyncio.get_event_loop().time()
                result = await self._maybe_await(callback(message))
                await self._send_response(message, result)
                self._metrics[key]["tasks_processed"] += 1
                self._metrics[key]["total_processing_time"] += (
                    asyncio.get_event_loop().time() - start_time
                )

            except Exception as e:
                self._metrics[key]["tasks_failed"] += 1
                logger.exception(
                    f"[Runner {self.runner_id}] Error processing message on '{topic}' with {sub.get('name')}: {e}"
                )

        # Run all handlers for the topic concurrently
        await asyncio.gather(*(run_handler(sub) for sub in subscriptions))

    async def publish(self, topic: str, payload: dict):
        """
        publish to the event bus
        """
        if not self.bus:
            self.bus = await EventBusFactory.get_event_bus()
            await self.bus.connect()
        await self.bus.publish(topic=topic, message=payload)

    async def _send_response(self, message: Dict[str, Any], result: Any):
        webhook_url = message.get("webhook")
        task_id = message.get("task_id")
        topic = message.get("topic")

        response_payload = {
            "runner_id": self.runner_id,
            "topic": topic,
            "task_id": task_id,
            "status": "completed",
            "result": result,
            "timestamp": asyncio.get_event_loop().time(),
        }

        if task_id:
            try:
                await self.result_store.save_result(task_id, response_payload)
            except Exception as e:
                logger.error(f"Failed to save result for {task_id}: {e}")

        # Send webhook if requested
        if webhook_url:
            try:
                async with aiohttp.ClientSession() as session:
                    resp = await session.post(
                        webhook_url, json={"payload": response_payload}
                    )
                    logger.info(f"Webhook sent to {webhook_url} [status={resp.status}]")
            except Exception as e:
                logger.error(f"Webhook failed for {task_id}: {e}")
        else:
            logger.debug(f"Task {task_id} completed (no webhook). Result stored.")

    async def start(self):
        """Start listening for all registered topics."""
        if self._running:
            logger.warning(f"[Runner {self.runner_id}] Already running.")
            return
        self._running = True
        logger.info(
            f"[Runner {self.runner_id}] Listening for topics: {list(self._handlers.keys())}"
        )

    async def stop(self):
        """Stop runner and close event bus."""
        if not self._running:
            return
        await self.bus.close()
        self._running = False
        logger.info(f"[Runner {self.runner_id}] Stopped.")

    @staticmethod
    async def _maybe_await(result):
        """Await coroutine results automatically."""
        if asyncio.iscoroutine(result):
            return await result
        return result
