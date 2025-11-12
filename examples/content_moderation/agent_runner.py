import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from decouple import config
from omnicoreagent import EventRouter, MemoryRouter, OmniAgent

from omnidaemon import AgentConfig, OmniDaemonSDK, SubscriptionConfig, start_api_server
from metrics import record_decision, record_event, start_metrics_server
from schema import ModerationDecision, ModerationEvent
from tools import tool_registry
from state import INGEST_ROOT

logger = logging.getLogger(__name__)
sdk = OmniDaemonSDK()

MODERATION_TOPIC = "content_moderation.tasks"
REVIEW_TOPIC = "content_moderation.review"

DEFAULT_DIRECTORIES = [Path.home() / "omnicore_project"]


def _resolve_directories() -> list[str]:
    env_value = config("CONTENT_MODERATION_DIRS", default="")
    if env_value:
        candidates = [
            Path(item.strip()).expanduser()
            for item in env_value.split(",")
            if item.strip()
        ]
        return [str(path.resolve()) for path in candidates if path.exists()]
    return [str(path.resolve()) for path in DEFAULT_DIRECTORIES if path.exists()]


MCP_DIRECTORIES = _resolve_directories()

if not MCP_DIRECTORIES:
    fallback_dir = Path.home()
    MCP_DIRECTORIES = [str((fallback_dir / "Desktop").expanduser().resolve())]
    logger.warning(
        "No monitoring directories found; defaulting to Desktop when available."
    )

# Always include the ingest workspace so agents can access normalized files
if str(INGEST_ROOT.resolve()) not in MCP_DIRECTORIES:
    MCP_DIRECTORIES.append(str(INGEST_ROOT.resolve()))


CONTENT_MODERATION_AGENT = {
    "agent_id": "content_moderation_agent",
    "system_instruction": """You are the primary Content Moderation Agent for Abiola Adeshina Enterprises. Every event you receive contains either an `ingested_path` (a file that has already been copied into the moderation ingest workspace) or a request to perform a directory-wide cycle/report. Your job is to moderate each piece of content by calling the available tools and returning a structured decision.

Core workflow for single-file events:
- The payload will include `ingested_path` pointing to the normalized copy of the file you must moderate. This path is always within the directories already exposed to your filesystem MCP tool.
- Immediately call `analyze_content_file(ingested_path)` to review the content. Use the result plus any additional tools (flag_content, approve_content, remove_violating_content, get_moderation_stats, etc.) to make a final decision.
- If the content violates policy, call the appropriate tooling (flag_content or remove_violating_content) with a clear reason and severity. If it is acceptable, call approve_content with a short note.
- Summarize the moderation outcome as JSON with fields: `status` (approved|flagged|removed|error), `severity` (low|medium|high|critical or null), `actions` (list of actions taken or recommended), `notes` (short explanation), and `file_path` (original_path if provided, otherwise ingested_path).
- Always include references to any flagged reasons (spam, profanity, etc.). If the file cannot be read, return an error decision explaining why.

For cycle/report events:
- When directories are provided, scan them by calling `scan_directory_for_new_content`. For any new or modified files, repeat the single-file workflow above (call analyze_content_file, then the appropriate flag/approve/remove tools, and build structured JSON decisions) before generating summary statistics or reports.
- After processing all files, call `get_moderation_stats` and `create_moderation_report` to provide a consolidated view.

Policy highlights:
- Spam keywords (buy now, click here, free money, etc.)
- Inappropriate language (profanity, harassment)
- Suspicious patterns (excessive URLs/emails, ALL CAPS, high repetition)
- Quality concerns (low effort, duplicates)

Severity levels:
- CRITICAL: Immediate removal recommended.
- HIGH: Flag for priority human review.
- MEDIUM: Flag for normal review.
- LOW: Approve with notes / monitor.

Always document reasoning, reference the relevant policy sections, and prefer flagging to approval when uncertain. Never return "no content" if an `ingested_path` is provided—open the file and moderate it using your tools.""",
    "model_config": {
        "provider": config("OMNICORE_MODEL_PROVIDER", default="openai"),
        "model": config("OMNICORE_MODEL", default="gpt-4.1"),
        "temperature": 0.2,
        "max_context_length": 10_000,
    },
    "agent_config": {
        "max_steps": 20,
        "tool_call_timeout": 60,
        "request_limit": 0,
        "memory_config": {"mode": "sliding_window", "value": 100},
    },
}


