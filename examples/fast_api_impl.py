# app.py
from fastapi import FastAPI, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional
import logging
from contextlib import asynccontextmanager

from decouple import config

from omnidaemon.result_store import RedisResultStore
from omnidaemon.sdk import OmniDaemonSDK
from omnicoreagent import OmniAgent, ToolRegistry, MemoryRouter, EventRouter


# ----------------------------
# Configuration & Globals
# ----------------------------
logger = logging.getLogger(__name__)

sdk = OmniDaemonSDK(
    result_store=RedisResultStore(
        redi_url=config("REDIS_URL", default="redis://localhost")
    )
)

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

# Agent runner instance (managed in lifespan)
filesystem_agent_runner: Optional["OmniAgentRunner"] = None


# ----------------------------
# Agent Runner Class
# ----------------------------
class OmniAgentRunner:
    def __init__(self):
        self.agent: Optional[OmniAgent] = None
        self.memory_router: Optional[MemoryRouter] = None
        self.event_router: Optional[EventRouter] = None
        self.connected = False
        self.session_id: Optional[str] = None

    async def initialize(self):
        if self.connected:
            return
        logger.info("🚀 Initializing OmniAgent...")
        self.memory_router = MemoryRouter("in_memory")
        self.event_router = EventRouter("in_memory")

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
                "request_limit": 0,
                "total_tokens_limit": 0,
                "memory_config": {"mode": "sliding_window", "value": 100},
                "memory_results_limit": 5,
                "memory_similarity_threshold": 0.5,
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
        logger.info("✅ OmniAgent initialized successfully")

    async def handle_chat(self, message: str) -> str:
        if not self.agent:
            raise RuntimeError("Agent not initialized")
        if not self.session_id:
            from datetime import datetime

            self.session_id = f"api_session_{datetime.now().strftime('%Y%m%dT%H%M%S')}"

        result = await self.agent.run(message)
        return result.get("response", "No response received")

    async def shutdown(self):
        if getattr(self.agent, "mcp_tools", None):
            try:
                await self.agent.cleanup()
                logger.info(f"{self.agent.name}: MCP cleanup successful")
            except Exception as exc:
                logger.warning(f"{self.agent.name}: MCP cleanup failed: {exc}")


# ----------------------------
# Lifespan (Startup / Shutdown)
# ----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global filesystem_agent_runner

    # --- Startup ---
    logger.info("Starting OmniDaemon FastAPI server...")

    # Initialize agent runner
    filesystem_agent_runner = OmniAgentRunner()
    await filesystem_agent_runner.initialize()

    # Register agent with SDK
    async def call_file_system_agent(message: Dict[str, Any]):
        logger.info("📁 Filesystem agent received task")
        if filesystem_agent_runner is None:
            raise RuntimeError("Agent runner not ready")
        response = await filesystem_agent_runner.handle_chat(message.get("content", ""))
        print(f"this is response: {response}")
        return {"status": "success", "data": response}

    await sdk.register_agent(
        name="OMNICOREAGENT_FILESYSTEM_AGENT",
        topic="file_system.tasks",
        callback=call_file_system_agent,
        agent_config={
            "description": "Help the user manage their files. You can list files, read files, etc.",
        },
    )

    # Start SDK message listener
    await sdk.start()
    logger.info("✅ OmniDaemon SDK started")

    # Optional: Start internal API server if needed (not required here)

    yield  # <-- App runs here

    # --- Shutdown ---
    logger.info("Shutting down OmniDaemon...")
    await sdk.stop()
    if filesystem_agent_runner and filesystem_agent_runner.agent:
        await filesystem_agent_runner.shutdown()
    logger.info("✅ Shutdown complete")


# ----------------------------
# FastAPI App
# ----------------------------
app = FastAPI(
    title="OmniDaemon Filesystem Agent",
    description="FastAPI wrapper for OmniCore filesystem agent with webhook callbacks",
    lifespan=lifespan,
)


# ----------------------------
# Schemas
# ----------------------------
class TaskResponse(BaseModel):
    status: str
    topic: str
    message: str


class AgentResultCallback(BaseModel):
    payload: Dict[str, Any]


class FileSystemTaskRequest(BaseModel):
    content: str
    webhook: Optional[str] = None  # Optional: override default callback


# ----------------------------
# Callback Endpoint (for agent results)
# ----------------------------
@app.post("/filesystem_agent_result", status_code=status.HTTP_200_OK)
async def filesystem_agent_callback(data: AgentResultCallback):
    """Webhook endpoint where agent posts its final result."""
    payload = data.payload
    print(f"📁 Filesystem Agent Result: {payload}")
    # logger.info(f"📁 Filesystem Agent Result: {payload}")
    # You can forward to user's webhook here if needed
    return {"status": "received"}


# ----------------------------
# User Task Trigger
# ----------------------------
@app.post(
    "/run_filesystem_task",
    response_model=TaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_filesystem_task(task: FileSystemTaskRequest):
    """
    Trigger the filesystem agent to perform file operations.
    """
    payload = {
        "content": task.content,
        "webhook": task.webhook or "http://localhost:8000/filesystem_agent_result",
    }
    await sdk.publish_task("file_system.tasks", payload)
    return TaskResponse(
        status="queued",
        topic="file_system.tasks",
        message="Filesystem task queued for processing.",
    )


# ----------------------------
# Health Check
# ----------------------------
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "agent_ready": bool(
            filesystem_agent_runner and filesystem_agent_runner.connected
        ),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
