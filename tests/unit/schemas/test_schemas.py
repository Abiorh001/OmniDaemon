"""Unit tests for schemas."""

import pytest
from pydantic import ValidationError
from omnidaemon.schemas import (
    PayloadBase,
    EventEnvelope,
    SubscriptionConfig,
    AgentConfig,
)


class TestPayloadBase:
    """Test suite for PayloadBase schema."""

    def test_payload_base_required_fields(self):
        """Test PayloadBase requires content."""
        # Should succeed with content
        payload = PayloadBase(content="test content")
        assert payload.content == "test content"

        # Should fail without content
        with pytest.raises(ValidationError) as exc_info:
            PayloadBase()
        assert "content" in str(exc_info.value).lower()

    def test_payload_base_optional_fields(self):
        """Test PayloadBase optional fields."""
        # All fields optional except content
        payload = PayloadBase(content="test")
        assert payload.content == "test"
        assert payload.webhook is None
        assert payload.reply_to is None

        # Can set optional fields
        payload = PayloadBase(
            content="test",
            webhook="https://example.com/webhook",
            reply_to="reply.topic",
        )
        assert payload.webhook == "https://example.com/webhook"
        assert payload.reply_to == "reply.topic"

    def test_payload_base_validation(self):
        """Test PayloadBase validation."""
        # Valid payload
        payload = PayloadBase(content="valid content")
        assert isinstance(payload, PayloadBase)

        # Content must be string
        with pytest.raises(ValidationError):
            PayloadBase(content=123)


class TestEventEnvelope:
    """Test suite for EventEnvelope schema."""

    def test_event_envelope_generates_id(self):
        """Test EventEnvelope generates ID if missing."""
        payload = PayloadBase(content="test")
        envelope = EventEnvelope(topic="test.topic", payload=payload)

        assert envelope.id is not None
        assert isinstance(envelope.id, str)
        # Should be a valid UUID format
        assert len(envelope.id) == 36  # UUID4 string length

    def test_event_envelope_preserves_id(self):
        """Test EventEnvelope preserves provided ID."""
        custom_id = "custom-id-123"
        payload = PayloadBase(content="test")
        envelope = EventEnvelope(id=custom_id, topic="test.topic", payload=payload)

        assert envelope.id == custom_id

    def test_event_envelope_required_fields(self):
        """Test EventEnvelope required fields."""
        payload = PayloadBase(content="test")

        # Should succeed with required fields
        envelope = EventEnvelope(topic="test.topic", payload=payload)
        assert envelope.topic == "test.topic"
        assert envelope.payload == payload

        # Should fail without topic
        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(payload=payload)
        assert "topic" in str(exc_info.value).lower()

        # Should fail without payload
        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(topic="test.topic")
        assert "payload" in str(exc_info.value).lower()

    def test_event_envelope_optional_fields(self):
        """Test EventEnvelope optional fields."""
        payload = PayloadBase(content="test")
        envelope = EventEnvelope(topic="test.topic", payload=payload)

        # Optional fields should have defaults or be None
        assert envelope.tenant_id is None
        assert envelope.correlation_id is None
        assert envelope.causation_id is None
        assert envelope.source is None

        # Can set optional fields
        envelope = EventEnvelope(
            topic="test.topic",
            payload=payload,
            tenant_id="tenant-123",
            correlation_id="corr-456",
            causation_id="cause-789",
            source="web-api",
        )
        assert envelope.tenant_id == "tenant-123"
        assert envelope.correlation_id == "corr-456"
        assert envelope.causation_id == "cause-789"
        assert envelope.source == "web-api"

    def test_event_envelope_generates_created_at(self):
        """Test EventEnvelope generates created_at."""
        import time

        payload = PayloadBase(content="test")

        before = time.time()
        envelope = EventEnvelope(topic="test.topic", payload=payload)
        after = time.time()

        assert envelope.created_at is not None
        assert isinstance(envelope.created_at, float)
        assert before <= envelope.created_at <= after

    def test_event_envelope_default_delivery_attempts(self):
        """Test EventEnvelope default delivery_attempts."""
        payload = PayloadBase(content="test")
        envelope = EventEnvelope(topic="test.topic", payload=payload)

        assert envelope.delivery_attempts == 1

    def test_event_envelope_topic_validation(self):
        """Test EventEnvelope topic validation."""
        payload = PayloadBase(content="test")

        # Valid topics
        envelope1 = EventEnvelope(topic="test.topic", payload=payload)
        assert envelope1.topic == "test.topic"

        envelope2 = EventEnvelope(topic="  spaced.topic  ", payload=payload)
        assert envelope2.topic == "spaced.topic"  # Should be stripped

        # Topic must be string
        with pytest.raises(ValidationError):
            EventEnvelope(topic=123, payload=payload)

    def test_event_envelope_topic_empty(self):
        """Test EventEnvelope rejects empty topic."""
        payload = PayloadBase(content="test")

        # Empty string
        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(topic="", payload=payload)
        assert "non-empty" in str(exc_info.value).lower()

        # Whitespace only
        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(topic="   ", payload=payload)
        assert "non-empty" in str(exc_info.value).lower()

    def test_event_envelope_topic_dlq_reserved(self):
        """Test EventEnvelope rejects DLQ topics."""
        payload = PayloadBase(content="test")

        # Topics starting with omni-dlq:
        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(topic="omni-dlq:test", payload=payload)
        assert "dlq" in str(exc_info.value).lower()

        # Topics containing :dlq
        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(topic="test:dlq", payload=payload)
        assert "dlq" in str(exc_info.value).lower()

        # Topics containing dlq in middle
        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(topic="test:dlq:something", payload=payload)
        assert "dlq" in str(exc_info.value).lower()

    def test_event_envelope_delivery_attempts_min(self):
        """Test EventEnvelope delivery_attempts minimum."""
        payload = PayloadBase(content="test")

        # Minimum is 1
        envelope = EventEnvelope(
            topic="test.topic", payload=payload, delivery_attempts=1
        )
        assert envelope.delivery_attempts == 1

        # Can be greater than 1
        envelope = EventEnvelope(
            topic="test.topic", payload=payload, delivery_attempts=5
        )
        assert envelope.delivery_attempts == 5

        # Cannot be less than 1
        with pytest.raises(ValidationError) as exc_info:
            EventEnvelope(topic="test.topic", payload=payload, delivery_attempts=0)
        assert (
            "greater" in str(exc_info.value).lower()
            or "minimum" in str(exc_info.value).lower()
        )

        # Cannot be negative
        with pytest.raises(ValidationError):
            EventEnvelope(topic="test.topic", payload=payload, delivery_attempts=-1)


