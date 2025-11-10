"""Unit tests for BaseEventBus abstract class."""

import pytest
from abc import ABC
from omnidaemon.event_bus.base import BaseEventBus


class TestBaseEventBus:
    """Test suite for BaseEventBus abstract interface."""

    def test_base_event_bus_is_abstract(self):
        """Verify BaseEventBus cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseEventBus()

    def test_base_event_bus_has_connect_method(self):
        """Verify connect() abstract method exists."""
        assert hasattr(BaseEventBus, "connect")
        assert getattr(BaseEventBus.connect, "__isabstractmethod__", False)

    def test_base_event_bus_has_close_method(self):
        """Verify close() abstract method exists."""
        assert hasattr(BaseEventBus, "close")
        assert getattr(BaseEventBus.close, "__isabstractmethod__", False)

    def test_base_event_bus_has_publish_method(self):
        """Verify publish() abstract method exists."""
        assert hasattr(BaseEventBus, "publish")
        assert getattr(BaseEventBus.publish, "__isabstractmethod__", False)

    def test_base_event_bus_has_subscribe_method(self):
        """Verify subscribe() abstract method exists."""
        assert hasattr(BaseEventBus, "subscribe")
        assert getattr(BaseEventBus.subscribe, "__isabstractmethod__", False)

    def test_base_event_bus_has_unsubscribe_method(self):
        """Verify unsubscribe() abstract method exists."""
        assert hasattr(BaseEventBus, "unsubscribe")
        assert getattr(BaseEventBus.unsubscribe, "__isabstractmethod__", False)

    def test_base_event_bus_has_get_consumers_method(self):
        """Verify get_consumers() abstract method exists."""
        assert hasattr(BaseEventBus, "get_consumers")
        assert getattr(BaseEventBus.get_consumers, "__isabstractmethod__", False)

    def test_concrete_implementation_required(self):
        """Verify concrete implementations must implement all methods."""

        # Create a partial implementation
        class IncompleteEventBus(BaseEventBus):
            async def connect(self):
                pass

            async def close(self):
                pass

            async def publish(self, event_payload):
                pass

            # Missing subscribe, unsubscribe, get_consumers

        # Should raise TypeError when trying to instantiate
        with pytest.raises(TypeError):
            IncompleteEventBus()

        # Complete implementation should work
        class CompleteEventBus(BaseEventBus):
            async def connect(self):
                pass

            async def close(self):
                pass

            async def publish(self, event_payload):
                return "test-id"

            async def subscribe(self, topic, agent_name, callback, config=None):
                pass

            async def unsubscribe(
                self, topic, agent_name, delete_group=False, delete_dlq=False
            ):
                pass

            async def get_consumers(self):
                return {}

        # Complete implementation should be instantiable
        bus = CompleteEventBus()
        assert isinstance(bus, BaseEventBus)
        assert isinstance(bus, ABC)
