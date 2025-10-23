from omnicoreagent import OmniAgent, ToolRegistry, MemoryRouter, EventRouter
from typing import Optional
import asyncio
import logging
from decouple import config
from src.omnidaemon.result_store import RedisResultStore
from src.omnidaemon.sdk import OmniDaemonSDK
from src.omnidaemon.api.server import start_api_server


sdk = OmniDaemonSDK(
    result_store=RedisResultStore(
        redi_url=config("REDIS_URL", default="redis://localhost")
    )
)


logger = logging.getLogger(__name__)

tool_registry = ToolRegistry()

MCP_TOOLS = [
    {
        "name": "filesystem",
        "command": "npx",
        "args": [
            "-y",
            "@modelcontextprotocol/server-filesystem",
            "/home/abiorh/ai/omi_file_system",
        ],
    },
]


class OmniAgentRunner:
    """Comprehensive CLI interface for OmniAgent."""

    def __init__(self):
        """Initialize the CLI interface."""
        self.agent: Optional[OmniAgent] = None
        self.memory_router: Optional[MemoryRouter] = None
        self.event_router: Optional[EventRouter] = None
        self.connected = False

        self.session_id: Optional[str] = None

    async def initialize(self):
        """Initialize all components."""
        print(f"connectedd: {self.connected}")
        print("🚀 Initializing OmniAgent CLI...")
        if self.connected:
            print("already initiazlied")
            return

        # Initialize routers
        self.memory_router = MemoryRouter("in_memory")
        self.event_router = EventRouter("in_memory")

        # Initialize agent with exact same config as working example
        self.agent = OmniAgent(
            name="filesystem_assistant_agent",
            system_instruction="Help the user manage their files. You can list files, read files, etc.",
            model_config={
                "provider": "openai",
                "model": "gpt-4.1",
                "temperature": 0,
                "max_context_length": 1000,
            },
            mcp_tools=MCP_TOOLS,
            agent_config={
                "agent_name": "OmniAgent",
                "max_steps": 15,
                "tool_call_timeout": 20,
                "request_limit": 0,  # 0 = unlimited
                "total_tokens_limit": 0,  # or 0 for unlimited
                # --- Memory Retrieval Config ---
                "memory_config": {"mode": "sliding_window", "value": 100},
                "memory_results_limit": 5,
                "memory_similarity_threshold": 0.5,
                # --- Tool Retrieval Config ---
                "enable_tools_knowledge_base": False,
                "tools_results_limit": 10,
                "tools_similarity_threshold": 0.1,
            },
            memory_router=self.memory_router,
            event_router=self.event_router,
            debug=False,
        )
        await self.agent.connect_mcp_servers()
        self.connected = True

        print("✅ OmniAgent CLI initialized successfully")
        print(f"connectedd: {self.connected}")

    async def handle_chat(self, message: str):
        """Handle chat messages."""
        print(f"connectedd: {self.connected}")
        if not self.agent:
            print("❌ Agent not initialized")
            return

        print(f"🤖 Processing: {message}")

        # Generate session ID if not exists
        if not self.session_id:
            from datetime import datetime

            self.session_id = (
                f"cli_session_{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}"
            )

        try:
            # Run the agent and get response
            result = await self.agent.run(message)
            response = result.get("response", "No response received")
            return response
        except Exception as e:
            print(f"❌ Error: {e}")

    async def shutdown(self):
        if getattr(self.agent, "mcp_tools", None):
            try:
                await self.agent.cleanup()
                logger.info(f"{self.agent.name}: MCP cleanup successful")
            except Exception as exc:
                logger.warning(f"{self.agent.name}: MCP cleanup failed: {exc}")


filesystem_agent_runner = OmniAgentRunner()


async def call_file_system_agent(message: dict):
    print("document agent get task")
    await filesystem_agent_runner.initialize()
    result = await filesystem_agent_runner.handle_chat(message=message.get("content"))
    return {"status": "success", "data": result}


async def main():
    # Register agents for multiple topics
    await sdk.register_agent(
        name="OMNICOREAGENT_FILESYSTEM_AGENT",
        topic="file_system.tasks",
        callback=call_file_system_agent,
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
