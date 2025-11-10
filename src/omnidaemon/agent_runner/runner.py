import asyncio
import logging
import time
from typing import Optional, Dict, Any, Callable, Awaitable, Union
from uuid import uuid4
import aiohttp
from omnidaemon.event_bus.base import BaseEventBus
from omnidaemon.storage.base import BaseStore

logger = logging.getLogger(__name__)


class BaseAgentRunner:
    """
    Base agent runner with dependency injection.

    This class orchestrates agent execution by managing subscriptions to event topics,
    processing messages through registered callbacks, and persisting results and metrics.
    All data operations (agents, results, metrics) go through the unified store.

    Features:
        - Supports multiple topic subscriptions and agent callbacks
        - Each callback can be an async or sync function
        - Uses injected event bus and storage instances (dependency injection)
        - All persistence handled by unified storage layer
        - Automatic webhook delivery and reply-to topic publishing
        - Comprehensive metric tracking for monitoring

    Args:
        event_bus: Event bus instance for publishing and subscribing to topics
        store: Storage instance for persisting agents, results, and metrics
        runner_id: Optional unique identifier for this runner instance. If not provided,
                   a UUID will be generated automatically.

    Attributes:
        runner_id: Unique identifier for this runner instance
        event_bus: Event bus instance for message handling
        store: Storage instance for data persistence
        event_bus_connected: Whether the event bus has been connected
        _running: Whether the runner is currently active
    """

    def __init__(
        self,
        event_bus: BaseEventBus,
        store: BaseStore,
        runner_id: Optional[str] = None,
    ) -> None:
        self.runner_id = runner_id or str(uuid4())
        self.event_bus = event_bus
        self.store = store
        self.event_bus_connected = False
        self._running = False

    async def register_handler(self, topic: str, subscription: Dict[str, Any]) -> None:
        """
        Register an agent handler for a given topic.

        This method registers an agent callback for a specific topic, automatically
        subscribes to the topic on the event bus, and persists the agent configuration
        to storage. If this is the first agent registration, it also initializes the
        runner start time and runner ID in storage.

        Args:
            topic: The topic name to subscribe to (e.g., "file_system.tasks")
            subscription: Dictionary containing agent configuration:
                - name: Agent name/identifier
                - callback: Callable function to process messages
                - config: Optional subscription configuration (consumer_count, etc.)
                - description: Optional agent description
                - tools: Optional list of tools available to the agent

        Raises:
            Exception: If event bus or storage connection fails
        """
        if not self.event_bus_connected:
            await self.event_bus.connect()
            await self.store.connect()
            self.event_bus_connected = True

        await self.store.add_agent(topic=topic, agent_data=subscription)

        agent_name = subscription.get("name")
        agent_callback = subscription.get("callback")
        if not agent_name or not agent_callback:
            raise ValueError("Subscription must include 'name' and 'callback'")
        general_callback = await self._make_agent_callback(
            topic=topic, agent_name=agent_name, agent_callback=agent_callback
        )
        config = subscription.get("config") or {}
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
        self,
        topic: str,
        agent_name: str,
        agent_callback: Callable[[Dict[str, Any]], Any],
    ) -> Callable[[Dict[str, Any]], Awaitable[None]]:
        """
        Create a wrapped callback that runs the agent and tracks metrics.

        This method creates a wrapper function around the user's agent callback that:
        - Enriches messages with topic and agent information
        - Tracks task_received, task_processed, and task_failed events
        - Handles both async and sync callbacks automatically
        - Sends responses via webhook and reply-to topics
        - Persists results to storage

        Args:
            topic: The topic name this agent is subscribed to
            agent_name: The name/identifier of the agent
            agent_callback: The user's callback function to wrap. Can be async or sync.

        Returns:
            An async wrapper function that handles message processing and metric tracking
        """

        async def agent_wrapper(message: Dict[str, Any]) -> None:
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
        Publish an event to the event bus.

        This method publishes a message to the specified topic on the event bus.
        If the event bus is not connected, it will automatically establish a connection.

        Args:
            event_payload: Dictionary containing the event data. Must include:
                - topic: The topic to publish to
                - id: Optional task ID (if not provided, will be generated)
                - payload: Dictionary with message content, webhook, reply_to, etc.
                - correlation_id: Optional correlation ID for tracing
                - causation_id: Optional causation ID for event sourcing
                - source: Optional source identifier
                - delivery_attempts: Optional delivery attempt counter

        Returns:
            The task ID of the published event

        Raises:
            Exception: If event bus connection or publishing fails
        """
        if not self.event_bus_connected:
            await self.event_bus.connect()
            self.event_bus_connected = True
        task_id = await self.event_bus.publish(event_payload=event_payload)
        return task_id

    async def _send_response(self, message: Dict[str, Any], result: Any) -> None:
        """
        Send response via webhook, reply-to topic, and save to store.

        This method handles multiple response delivery mechanisms:
        1. Saves the result to storage with a 24-hour TTL
        2. Sends HTTP webhook if webhook URL is provided (with retry logic)
        3. Publishes response to reply_to topic if specified

        All results are saved to unified storage with 24-hour TTL for later retrieval.

        Args:
            message: The original message/event that triggered the agent
            result: The result returned by the agent callback

        Note:
            Webhook delivery uses exponential backoff retry (3 attempts max).
            If webhook delivery fails after all retries, it's logged but doesn't raise.
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

    async def publish_response(
        self, message: Dict[str, Any], result: Any
    ) -> Optional[str]:
        """
        Publish a new event as a response to a previous task/message.

        This method creates a new event on the reply_to topic specified in the
        original message, preserving correlation and causation IDs for event sourcing
        and distributed tracing.

        Args:
            message: Original event envelope dictionary containing reply_to topic
            result: The output/content to include in the response payload

        Returns:
            The task ID of the newly published response event, or None if no
            reply_to topic was specified in the original message
        """
        reply_to = message.get("reply_to")
        if not reply_to:
            return None

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

    async def start(self) -> None:
        """
        Start listening for all registered topics.

        This method activates the runner and begins processing messages for all
        registered agents. It retrieves all registered agents from storage and
        logs the topics that will be monitored.

        Note:
            The actual message consumption is handled by the event bus subscription
            mechanism, which was set up during agent registration.
        """
        if self._running:
            logger.warning(f"[Runner {self.runner_id}] Already running.")
            return
        self._running = True

        all_agents = await self.store.list_all_agents()
        topics = list(all_agents.keys())

        logger.info(f"[Runner {self.runner_id}] Listening for topics: {topics}")

    async def stop(self) -> None:
        """
        Stop runner and close event bus.

        This method gracefully shuts down the runner by:
        1. Clearing the start time and runner ID from storage
        2. Closing the event bus connection
        3. Setting the running flag to False

        Note:
            This method is idempotent - calling it multiple times is safe.
        """
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
    async def _maybe_await(result: Union[Awaitable[Any], Any]) -> Any:
        """
        Await coroutine results automatically.

        This utility method handles both async and sync return values from callbacks.
        If the result is a coroutine, it awaits it; otherwise, it returns the value directly.

        Args:
            result: Either a coroutine to await or a direct value

        Returns:
            The awaited result if it was a coroutine, or the original value if not
        """
        if asyncio.iscoroutine(result):
            return await result
        return result
