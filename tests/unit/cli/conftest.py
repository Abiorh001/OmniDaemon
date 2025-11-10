"""Pytest configuration for CLI tests."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# Patch OmniDaemonSDK at module level before any imports
_mock_sdk_patcher = None
_mock_sdk_instance = None


def pytest_configure(config):
    """Configure pytest - patch SDK before any test imports."""
    global _mock_sdk_patcher, _mock_sdk_instance

    # Check if CLI tests are being collected
    # We'll patch in pytest_runtest_setup to avoid affecting SDK tests
    pass


def pytest_unconfigure(config):
    """Cleanup after tests."""
    global _mock_sdk_patcher
    if _mock_sdk_patcher:
        _mock_sdk_patcher.stop()
        _mock_sdk_patcher = None


def pytest_runtest_setup(item):
    """Setup hook - patch SDK before CLI tests, unpatch before non-CLI tests."""
    global _mock_sdk_patcher, _mock_sdk_instance

    is_cli_test = "cli" in str(item.nodeid)

    if is_cli_test:
        # CLI test - ensure patch is active
        if _mock_sdk_patcher is None:
            # Create mock SDK instance
            _mock_sdk_instance = MagicMock()
            _mock_sdk_instance.list_agents = AsyncMock(return_value={})
            _mock_sdk_instance.get_agent = AsyncMock(return_value=None)
            _mock_sdk_instance.unsubscribe_agent = AsyncMock(return_value=True)
            _mock_sdk_instance.delete_agent = AsyncMock(return_value=True)
            _mock_sdk_instance.delete_topic = AsyncMock(return_value=0)
            _mock_sdk_instance.publish_task = AsyncMock(return_value="test-task-id")
            _mock_sdk_instance.get_result = AsyncMock(return_value=None)
            _mock_sdk_instance.list_results = AsyncMock(return_value=[])
            _mock_sdk_instance.delete_result = AsyncMock(return_value=True)
            _mock_sdk_instance.list_streams = AsyncMock(return_value=[])
            _mock_sdk_instance.inspect_stream = AsyncMock(return_value=[])
            _mock_sdk_instance.list_groups = AsyncMock(return_value=[])
            _mock_sdk_instance.inspect_dlq = AsyncMock(return_value=[])
            _mock_sdk_instance.get_bus_stats = AsyncMock(
                return_value={
                    "snapshot": {"topics": {}},
                    "redis_info": {"used_memory_human": "1MB"},
                }
            )
            _mock_sdk_instance.health = AsyncMock(return_value={"status": "healthy"})
            _mock_sdk_instance.storage_health = AsyncMock(
                return_value={"status": "healthy", "backend": "redis"}
            )
            _mock_sdk_instance.clear_agents = AsyncMock(return_value=0)
            _mock_sdk_instance.clear_results = AsyncMock(return_value=0)
            _mock_sdk_instance.clear_metrics = AsyncMock(return_value=0)
            _mock_sdk_instance.clear_all = AsyncMock(
                return_value={"agents": 0, "results": 0, "metrics": 0, "config": 0}
            )
            _mock_sdk_instance.save_config = AsyncMock()
            _mock_sdk_instance.get_config = AsyncMock(return_value=None)
            _mock_sdk_instance.metrics = AsyncMock(return_value={})

            # Patch the SDK class to return our mock
            _mock_sdk_patcher = patch(
                "omnidaemon.sdk.OmniDaemonSDK", return_value=_mock_sdk_instance
            )
            _mock_sdk_patcher.start()

        # The SDK instance will be patched by the mock_sdk fixture in test_main.py
    else:
        # Non-CLI test - ensure patch is stopped
        if _mock_sdk_patcher is not None:
            _mock_sdk_patcher.stop()
            _mock_sdk_patcher = None


def pytest_runtest_teardown(item):
    """Teardown hook - restore patch state after test."""
    global _mock_sdk_patcher

    is_cli_test = "cli" in str(item.nodeid)

    if not is_cli_test and _mock_sdk_patcher is None:
        # Non-CLI test finished, patch was already stopped
        pass
    # For CLI tests, keep patch active for next CLI test


@pytest.fixture(scope="session")
def patch_sdk_class_for_cli_tests():
    """Provide the mocked SDK instance for CLI tests."""
    global _mock_sdk_instance
    return _mock_sdk_instance
