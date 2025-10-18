from omnicoreagent import OmniAgent, ToolRegistry, MemoryRouter, EventRouter
from typing import Optional
import asyncio
import logging
from decouple import config
from redis import asyncio as aioredis
from src.omnidaemon.result_store import RedisResultStore
from src.omnidaemon.sdk import OmniDaemonSDK
from src.omnidaemon.api.server import start_api_server


redis = aioredis.from_url("redis://localhost")
sdk = OmniDaemonSDK(result_store=RedisResultStore(redis))


logger = logging.getLogger(__name__)

tool_registry = ToolRegistry()


class OmniAgentRunner:
    """Comprehensive CLI interface for OmniAgent."""

    def __init__(self):
        """Initialize the CLI interface."""
        self.agent: Optional[OmniAgent] = None
        self.memory_router: Optional[MemoryRouter] = None
        self.event_router: Optional[EventRouter] = None
        self.connected = False

        self.session_id: Optional[str] = None

    # Mathematical tools
    @tool_registry.register_tool("calculate_area")
    def calculate_area(length: float, width: float) -> str:
        """Calculate the area of a rectangle."""
        area = length * width
        return f"Area of rectangle ({length} x {width}): {area} square units"

    @tool_registry.register_tool("calculate_perimeter")
    def calculate_perimeter(length: float, width: float) -> str:
        """Calculate the perimeter of a rectangle."""
        perimeter = 2 * (length + width)
        return f"Perimeter of rectangle ({length} x {width}): {perimeter} units"

    # Text processing tools
    @tool_registry.register_tool("format_text")
    def format_text(text: str, style: str = "normal") -> str:
        """Format text in different styles."""
        if style == "uppercase":
            return text.upper()
        elif style == "lowercase":
            return text.lower()
        elif style == "title":
            return text.title()
        elif style == "reverse":
            return text[::-1]
        else:
            return text

    @tool_registry.register_tool("word_count")
    def word_count(text: str) -> str:
        """Count words in text."""
        words = text.split()
        return f"Word count: {len(words)} words"

    # System information tools
    @tool_registry.register_tool("system_info")
    def get_system_info() -> str:
        """Get basic system information."""
        import platform
        import time

        info = f"""System Information:
• OS: {platform.system()} {platform.release()}
• Architecture: {platform.machine()}
• Python Version: {platform.python_version()}
• Current Time: {time.strftime("%Y-%m-%d %H:%M:%S")}"""
        return info

    # Data analysis tools
    @tool_registry.register_tool("analyze_numbers")
    def analyze_numbers(numbers: str) -> str:
        """Analyze a list of numbers."""
        try:
            num_list = [float(x.strip()) for x in numbers.split(",")]
            if not num_list:
                return "No numbers provided"

            total = sum(num_list)
            average = total / len(num_list)
            minimum = min(num_list)
            maximum = max(num_list)

            return f"""Number Analysis:
• Count: {len(num_list)} numbers
• Sum: {total}
• Average: {average:.2f}
• Min: {minimum}
• Max: {maximum}"""
        except Exception as e:
            return f"Error analyzing numbers: {str(e)}"

    # File system tools
    @tool_registry.register_tool("list_directory")
    def list_directory(path: str = ".") -> str:
        """List contents of a directory."""
        import os

        try:
            if not os.path.exists(path):
                return f"Directory {path} does not exist"

            items = os.listdir(path)
            files = [item for item in items if os.path.isfile(os.path.join(path, item))]
            dirs = [item for item in items if os.path.isdir(os.path.join(path, item))]

            return f"""Directory: {path}
• Files: {len(files)} ({files[:5]}{"..." if len(files) > 5 else ""})
• Directories: {len(dirs)} ({dirs[:5]}{"..." if len(dirs) > 5 else ""})"""
        except Exception as e:
            return f"Error listing directory: {str(e)}"

    # Background agent specific tools (from working example)
    @tool_registry.register_tool("file_monitor")
    def monitor_files(directory: str = "/tmp") -> str:
        """Monitor files in a directory."""
        import os

        try:
            if not os.path.exists(directory):
                return f"Directory {directory} does not exist"

            files = os.listdir(directory)
            file_count = len(files)
            sample_files = files[:5] if files else []

            return (
                f"Found {file_count} files in {directory}. Sample files: {sample_files}"
            )
        except Exception as e:
            return f"Error monitoring directory {directory}: {str(e)}"

    @tool_registry.register_tool("system_status")
    def get_system_status() -> str:
        """Get realistic system status information."""
        import time
        import random

        # Generate realistic system metrics
        cpu_usage = random.uniform(5.0, 85.0)
        memory_usage = random.uniform(20.0, 90.0)
        disk_usage = random.uniform(30.0, 95.0)
        uptime_hours = random.randint(1, 720)  # 1 hour to 30 days
        active_processes = random.randint(50, 300)

        # Add some system alerts based on thresholds
        alerts = []
        if cpu_usage > 80:
            alerts.append("High CPU usage detected")
        if memory_usage > 85:
            alerts.append("High memory usage detected")
        if disk_usage > 90:
            alerts.append("Disk space running low")

        status_report = f"""System Status Report:
• CPU Usage: {cpu_usage:.1f}%
• Memory Usage: {memory_usage:.1f}%
• Disk Usage: {disk_usage:.1f}%
• System Uptime: {uptime_hours} hours
• Active Processes: {active_processes}
• Timestamp: {time.strftime("%Y-%m-%d %H:%M:%S")}"""

        if alerts:
            status_report += f"\n\n⚠️  Alerts: {'; '.join(alerts)}"

        return status_report

    @tool_registry.register_tool("log_analyzer")
    def analyze_logs(log_file: str = "/var/log/syslog") -> str:
        """Analyze log files for patterns."""
        import random
        import time

        try:
            # Simulate log analysis with realistic data
            total_lines = random.randint(1000, 50000)
            error_count = random.randint(0, 50)
            warning_count = random.randint(5, 200)
            critical_count = random.randint(0, 10)

            # Generate some realistic log patterns
            log_patterns = []
            if error_count > 0:
                log_patterns.append(
                    f"Authentication failures: {random.randint(0, error_count // 2)}"
                )
            if warning_count > 0:
                log_patterns.append(
                    f"Service restarts: {random.randint(0, warning_count // 3)}"
                )
            if critical_count > 0:
                log_patterns.append(f"System errors: {critical_count}")

            analysis = f"""Log Analysis Report:
• Total Log Lines: {total_lines:,}
• Error Count: {error_count}
• Warning Count: {warning_count}
• Critical Count: {critical_count}
• Analysis Time: {time.strftime("%H:%M:%S")}

Patterns Found:"""

            if log_patterns:
                for pattern in log_patterns:
                    analysis += f"\n• {pattern}"
            else:
                analysis += "\n• No significant patterns detected"

            return analysis

        except Exception as e:
            return f"Error analyzing logs: {str(e)}"

    @tool_registry.register_tool("directory_info")
    def get_directory_info(directory: str = "/tmp") -> str:
        """Get detailed information about a directory."""
        import os
        import time

        try:
            if not os.path.exists(directory):
                return f"Directory {directory} does not exist"

            stats = os.stat(directory)
            files = os.listdir(directory)
            file_count = len(files)

            # Get some basic file info
            file_types = {}
            total_size = 0
            for file in files[:20]:  # Check first 20 files
                file_path = os.path.join(directory, file)
                try:
                    if os.path.isfile(file_path):
                        file_types["files"] = file_types.get("files", 0) + 1
                        total_size += os.path.getsize(file_path)
                    elif os.path.isdir(file_path):
                        file_types["directories"] = file_types.get("directories", 0) + 1
                except:  # noqa: E722
                    pass

            return f"""Directory Analysis: {directory}
• Total Items: {file_count}
• Files: {file_types.get("files", 0)}
• Directories: {file_types.get("directories", 0)}
• Total Size: {total_size:,} bytes
• Last Modified: {time.ctime(stats.st_mtime)}"""
        except Exception as e:
            return f"Error getting directory info: {str(e)}"

    @tool_registry.register_tool("simple_calculator")
    def calculate(operation: str, a: float, b: float = 0) -> str:
        """Perform simple mathematical calculations.

        Args:
            operation: "add", "subtract", "multiply", "divide"
            a: First number
            b: Second number (default 0)
        """
        try:
            if operation.lower() == "add":
                result = a + b
                operation_name = "addition"
            elif operation.lower() == "subtract":
                result = a - b
                operation_name = "subtraction"
            elif operation.lower() == "multiply":
                result = a * b
                operation_name = "multiplication"
            elif operation.lower() == "divide":
                if b == 0:
                    return "Error: Division by zero"
                result = a / b
                operation_name = "division"
            else:
                return f"Unknown operation: '{operation}'. Supported: 'add', 'subtract', 'multiply', 'divide'"

            return f"Result of {operation_name}({a}, {b}): {result}"
        except Exception as e:
            return f"Calculation error: {str(e)}"

    async def initialize(self):
        """Initialize all components."""
        print(f"connectedd: {self.connected}")
        print("🚀 Initializing OmniAgent CLI...")
        if self.connected:
            print("already initiazlied")
            return

        # Initialize routers
        self.memory_router = MemoryRouter("database")
        self.event_router = EventRouter("in_memory")

        # Initialize agent with exact same config as working example
        self.agent = OmniAgent(
            name="comprehensive_demo_agent",
            # system_instruction="You are a comprehensive AI assistant with access to mathematical, text processing, system information, data analysis, and file system tools. You can perform complex calculations, format text, analyze data, and provide system information. Always use the appropriate tools for the task and provide clear, helpful responses.",
            system_instruction="""
You are TutorAgent, an AI assistant specialized in personalized education. 
You have access to four tools that manage user-specific knowledge and learning progress:

- insert_knowledge: Store new educational content for a user’s knowledge base.
- knowledge_base_retrieval: Search and retrieve stored knowledge for a given user.
- update_user_progress: Record or update a user’s performance on topics and activities.
- get_user_context: Retrieve a user’s complete progress history to guide personalized tutoring.

Always use the most relevant tool when storing, retrieving, or adapting knowledge. 
Provide clear, supportive, and context-aware responses that help learners grow.
""",
            model_config={
                "provider": "openai",
                "model": "gpt-4.1",
                "temperature": 0.3,
                "max_context_length": 5000,
            },
            # mcp_tools=MCP_TOOLS,
            local_tools=tool_registry,
            agent_config={
                "agent_name": "OmniAgent",
                "max_steps": 15,
                "tool_call_timeout": 60,
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
            embedding_config={
                "provider": "voyage",
                "model": "voyage-3.5",
                "dimensions": 1024,
                "encoding_format": "base64",
            },
            memory_router=self.memory_router,
            event_router=self.event_router,
            debug=True,
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
            result = await self.agent.run(message, session_id=self.session_id)
            response = result.get("response", "No response received")
            return response
        except Exception as e:
            print(f"❌ Error: {e}")


document_agent_runner = OmniAgentRunner()
omni_recipeagent_runner = OmniAgentRunner()
omni_invagent_runner = OmniAgentRunner()


async def document_agent(message):
    print("document agent get task")
    await document_agent_runner.initialize()
    result = await document_agent_runner.handle_chat(message=message.get("content"))
    return {"status": "success", "data": result}


async def recipe_agent(message):
    print("recipe agent get task")
    await omni_recipeagent_runner.initialize()
    result = await omni_recipeagent_runner.handle_chat(message=message.get("content"))
    print(f"RESULT FROM RECIPE AGENT: {result}")
    return {"status": "success", "data": result}


async def inventory_agent(message):
    print(f"messaged rceievd: {message}")
    await omni_invagent_runner.initialize()
    result = await omni_invagent_runner.handle_chat(message=message.get("content"))
    print(f"RESULT FROM INVENTORY AGENT: {result}")
    return {"status": "success", "data": result}


async def main():
    # Register agents for multiple topics
    await sdk.register_agent(
        name="document_conversation_agent",
        topic="document.conversion.tasks",
        callback=document_agent,
        agent_config={
            "description": "this is meant for document",
        },
    )
    await sdk.register_agent(
        name="food_agent",
        topic="recipe.tasks",
        callback=recipe_agent,
        agent_config={
            "description": "this is meant for food recipe",
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


# # Register agents for multiple topics
# @sdk.agent(topic="document.conversion.tasks", name="omniagent")
# async def document_agent(message):
#     print("document agent get task")
#     await document_agent_runner.initialize()
#     result = await document_agent_runner.handle_chat(message=message.get("content"))
#     return {"status": "success", "data": result}


# # run the agent runner
# sdk.run()