class TestSubscriptionConfig:
    """Test suite for SubscriptionConfig schema."""

    def test_subscription_config_optional_fields(self):
        """Test SubscriptionConfig all fields optional."""
        # Can create with no fields
        config = SubscriptionConfig()
        assert config.reclaim_idle_ms is None
        assert config.dlq_retry_limit is None
        assert config.consumer_count == 1  # Has default

        # Can set all fields
        config = SubscriptionConfig(
            reclaim_idle_ms=5000, dlq_retry_limit=3, consumer_count=2
        )
        assert config.reclaim_idle_ms == 5000
        assert config.dlq_retry_limit == 3
        assert config.consumer_count == 2

    def test_subscription_config_consumer_count_min(self):
        """Test SubscriptionConfig consumer_count minimum."""
        # Minimum is 1
        config = SubscriptionConfig(consumer_count=1)
        assert config.consumer_count == 1

        # Can be greater than 1
        config = SubscriptionConfig(consumer_count=5)
        assert config.consumer_count == 5

        # Cannot be less than 1
        with pytest.raises(ValidationError) as exc_info:
            SubscriptionConfig(consumer_count=0)
        assert (
            "greater" in str(exc_info.value).lower()
            or "minimum" in str(exc_info.value).lower()
        )

        # Cannot be negative
        with pytest.raises(ValidationError):
            SubscriptionConfig(consumer_count=-1)

    def test_subscription_config_defaults(self):
        """Test SubscriptionConfig defaults."""
        config = SubscriptionConfig()

        # consumer_count defaults to 1
        assert config.consumer_count == 1

        # Other fields default to None
        assert config.reclaim_idle_ms is None
        assert config.dlq_retry_limit is None


class TestAgentConfig:
    """Test suite for AgentConfig schema."""

    def test_agent_config_generates_name(self):
        """Test AgentConfig generates name if missing."""

        async def dummy_callback(message):
            pass

        # Should generate name if not provided
        config = AgentConfig(topic="test.topic", callback=dummy_callback)
        assert config.name is not None
        assert isinstance(config.name, str)
        assert config.name.startswith("agent-")

        # Generated name should be unique
        config2 = AgentConfig(topic="test.topic", callback=dummy_callback)
        assert config.name != config2.name

    def test_agent_config_required_fields(self):
        """Test AgentConfig required fields."""

        async def dummy_callback(message):
            pass

        # Should succeed with required fields
        config = AgentConfig(topic="test.topic", callback=dummy_callback)
        assert config.topic == "test.topic"
        assert config.callback == dummy_callback

        # Should fail without topic
        with pytest.raises(ValidationError) as exc_info:
            AgentConfig(callback=dummy_callback)
        assert "topic" in str(exc_info.value).lower()

        # Should fail without callback
        with pytest.raises(ValidationError) as exc_info:
            AgentConfig(topic="test.topic")
        assert "callback" in str(exc_info.value).lower()

    def test_agent_config_optional_fields(self):
        """Test AgentConfig optional fields."""

        async def dummy_callback(message):
            pass

        config = AgentConfig(topic="test.topic", callback=dummy_callback)

        # Optional fields should have defaults
        assert config.tools == []
        assert config.description == ""
        assert isinstance(config.config, SubscriptionConfig)

        # Can set optional fields
        config = AgentConfig(
            topic="test.topic",
            callback=dummy_callback,
            name="custom-agent",
            tools=["tool1", "tool2"],
            description="Test agent",
        )
        assert config.name == "custom-agent"
        assert config.tools == ["tool1", "tool2"]
        assert config.description == "Test agent"

    def test_agent_config_default_subscription_config(self):
        """Test AgentConfig default SubscriptionConfig."""

        async def dummy_callback(message):
            pass

        config = AgentConfig(topic="test.topic", callback=dummy_callback)

        # Should have default SubscriptionConfig
        assert isinstance(config.config, SubscriptionConfig)
        assert config.config.consumer_count == 1
        assert config.config.reclaim_idle_ms is None
        assert config.config.dlq_retry_limit is None

        # Can provide custom SubscriptionConfig
        custom_config = SubscriptionConfig(consumer_count=3, reclaim_idle_ms=10000)
        config = AgentConfig(
            topic="test.topic", callback=dummy_callback, config=custom_config
        )
        assert config.config.consumer_count == 3
        assert config.config.reclaim_idle_ms == 10000
