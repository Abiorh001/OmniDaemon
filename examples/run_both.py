import asyncio
import logging
from decouple import config
from examples.omnicoreagent.agent_runner import (
    call_file_system_agent as call_file_system_agent_omnicoreagent,
)
from examples.google_adk.agent_runner import (
    call_file_system_agent as call_file_system_agent_google_adk,
)
from omnidaemon import AgentConfig, SubscriptionConfig, OmniDaemonSDK, start_api_server


sdk = OmniDaemonSDK()
logger = logging.getLogger(__name__)


async def main():
    try:
        # Register agents for multiple topics
        logger.info("Registering agents from multiple frameworks...")
        await sdk.register_agent(
            agent_config=AgentConfig(
                name="OMNICOREAGENT_FILESYSTEM_AGENT",
                topic="file_system.tasks",
                callback=call_file_system_agent_omnicoreagent,
                description="Help the user manage their files. You can list files, read files, etc.",
                tools=[],
                config=SubscriptionConfig(
                    reclaim_idle_ms=60000, dlq_retry_limit=1, consumer_count=3
                ),
            )
        )

        await sdk.register_agent(
            agent_config=AgentConfig(
                name="GOOGLE_ADK_FILESYSTEM_AGENT",
                topic="file_system.tasks",
                callback=call_file_system_agent_google_adk,
                description="Help the user manage their files. You can list files, read files, etc.",
                tools=[],
                config=SubscriptionConfig(
                    reclaim_idle_ms=50000,
                    dlq_retry_limit=5,
                    consumer_count=2,
                ),
            )
        )
        logger.info("Agents registered successfully")

        # Start the agent runner
        logger.info("Starting OmniDaemon agent runner...")
        await sdk.start()
        logger.info("OmniDaemon agent runner started")

        # Start API server if enabled
        enable_api = config("OMNIDAEMON_API_ENABLED", default=False, cast=bool)
        api_port = config("OMNIDAEMON_API_PORT", default=8765, cast=int)
        if enable_api:
            asyncio.create_task(start_api_server(sdk, port=api_port))
            logger.info(f"OmniDaemon API running on http://127.0.0.1:{api_port}")

        # Keep running to listen to new messages
        logger.info("Agent runner is now processing events. Press Ctrl+C to stop.")
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            logger.info("Received shutdown signal (Ctrl+C)...")

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Received shutdown signal...")
    except Exception as e:
        logger.error(f"Error during agent runner execution: {e}", exc_info=True)
        raise

    finally:
        # Always cleanup, even if there was an error
        logger.info("Shutting down OmniDaemon...")
        try:
            await sdk.shutdown()
            logger.info("OmniDaemon shutdown complete")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}", exc_info=True)


# -----------------------------
# Run the example
# -----------------------------
if __name__ == "__main__":
    asyncio.run(main())