def build_agent_prompt(event: ModerationEvent) -> str:
    base_instructions = [
        "# Moderation Event",
        f"task: {event.task}",
        f"requested_by: {event.requested_by}",
    ]

    if event.metadata:
        base_instructions.append(f"metadata: {event.metadata.dict(exclude_none=True)}")

    if event.task == "single_file" and event.ingested_path:
        base_instructions.extend(
            [
                "\nYou must moderate the following ingested file immediately:",
                f"- ingested_path: {event.ingested_path}",
                f"- original_path: {event.original_path or 'unknown'}",
                "\nSteps:",
                "1. Call analyze_content_file(ingested_path).",
                "2. Evaluate the findings against policy guidelines (spam, hate, PII, suspicious links, quality).",
                "3. If violations exist, call flag_content or remove_violating_content with precise reasons and severity.",
                "4. If the content is acceptable, call approve_content with a brief note.",
                "5. Return a JSON object with: status, severity, actions, notes (list), file_path (original preferred).",
            ]
        )
    elif event.task in {"cycle", "report"}:
        directories = ", ".join(event.directories or []) or "(default)"
        base_instructions.extend(
            [
                "\nYou must run a moderation cycle over directories:",
                directories,
                "For each new or modified file, perform the single-file workflow described above, then produce a summary",
                "using get_moderation_stats and create_moderation_report.",
            ]
        )
        if event.task == "report":
            base_instructions.append(
                "This is a report-only run; do not ingest new files, only generate statistics."
            )

    base_instructions.append(
        "\nAlways respond with valid JSON (not Python) describing the final moderation decision."
    )

    return "\n".join(base_instructions)


class ContentModerationAgentRunner:
    def __init__(self) -> None:
        self.agent: Optional[OmniAgent] = None
        self.memory_router: Optional[MemoryRouter] = None
        self.event_router: Optional[EventRouter] = None
        self.connected = False

    async def initialize(self) -> None:
        if self.connected:
            return

        self.memory_router = MemoryRouter("in_memory")
        self.event_router = EventRouter("in_memory")

        self.agent = OmniAgent(
            name=CONTENT_MODERATION_AGENT["agent_id"],
            system_instruction=CONTENT_MODERATION_AGENT["system_instruction"],
            model_config=CONTENT_MODERATION_AGENT["model_config"],
            mcp_tools=[
                {
                    "name": "filesystem",
                    "command": "npx",
                    "args": [
                        "-y",
                        "@modelcontextprotocol/server-filesystem",
                        *MCP_DIRECTORIES,
                    ],
                }
            ],
            local_tools=tool_registry,
            agent_config=CONTENT_MODERATION_AGENT["agent_config"],
            memory_router=self.memory_router,
            event_router=self.event_router,
            debug=config("OMNICORE_DEBUG", default=True, cast=bool),
        )

        await self.agent.connect_mcp_servers()
        self.connected = True
        logger.info(
            "Content moderation agent initialized. Monitoring directories: %s",
            ", ".join(MCP_DIRECTORIES),
        )

    async def handle_event(self, message: Dict) -> Dict:
        await self.initialize()

        event_raw = message.get("content")
        if event_raw is None:
            logger.error("Moderation payload missing 'content' field")
            decision = ModerationDecision(
                status="error",
                notes=["Missing content payload"],
                file_path=None,
                source_event_id=message.get("id"),
            )
            record_decision(decision)
            return decision.model_dump()

        try:
            moderation_event = ModerationEvent.from_raw(event_raw)
        except (ValueError, TypeError) as exc:
            logger.exception("Invalid moderation event payload")
            decision = ModerationDecision(
                status="error",
                notes=[str(exc)],
                source_event_id=message.get("id"),
            )
            record_decision(decision)
            return decision.model_dump()

        record_event(moderation_event)

        updated_content_prompt = build_agent_prompt(moderation_event)
        logger.info(
            "Executing moderation cycle for event %s task=%s",
            message.get("id"),
            moderation_event.task,
        )

        try:
            result = await self.agent.run(updated_content_prompt)
            if isinstance(result, dict):
                raw = result.get("response") or result
            else:
                raw = result
            decision = ModerationDecision.from_agent_response(
                raw,
                source_event_id=message.get("id"),
            )
            record_decision(decision)
            return decision.model_dump()
        except Exception as exc:
            logger.exception("Content moderation agent failed")
            decision = ModerationDecision(
                status="error",
                severity=None,
                actions=["error"],
                notes=[str(exc)],
                file_path=moderation_event.original_path
                or moderation_event.ingested_path,
                source_event_id=message.get("id"),
            )
            record_decision(decision)
            return decision.model_dump()

    async def shutdown(self) -> None:
        if self.agent:
            try:
                await self.agent.cleanup()
            except Exception as exc:
                logger.warning("Failed to clean up moderation agent: %s", exc)
        self.connected = False


