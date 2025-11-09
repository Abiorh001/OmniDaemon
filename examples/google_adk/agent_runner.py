import os  # Required for path operations
from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from decouple import config
from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.genai import types
import asyncio
import logging
from dotenv import load_dotenv
from google.adk.models.lite_llm import LiteLlm
from omnidaemon import OmniDaemonSDK, start_api_server, AgentConfig, SubscriptionConfig

load_dotenv()
# api_key = os.getenv("GOOGLE_API_KEY")
api_key = os.getenv("OPENAI_API_KEY")


sdk = OmniDaemonSDK()


logger = logging.getLogger(__name__)


TARGET_FOLDER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "/home/abiorh/ai/google_adk_file_system"
)


filesystem_agent = LlmAgent(
    # model="gemini-2.0-flash",
    model=LiteLlm(model="openai/gpt-4.1"),
    # model=LiteLlm(model="gemini/gemini-2.0-flash"),
    name="filesystem_assistant_agent",
    instruction="Help the user manage their files. You can list files, read files, etc.",
    tools=[
        McpToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command="npx",
                    args=[
                        "-y",
                        "@modelcontextprotocol/server-filesystem",
                        os.path.abspath(TARGET_FOLDER_PATH),
                    ],
                ),
                timeout=60,
            ),
        )
    ],
)


# --- Session Management ---
# Key Concept: SessionService stores conversation history & state.
# InMemorySessionService is simple, non-persistent storage for this tutorial.
session_service = InMemorySessionService()

# Define constants for identifying the interaction context
APP_NAME = "filesystem_agent"
USER_ID = "user_1"
SESSION_ID = "session_001"


# Create the specific session where the conversation will happen
async def create_session():
    await session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=SESSION_ID
    )


# --- Runner ---
# Key Concept: Runner orchestrates the agent execution loop.
runner = Runner(
    agent=filesystem_agent, app_name=APP_NAME, session_service=session_service
)


async def call_file_system_agent(message: dict):
    """Sends a query to the agent and prints the final response."""
    await create_session()
    query = message.get("content")
    if not query:
        return "No content in the message payload"
    logger.info(f"\n>>> User Query: {query}")

    content = types.Content(role="user", parts=[types.Part(text=query)])

    final_response_text = "Agent did not produce a final response."  # Default

    async for event in runner.run_async(
        user_id=USER_ID, session_id=SESSION_ID, new_message=content
    ):
        if event.is_final_response():
            if event.content and event.content.parts:
                # Assuming text response in the first part
                final_response_text = event.content.parts[0].text
            elif (
                event.actions and event.actions.escalate
            ):  # Handle potential errors/escalations
                final_response_text = (
                    f"Agent escalated: {event.error_message or 'No specific message.'}"
                )
            # Add more checks here if needed (e.g., specific error codes)
            break  # Stop processing events once the final response is found

    print(f"<<< Agent Response: {final_response_text}")
    return final_response_text


async def main():
    try:
        # Register agents
        logger.info("Registering Google ADK agents...")
        await sdk.register_agent(
            agent_config=AgentConfig(
                name="GOOGLE_ADK_FILESYSTEM_AGENT",
                topic="file_system.tasks",
                callback=call_file_system_agent,
                description="Help the user manage their files. You can list files, read files, etc.",
                tools=[],
                config=SubscriptionConfig(
                    reclaim_idle_ms=6000, dlq_retry_limit=3, consumer_count=3
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
