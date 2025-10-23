from omnicoreagent import OmniAgent, ToolRegistry, MemoryRouter, EventRouter
from typing import Optional
import asyncio
import logging
from decouple import config
from redis import asyncio as aioredis
from src.omnidaemon.result_store import RedisResultStore
from src.omnidaemon.sdk import OmniDaemonSDK
from src.omnidaemon.api.server import start_api_server
from examples.omnicoreagent.agent_runner import (
    call_file_system_agent as call_file_system_agent_omnicoreagent,
)
from examples.google_adk.agent_runner import (
    call_file_system_agent as call_file_system_agent_google_adk,
)

redis = aioredis.from_url("redis://localhost")
sdk = OmniDaemonSDK(result_store=RedisResultStore(redis))
logger = logging.getLogger(__name__)


async def main():
    # Register agents for multiple topics
    await sdk.register_agent(
        name="OMNICOREAGENT_FILESYSTEM_AGENT",
        topic="file_system.tasks",
        callback=call_file_system_agent_omnicoreagent,
        agent_config={
            "description": "Help the user manage their files. You can list files, read files, etc.",
        },
    )

    await sdk.register_agent(
        name="GOOGLE_ADK_FILESYSTEM_AGENT",
        topic="file_system.tasks",
        callback=call_file_system_agent_google_adk,
        agent_config={
            "description": "Help the user manage their files. You can list files, read files, etc.",
        },
    )

    # Start the agent runner
    await sdk.start()

    # ✅ Start API server separately (optional)

    enable_api = config("OMNIDAEMON_API_ENABLED", default=False, cast=bool)
    api_port = config("OMNIDAEMON_API_PORT", default=8765, cast=int)
    if enable_api:
        asyncio.create_task(start_api_server(sdk, port=api_port))
        logger.info(f"OmniDaemon API running on http://127.0.0.1:{api_port}")

    # Keep running to listen to new messages
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("Stopping...")
        await sdk.stop()


# -----------------------------
# Run the example
# -----------------------------
if __name__ == "__main__":
    asyncio.run(main())