class ReviewAgentRunner:
    def __init__(self) -> None:
        self.agent: Optional[OmniAgent] = None
        self.memory_router: Optional[MemoryRouter] = None
        self.event_router: Optional[EventRouter] = None
        self.connected = False

    async def initialize(self) -> None:
        if self.connected:
            return

        self.memory_router = MemoryRouter("in_memory")
        self.event_router = EventRouter("in_memory")

        system_instruction = (
            "You are the Moderation Review Archiver. Whenever a moderation result arrives on this topic, you must"
            " parse the payload, validate it, and persist it by calling the `record_moderation_result` tool."
            " The payload will usually be the JSON returned by the primary moderation agent."
            " Follow this workflow:\n"
            " 1. If the payload includes the OmniDaemon envelope (task_id, topic, etc.), extract the moderation"
            "    result from the `content` field. Treat string content as JSON and parse it.\n"
            " 2. Ensure the stored entry captures: source_event_id, file_path (prefer original_path), status,"
            "    severity, and the full raw response.\n"
            " 3. Call `record_moderation_result(<json_string>)` with the cleaned moderation JSON. This writes to"
            "    SQLite for analytics/auditing.\n"
            " 4. If parsing fails or the moderation response is malformed, return an error JSON explaining what went"
            "    wrong—do not silently succeed.\n"
            " 5. Optionally produce a short summary (`summary` field) describing what was archived (file name, decision)."
            " The absolute priority is to keep the database in sync with every moderation decision."
        )

        self.agent = OmniAgent(
            name="content_moderation_review_agent",
            system_instruction=system_instruction,
            model_config={
                "provider": config("OMNICORE_MODEL_PROVIDER", default="openai"),
                "model": config("OMNICORE_MODEL", default="gpt-4.1"),
                "temperature": 0,
                "max_context_length": 4000,
            },
            local_tools=tool_registry,
            agent_config={
                "max_steps": 8,
                "tool_call_timeout": 20,
                "request_limit": 0,
                "memory_config": {"mode": "sliding_window", "value": 25},
            },
            memory_router=self.memory_router,
            event_router=self.event_router,
            debug=config("OMNICORE_DEBUG", default=True, cast=bool),
        )

        await self.agent.connect_mcp_servers()
        self.connected = True
        logger.info("Review agent initialized; awaiting moderation results")

    async def handle_event(self, message: Dict) -> Dict:
        await self.initialize()

        content = message.get("content")
        logger.info("Archiving moderation response from event %s", message.get("id"))

        try:
            if content is None:
                raise ValueError("empty moderation response")

            decision = ModerationDecision.from_agent_response(
                content,
                source_event_id=message.get("id"),
            )
            record_decision(decision)

            payload_for_agent = content
            if isinstance(payload_for_agent, dict):
                payload_for_agent = json.dumps(payload_for_agent)

            result = await self.agent.run(payload_for_agent)
            summary = result.get("response") if isinstance(result, dict) else result

            return {
                "status": "archived",
                "source_event": message.get("id"),
                "file_path": decision.file_path,
                "summary": summary,
            }
        except Exception as exc:
            logger.exception("Review agent failed to archive moderation result")
            decision = ModerationDecision(
                status="error",
                severity=None,
                actions=["error"],
                notes=[str(exc)],
                source_event_id=message.get("id"),
            )
            record_decision(decision)
            return decision.model_dump()

    async def shutdown(self) -> None:
        if self.agent:
            try:
                await self.agent.cleanup()
            except Exception as exc:
                logger.warning("Failed to clean up review agent: %s", exc)
        self.connected = False


moderation_runner = ContentModerationAgentRunner()
review_runner = ReviewAgentRunner()


async def handle_moderation_event(message: Dict) -> Dict:
    return await moderation_runner.handle_event(message)


async def handle_review_event(message: Dict) -> Dict:
    return await review_runner.handle_event(message)


async def main() -> None:
    try:
        await sdk.register_agent(
            AgentConfig(
                name="CONTENT_MODERATION_AGENT",
                topic=MODERATION_TOPIC,
                callback=handle_moderation_event,
                description="OmniCore-driven content moderation pipeline",
                config=SubscriptionConfig(
                    reclaim_idle_ms=60000, dlq_retry_limit=5, consumer_count=3
                ),
            )
        )

        await sdk.register_agent(
            AgentConfig(
                name="CONTENT_MODERATION_REVIEW_AGENT",
                topic=REVIEW_TOPIC,
                callback=handle_review_event,
                description="Stores moderation outcomes in SQLite for analytics",
                config=SubscriptionConfig(
                    reclaim_idle_ms=60000, dlq_retry_limit=3, consumer_count=3
                ),
            )
        )

        enable_api = config("OMNIDAEMON_API_ENABLED", default=False, cast=bool)
        api_port = config("OMNIDAEMON_API_PORT", default=8765, cast=int)
        if enable_api:
            asyncio.create_task(start_api_server(sdk, port=api_port))
            logger.info("OmniDaemon API available at http://127.0.0.1:%s", api_port)

        logger.info(
            "Content moderation agents registered. Listening on %s", MODERATION_TOPIC
        )
        logger.info(
            "Content moderation agents registered. Listening on %s", REVIEW_TOPIC
        )
        metrics_port = config("CONTENT_MODERATION_METRICS_PORT", default=9102, cast=int)
        start_metrics_server(metrics_port)
        await sdk.start()

        try:
            while True:
                await asyncio.sleep(1)
        except (asyncio.CancelledError, KeyboardInterrupt):
            logger.info("Shutdown signal received")
    finally:
        await sdk.shutdown()
        await moderation_runner.shutdown()
        await review_runner.shutdown()
        logger.info("Content moderation example stopped")


if __name__ == "__main__":
    asyncio.run(main())
