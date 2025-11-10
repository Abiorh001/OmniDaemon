from abc import ABC, abstractmethod
from typing import Any, Callable, Dict


class BaseEventBus(ABC):
    """
    Abstract event bus contract for message publishing and subscription.

    This abstract base class defines the interface that all event bus implementations
    must follow. It supports various messaging backends such as Redis Streams, Kafka,
    NATS, RabbitMQ, etc.

    Implementations should handle:
    - Connection management
    - Message publishing to topics
    - Consumer group subscriptions with callbacks
    - Consumer group management (creation, deletion)
    - Dead-letter queue (DLQ) handling
    - Consumer status monitoring

    Note:
        All methods are async and should be implemented as coroutines.
    """

    @abstractmethod
    async def connect(self) -> None:
        """
        Establish connection to the event bus backend.

        This method should initialize the connection to the underlying messaging
        system. It should be idempotent - calling it multiple times should be safe.

        Raises:
            ConnectionError: If connection to the event bus fails
        """
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        """
        Close connection to the event bus and cleanup resources.

        This method should gracefully close all connections, cancel any ongoing
        subscriptions, and release resources. It should be idempotent.

        Note:
            After calling close(), the event bus should be reconnected via connect()
            before use.
        """
        raise NotImplementedError

    @abstractmethod
    async def publish(self, event_payload: Dict[str, Any]) -> str:
        """
        Publish an event to a topic.

        Args:
            event_payload: Dictionary containing event data. Must include:
                - topic: The topic name to publish to
                - id: Optional task/event ID
                - payload: Dictionary with message content, webhook, reply_to, etc.
                - correlation_id: Optional correlation ID for distributed tracing
                - causation_id: Optional causation ID for event sourcing
                - source: Optional source identifier
                - delivery_attempts: Optional delivery attempt counter

        Returns:
            The task ID or message ID of the published event

        Raises:
            ValueError: If event_payload is missing required fields (e.g., topic)
            ConnectionError: If event bus is not connected
        """
        raise NotImplementedError

    @abstractmethod
    async def subscribe(
        self,
        topic: str,
        agent_name: str,
        callback: Callable[[Dict[str, Any]], Any],
        config: Dict[str, Any] = {},
    ) -> None:
        """
        Subscribe an agent callback to a topic.

        This method creates a consumer group (if needed) and starts consuming messages
        from the specified topic. Messages are delivered to the callback function.

        Args:
            topic: The topic name to subscribe to
            agent_name: Unique identifier for the agent/consumer
            callback: Callable function to process messages. Can be async or sync.
                     Receives a dictionary with message data.
            config: Optional configuration dictionary with:
                - consumer_count: Number of concurrent consumers (default: 1)
                - reclaim_idle_ms: Time in milliseconds before reclaiming pending messages
                - dlq_retry_limit: Maximum retry attempts before sending to DLQ

        Raises:
            ValueError: If topic or agent_name is invalid
            ConnectionError: If event bus is not connected
        """
        raise NotImplementedError

    @abstractmethod
    async def unsubscribe(
        self,
        topic: str,
        agent_name: str,
        delete_group: bool = False,
        delete_dlq: bool = False,
    ) -> None:
        """
        Unsubscribe an agent from a topic.

        This method stops message consumption for the specified agent and optionally
        cleans up the consumer group and dead-letter queue.

        Args:
            topic: The topic name to unsubscribe from
            agent_name: The agent/consumer identifier to unsubscribe
            delete_group: If True, permanently delete the consumer group
            delete_dlq: If True, permanently delete the associated dead-letter queue

        Note:
            If delete_group is False, the consumer group is preserved and can be
            resumed later. If delete_dlq is False, failed messages remain in the DLQ.
        """
        raise NotImplementedError

    @abstractmethod
    async def get_consumers(self) -> Dict[str, Any]:
        """
        Return current consumers and their configurations.

        This method provides a snapshot of all active consumer groups, including
        their topics, consumer counts, pending messages, and configuration.

        Returns:
            Dictionary mapping consumer group names to their metadata:
                - topic: The subscribed topic
                - stream: The underlying stream/channel name
                - consumers_count: Number of active consumers
                - pending_messages: Number of unprocessed messages
                - config: Consumer group configuration
        """
        raise NotImplementedError
