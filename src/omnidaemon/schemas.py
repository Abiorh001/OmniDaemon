from pydantic import BaseModel, Field, field_validator
from typing import Any, Dict, Optional, Callable, List
import uuid
import time


class PayloadBase(BaseModel):
    """
    Base payload structure for event messages.

    This class defines the standard structure for message payloads that are
    sent through the event bus. It includes the main content and optional
    routing/response information.

    Attributes:
        content: The main content of the payload (required)
        webhook: Optional webhook URL for asynchronous callbacks when task completes
        reply_to: Optional topic name where the response should be published
    """

    content: str = Field(..., description="The main content of the payload.")
    webhook: Optional[str] = Field(
        None, description="Optional webhook URL for callbacks."
    )
    reply_to: Optional[str] = Field(
        None,
        description="Optional topic that should publish the final response to.",
    )


class EventEnvelope(BaseModel):
    """
    Complete event envelope for publishing tasks to OmniDaemon.

    This class represents a fully structured event that can be published to
    the event bus. It includes all metadata needed for event sourcing, distributed
    tracing, and multi-tenancy support.

    Attributes:
        id: Globally unique event ID (UUID4). Auto-generated if not provided.
        topic: Event topic name (e.g., 'file_system.tasks'). Required.
        payload: Business payload containing content, webhook, and reply_to.
        tenant_id: Optional tenant identifier for multi-tenancy isolation.
        created_at: Unix timestamp (seconds) when event was created. Auto-generated.
        delivery_attempts: Number of delivery attempts (starts at 1, incremented on retry).
        correlation_id: ID for tracing request flow across services.
        causation_id: ID of the event/command that caused this event.
        source: Service or component that published this event.

    Example:
        ```python
        event = EventEnvelope(
            topic="file_system.tasks",
            payload=PayloadBase(
                content="list_files",
                webhook="https://example.com/callback",
                reply_to="file_system.responses"
            ),
            correlation_id="req-123",
            causation_id="causation-123",
            tenant_id="tenant-123",
            created_at=time.time(),
            delivery_attempts=1,
            source="web-api"
        )
        ```
    """

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Globally unique event ID (UUID4).",
    )
    topic: str = Field(..., description="Event topic (e.g., 'file_system.tasks').")
    payload: PayloadBase = Field(..., description="Business payload.")
    tenant_id: Optional[str] = Field(
        None, description="Tenant identifier for multi-tenancy isolation."
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp (seconds) when event was created.",
    )
    delivery_attempts: int = Field(
        default=1,
        ge=1,
        description="Number of times this event has been delivered (incremented on retry).",
    )
    correlation_id: Optional[str] = Field(
        None,
        description="ID to trace a request flow across services (e.g., HTTP X-Correlation-ID).",
    )
    causation_id: Optional[str] = Field(
        None, description="ID of the event/command that caused this event."
    )
    source: Optional[str] = Field(
        None,
        description="Service or component that published this event (e.g., 'web-api', 'scheduler').",
    )

    @field_validator("topic")
    @classmethod
    def validate_topic(cls, v: str) -> str:
        """
        Validate topic name.

        Ensures the topic is a non-empty string and doesn't contain
        reserved DLQ keywords.

        Args:
            v: Topic name to validate

        Returns:
            Validated and stripped topic name

        Raises:
            ValueError: If topic is empty or contains reserved keywords
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("Topic must be a non-empty string")
        if stripped.startswith("omni-dlq:") or ":dlq" in stripped:
            raise ValueError(
                "Topic must not contain 'dlq' (reserved for dead-letter queues)"
            )
        return stripped


class SubscriptionConfig(BaseModel):
    """
    Configuration for agent subscription to a topic.

    This class defines configuration options for how an agent consumes messages
    from a topic, including retry behavior, message reclaiming, and concurrency.

    Attributes:
        reclaim_idle_ms: Time in milliseconds after which idle/pending messages
                         are reclaimed for retry. Only applies to event buses that
                         support message reclaiming (e.g., Redis Streams).
        dlq_retry_limit: Maximum number of retry attempts before sending a message
                        to the dead-letter queue. Only applies to event buses that
                        support DLQ (e.g., Redis Streams).
        consumer_count: Number of parallel consumers for load balancing. Must be
                       at least 1. Higher values allow concurrent message processing.
    """

    reclaim_idle_ms: Optional[int] = Field(
        None,
        description="Time in milliseconds after which idle messages are reclaimed if the event bus supports it.",
    )
    dlq_retry_limit: Optional[int] = Field(
        None,
        description="Number of retries before sending message to dead-letter queue if the event bus supports it.",
    )
    consumer_count: Optional[int] = Field(
        1,
        ge=1,
        description="Number of parallel consumers for this subscription (if supported by the event bus).",
    )


class AgentConfig(BaseModel):
    """
    Configuration for registering an agent with OmniDaemon.

    This class defines all the information needed to register an agent that will
    process messages from a specific topic. The agent callback function is where
    your AI agent or business logic runs.

    Attributes:
        name: Unique name for the agent. Auto-generated if not provided.
        topic: Topic name to which the agent subscribes. Required.
        callback: Callable function (async or sync) to handle incoming messages.
                 This is where your agent logic runs. Required.
        tools: Optional list of tool names available to the agent.
        description: Optional description of the agent's purpose and capabilities.
        config: Optional subscription configuration for retry behavior, concurrency, etc.

    Example:
        ```python
        agent_config = AgentConfig(
            name="my_agent",
            topic="file_system.tasks",
            callback=my_agent_function,
            description="Handles file system operations",
            tools=["filesystem", "search"],
            config=SubscriptionConfig(
                consumer_count=3,
                reclaim_idle_ms=180000,
                dlq_retry_limit=3
            )
        )
        ```
    """

    name: str = Field(
        default_factory=lambda: f"agent-{str(uuid.uuid4())}",
        description="Unique name for the agent.",
    )
    topic: str = Field(..., description="Topic to which the agent subscribes.")
    callback: Callable[[Dict[str, Any]], Any] = Field(
        ..., description="Async or sync function to handle incoming messages."
    )
    tools: Optional[List[str]] = Field(
        default_factory=list, description="List of tools available to the agent."
    )
    description: Optional[str] = Field(
        "", description="Description of the agent's purpose."
    )
    config: Optional[SubscriptionConfig] = Field(
        default_factory=lambda: SubscriptionConfig(
            reclaim_idle_ms=None, dlq_retry_limit=None, consumer_count=1
        ),
        description="Configuration for the agent's subscription.",
    )
