import asyncio
import httpx
import json
import typer
from decouple import config
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TaskProgressColumn,
)
from rich.tree import Tree
from rich.layout import Layout
from rich.live import Live
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.columns import Columns
from rich.align import Align
from rich.text import Text
from omnidaemon.schemas import EventEnvelope, PayloadBase
from pathlib import Path
from omnidaemon.sdk import OmniDaemonSDK
import sys
from datetime import datetime


console = Console(record=True, force_terminal=True)


app = typer.Typer(
    name="omnidaemon",
    help="[bold cyan]⚡ OmniDaemon CLI[/] - Universal Event-Driven Runtime Engine for AI Agents",
    add_completion=False,
    rich_markup_mode="rich",
    pretty_exceptions_enable=True,
)

agent_app = typer.Typer(
    name="agent",
    help="[bold green]🤖 Agent Management[/] - Register, monitor, and control AI agents",
    rich_markup_mode="rich",
)
task_app = typer.Typer(
    name="task",
    help="[bold yellow]📋 Task Operations[/] - Publish tasks and retrieve results",
    rich_markup_mode="rich",
)
bus_app = typer.Typer(
    name="bus",
    help="[bold magenta]📡 Event Bus Monitor[/] - Monitor Redis Streams and message flow",
    rich_markup_mode="rich",
)

app.add_typer(agent_app, name="agent")
app.add_typer(task_app, name="task")
app.add_typer(bus_app, name="bus")

EVENT_BUS_TYPE = config("EVENT_BUS_TYPE")


OMNIDAEMON_BANNER = """
[bold cyan]╔═══════════════════════════════════════════════════════════════════════════════════════╗[/]
[bold cyan]║                                                                                       ║[/]
[bold cyan]║[/]    [bold bright_cyan]  ██████╗ ███╗   ███╗███╗   ██╗██╗██████╗  █████╗ ███████╗███╗   ███╗ ██████╗ ███╗   ██╗[/]    [bold cyan]║[/]
[bold cyan]║[/]    [bold bright_cyan] ██╔═══██╗████╗ ████║████╗  ██║██║██╔══██╗██╔══██╗██╔════╝████╗ ████║██╔═══██╗████╗  ██║[/]    [bold cyan]║[/]
[bold cyan]║[/]    [bold white] ██║   ██║██╔████╔██║██╔██╗ ██║██║██║  ██║███████║█████╗  ██╔████╔██║██║   ██║██╔██╗ ██║[/]    [bold cyan]║[/]
[bold cyan]║[/]    [bold white] ██║   ██║██║╚██╔╝██║██║╚██╗██║██║██║  ██║██╔══██║██╔══╝  ██║╚██╔╝██║██║   ██║██║╚██╗██║[/]    [bold cyan]║[/]
[bold cyan]║[/]    [bold bright_cyan] ╚██████╔╝██║ ╚═╝ ██║██║ ╚████║██║██████╔╝██║  ██║███████╗██║ ╚═╝ ██║╚██████╔╝██║ ╚████║[/]    [bold cyan]║[/]
[bold cyan]║[/]    [bold bright_cyan]  ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝╚═════╝ ╚═╝  ╚═╝╚══════╝╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═══╝[/]    [bold cyan]║[/]
[bold cyan]║                                                                                       ║[/]
[bold cyan]║[/]          [bold magenta on black] ⚡ Universal Event-Driven Runtime Engine for AI Agents ⚡ [/]          [bold cyan]║[/]
[bold cyan]║[/]             [dim cyan]React • Process • Scale • Monitor Events in Real-Time[/]             [bold cyan]║[/]
[bold cyan]║                                                                                       ║[/]
[bold cyan]╚═══════════════════════════════════════════════════════════════════════════════════════╝[/]
"""


def create_status_badge(status: str, running: bool = True) -> Text:
    """Create a beautiful status badge."""
    if running:
        return Text("● RUNNING", style="bold green")
    return Text("● STOPPED", style="bold red")


def create_header_panel(title: str, subtitle: str = "") -> Panel:
    """Create a beautiful header panel."""
    content = f"[bold white]{title}[/]"
    if subtitle:
        content += f"\n[dim]{subtitle}[/]"
    return Panel(
        Align.center(content),
        style="bold cyan",
        border_style="bright_cyan",
        box=box.DOUBLE_EDGE,
    )


def success_message(message: str):
    """Display a success message with icon."""
    console.print(f"[bold green]✓[/] {message}")


def error_message(message: str):
    """Display an error message with icon."""
    console.print(f"[bold red]✗[/] {message}")


def warning_message(message: str):
    """Display a warning message with icon."""
    console.print(f"[bold yellow]⚠[/] {message}")


def info_message(message: str):
    """Display an info message with icon."""
    console.print(f"[bold cyan]ℹ[/] {message}")


def format_timestamp(timestamp: float) -> str:
    """Format Unix timestamp to readable string."""
    if not timestamp:
        return "N/A"
    dt = datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def create_metric_card(title: str, value: str, icon: str = "📊") -> Panel:
    """Create a beautiful metric card."""
    content = Align.center(f"{icon}\n[bold bright_white]{value}[/]\n[dim]{title}[/]")
    return Panel(
        content,
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    )


try:
    sdk = OmniDaemonSDK()
except Exception as e:
    error_message(f"Failed to initialize OmniDaemonSDK: {e}")
    raise SystemExit(1)


def _ensure_redis_stream():
    if EVENT_BUS_TYPE != "redis_stream":
        typer.echo(
            "'omnidaemon bus' commands only work with EVENT_BUS_TYPE=redis_stream",
            err=True,
        )
        raise typer.Exit(code=1)


@bus_app.command("list")
def bus_list_cmd():
    """List all Redis streams with beautiful formatting."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Loading streams...", total=None)
        try:
            streams = asyncio.run(sdk.list_streams())
            progress.update(task, completed=True)
        except ValueError as e:
            error_message(str(e))
            raise typer.Exit(1)
        except Exception as e:
            error_message(f"Failed to list streams: {e}")
            raise typer.Exit(1)

    console.print()

    if not streams:
        warning_message("No streams found")
        return

    header = Panel(
        Align.center(f"[bold cyan]{len(streams)}[/] Redis Streams"),
        title="[bold white]📊 Streams Overview[/]",
        border_style="cyan",
        box=box.DOUBLE,
    )
    console.print(header)
    console.print()

    table = Table(
        box=box.DOUBLE_EDGE,
        border_style="bright_cyan",
        header_style="bold cyan",
    )
    table.add_column("Stream", style="magenta bold")
    table.add_column("Messages", justify="right", style="cyan")

    for stream in streams:
        stream_name = stream["stream"].replace("omni-stream:", "")
        table.add_row(stream_name, str(stream["length"]))

    console.print(table)
    console.print()
    success_message("Streams loaded successfully")
    console.print()


@bus_app.command("dlq")
def bus_dlq_cmd(
    topic: str = typer.Option(..., "--topic", "-t", help="Topic name"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of entries to show"),
):
    """Inspect dead-letter queue for a topic."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"[cyan]Loading DLQ for {topic}...", total=None)
        try:
            entries = asyncio.run(sdk.inspect_dlq(topic, limit=limit))
            progress.update(task, completed=True)
        except ValueError as e:
            error_message(str(e))
            raise typer.Exit(1)
        except Exception as e:
            error_message(f"Failed to inspect DLQ: {e}")
            raise typer.Exit(1)

    console.print()

    if not entries:
        info_message(f"No entries in DLQ for topic: [bold]{topic}[/]")
        return

    header = Panel(
        Align.center(
            f"[bold red]Dead Letter Queue[/]\n[dim]Topic:[/] [magenta]{topic}[/]"
        ),
        title="[bold white]💀 DLQ Entries[/]",
        border_style="red",
        box=box.DOUBLE,
    )
    console.print(header)
    console.print()

    for entry in entries:
        entry_panel = Panel(
            Syntax(
                json.dumps(entry["data"], indent=2, default=str),
                "json",
                theme="monokai",
            ),
            title=f"[bold red]Message ID:[/] {entry['id']}",
            border_style="red",
            box=box.ROUNDED,
        )
        console.print(entry_panel)
        console.print()

    console.print(f"[dim]Showing {len(entries)} of {len(entries)} DLQ entries[/]")
    console.print()


@bus_app.command("inspect")
def bus_inspect_cmd(
    stream: str = typer.Option(..., "--stream", "-s", help="Stream name"),
    limit: int = typer.Option(10, "--limit", "-n", help="Number of messages to show"),
):
    """View recent messages in a stream."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"[cyan]Loading messages from {stream}...", total=None)
        try:
            messages = asyncio.run(sdk.inspect_stream(stream, limit=limit))
            progress.update(task, completed=True)
        except ValueError as e:
            error_message(str(e))
            raise typer.Exit(1)
        except Exception as e:
            error_message(f"Failed to inspect stream: {e}")
            raise typer.Exit(1)

    console.print()

    if not messages:
        warning_message(f"No messages in stream: [bold]{stream}[/]")
        return

    header = Panel(
        Align.center(
            f"[bold cyan]Stream:[/] [magenta]{stream}[/]\n[dim]{len(messages)} messages[/]"
        ),
        title="[bold white]📬 Stream Messages[/]",
        border_style="cyan",
        box=box.DOUBLE,
    )
    console.print(header)
    console.print()

    for msg in messages:
        msg_panel = Panel(
            Syntax(
                json.dumps(msg["data"], indent=2, default=str), "json", theme="monokai"
            ),
            title=f"[bold cyan]ID:[/] {msg['id']}",
            border_style="cyan",
            box=box.ROUNDED,
        )
        console.print(msg_panel)
        console.print()

    console.print(f"[dim]Showing {len(messages)} most recent messages[/]")
    console.print()


@bus_app.command("groups")
def bus_groups_cmd(
    stream: str = typer.Option(..., "--stream", "-s", help="Stream name"),
):
    """Show consumer groups for a stream."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"[cyan]Loading groups for {stream}...", total=None)
        try:
            groups = asyncio.run(sdk.list_groups(stream))
            progress.update(task, completed=True)
        except ValueError as e:
            error_message(str(e))
            raise typer.Exit(1)
        except Exception as e:
            error_message(f"Failed to list groups: {e}")
            raise typer.Exit(1)

    console.print()

    if not groups:
        warning_message(f"No consumer groups for stream: [bold]{stream}[/]")
        return

    header = Panel(
        Align.center(
            f"[bold cyan]{len(groups)}[/] Consumer Groups\n[dim]Stream:[/] [magenta]{stream}[/]"
        ),
        title="[bold white]👥 Consumer Groups[/]",
        border_style="cyan",
        box=box.DOUBLE,
    )
    console.print(header)
    console.print()

    table = Table(
        box=box.DOUBLE_EDGE,
        border_style="bright_cyan",
        header_style="bold cyan",
    )
    table.add_column("Group Name", style="green bold")
    table.add_column("Consumers", justify="right", style="cyan")
    table.add_column("Pending", justify="right", style="yellow")
    table.add_column("Last Delivered ID", style="dim")

    for group in groups:
        pending_color = (
            "red"
            if group["pending"] > 50
            else "yellow"
            if group["pending"] > 0
            else "green"
        )
        table.add_row(
            group["name"],
            str(group["consumers"]),
            f"[{pending_color}]{group['pending']}[/]",
            group["last_delivered_id"][:20] + "..."
            if len(group["last_delivered_id"]) > 20
            else group["last_delivered_id"],
        )

    console.print(table)
    console.print()
    success_message(
        f"Found {len(groups)} consumer group{'s' if len(groups) > 1 else ''}"
    )
    console.print()


@bus_app.command("stats")
def bus_stats_cmd(
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Show comprehensive stats across all topics."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Collecting bus statistics...", total=None)
        try:
            stats = asyncio.run(sdk.get_bus_stats())
            progress.update(task, completed=True)
        except ValueError as e:
            error_message(str(e))
            raise typer.Exit(1)
        except Exception as e:
            error_message(f"Failed to get stats: {e}")
            raise typer.Exit(1)

    console.print()

    if output_json:
        console.print(json.dumps(stats, indent=2, default=str))
        return

    snapshot = stats["snapshot"]
    redis_info = stats["redis_info"]

    total_topics = len(snapshot["topics"])
    total_messages = sum(t["length"] for t in snapshot["topics"].values())
    total_dlq = sum(t["dlq_total"] for t in snapshot["topics"].values())

    header = Panel(
        Align.center(
            f"[bold cyan]{total_topics}[/] Topics  •  [bold cyan]{total_messages}[/] Messages  •  [bold red]{total_dlq}[/] DLQ\n"
            f"[dim]Redis Memory:[/] {redis_info['used_memory_human']}"
        ),
        title="[bold white]📊 Bus Statistics[/]",
        border_style="cyan",
        box=box.DOUBLE,
    )
    console.print(header)
    console.print()

    table = Table(
        box=box.DOUBLE_EDGE,
        border_style="bright_cyan",
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("Topic", style="magenta bold")
    table.add_column("Stream Length", justify="right", style="cyan")
    table.add_column("Group", style="green")
    table.add_column("Consumers", justify="right", style="cyan")
    table.add_column("Pending", justify="right", style="yellow")
    table.add_column("DLQ", justify="right", style="red")

    for topic, data in snapshot["topics"].items():
        for idx, group in enumerate(data["groups"]):
            pending_color = (
                "red"
                if group["pending"] > 50
                else "yellow"
                if group["pending"] > 0
                else "green"
            )
            dlq_color = "red" if group["dlq"] > 0 else "dim"

            table.add_row(
                topic if idx == 0 else "",
                str(data["length"]) if idx == 0 else "",
                group["name"],
                str(group["consumers"]),
                f"[{pending_color}]{group['pending']}[/]",
                f"[{dlq_color}]{group['dlq']}[/]",
            )

    console.print(table)
    console.print()
    success_message("Statistics collected successfully")
    console.print()
    console.print("[dim]💡 Tip: Use[/] --json [dim]flag for machine-readable output[/]")
    console.print()


def load_event(
    payload_file: str = None,
    topic: str = None,
    content: str = None,
    reply_to: str = None,
    webhook: str = None,
    **kwargs,
):
    """
    Create an EventEnvelope either from file (full EventEnvelope) or minimal fields.
    kwargs can include tenant_id, correlation_id, causation_id, source, meta.
    """
    if payload_file:
        try:
            raw = Path(payload_file).read_text()
            data = json.loads(raw)
        except FileNotFoundError:
            console.print(f"[red]File not found: {payload_file}[/]", err=True)
            raise typer.Exit(1)
        except json.JSONDecodeError:
            console.print(f"[red]Invalid JSON in {payload_file}[/]", err=True)
            raise typer.Exit(1)
    else:
        if not topic or not content:
            console.print(
                "[red]You must provide either a payload file or topic + content[/]",
                err=True,
            )
            raise typer.Exit(1)

        payload_obj = PayloadBase(content=content, reply_to=reply_to, webhook=webhook)
        data = {"topic": topic, "payload": payload_obj.model_dump()}
        data.update(kwargs)

    try:
        envelope = EventEnvelope(**data)
    except Exception as e:
        console.print(f"[red]Invalid EventEnvelope: {e}[/]", err=True)
        raise typer.Exit(1)

    return envelope.model_dump()


@task_app.command("publish")
def publish_task(
    payload_file: str = typer.Option(
        None, help="Path to JSON file with full EventEnvelope"
    ),
    topic: str = typer.Option(None, help="Event topic"),
    content: str = typer.Option(None, help="Content for payload.content"),
    reply_to: str = typer.Option(None, help="Optional reply_to topic"),
    webhook: str = typer.Option(None, help="Optional webhook URL"),
    tenant_id: str = typer.Option(None, help="Optional tenant_id"),
    correlation_id: str = typer.Option(None, help="Optional correlation_id"),
    causation_id: str = typer.Option(None, help="Optional causation_id"),
    source: str = typer.Option(None, help="Optional source name"),
):
    """Publish a new task with enterprise-grade confirmation."""
    console.print()

    try:
        envelope_dict = load_event(
            payload_file=payload_file,
            topic=topic,
            content=content,
            reply_to=reply_to,
            webhook=webhook,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            source=source,
        )
    except typer.Exit:
        raise
    except Exception as e:
        error_message(f"Failed to load event: {e}")
        raise typer.Exit(1)

    info_message(
        f"Publishing task to topic: [bold magenta]{envelope_dict.get('topic')}[/]"
    )
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Publishing task...", total=None)
        try:
            event_obj = EventEnvelope(**envelope_dict)
            task_id = asyncio.run(sdk.publish_task(event_envelope=event_obj))
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to publish task: {e}")
            raise typer.Exit(1)

    console.print()

    result_panel = Panel(
        f"[bold cyan]{task_id}[/]",
        title="[bold green]✓ Task Published Successfully[/]",
        subtitle="[dim]Task ID[/]",
        border_style="green",
        box=box.DOUBLE,
    )
    console.print(result_panel)
    console.print()

    console.print("[dim]Next steps:[/]")
    console.print(
        f"  [cyan]• Check status:[/] omnidaemon task result --task-id {task_id}"
    )
    console.print(f"  [cyan]• View all tasks:[/] omnidaemon task list")
    console.print()


@agent_app.command("list")
def agent_list(
    format: str = typer.Option(
        "tree", "--format", "-f", help="Output format: tree, table, or compact"
    ),
):
    """List all registered agents grouped by topic."""
    console.print()
    console.print(OMNIDAEMON_BANNER)
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Loading agents...", total=None)
        try:
            data = asyncio.run(sdk.list_agents())
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to list agents: {e}")
            raise typer.Exit(1)

    console.print()

    if not data:
        warning_message("No agents registered yet")
        console.print()
        info_message("Get started by registering your first agent!")
        console.print("  [dim]Example:[/] omnidaemon agent register --help")
        raise typer.Exit(0)

    total_agents = sum(len(agents) for agents in data.values())
    total_topics = len(data)

    summary_panel = Panel(
        f"[bold cyan]{total_agents}[/] agents across [bold magenta]{total_topics}[/] topics",
        title="[bold white]📊 Agent Overview[/]",
        border_style="bright_cyan",
        box=box.DOUBLE,
    )
    console.print(summary_panel)
    console.print()

    if format == "tree":
        tree = Tree(
            "🌐 [bold cyan]OmniDaemon Agent Registry[/]",
            guide_style="bright_blue",
        )

        for topic, agents in sorted(data.items()):
            topic_branch = tree.add(
                f"[bold magenta]📡 {topic}[/] [dim]({len(agents)} agent{'s' if len(agents) > 1 else ''})[/]",
                guide_style="magenta",
            )

            for agent in agents:
                agent_name = agent.get("name", "unnamed")
                description = agent.get("description", "No description")
                tools = agent.get("tools", [])

                agent_info = f"[bold green]🤖 {agent_name}[/]\n"
                agent_info += f"[dim]{description}[/]"

                agent_branch = topic_branch.add(agent_info)

                if tools:
                    tools_text = ", ".join(f"[cyan]{t}[/]" for t in tools)
                    agent_branch.add(f"[dim]🔧 Tools:[/] {tools_text}")

                if agent.get("config"):
                    config_str = json.dumps(agent.get("config"), indent=2)
                    agent_branch.add(f"[dim]⚙️  Config:[/]\n[yellow]{config_str}[/]")

        console.print(tree)

    elif format == "compact":
        for topic, agents in sorted(data.items()):
            console.print(f"\n[bold magenta]📡 {topic}[/]")
            for agent in agents:
                name = agent.get("name", "unnamed")
                desc = agent.get("description", "No description")
                console.print(f"  [green]● {name}[/] [dim]- {desc}[/]")

    else:
        table = Table(
            title="[bold white]🤖 Registered Agents[/]",
            box=box.DOUBLE_EDGE,
            border_style="bright_cyan",
            header_style="bold cyan",
            show_lines=True,
        )
        table.add_column("Topic", style="magenta", no_wrap=True)
        table.add_column("Agent", style="green bold")
        table.add_column("Description", style="white")
        table.add_column("Tools", style="cyan")
        table.add_column("Status", justify="center")

        for topic, agents in sorted(data.items()):
            for idx, agent in enumerate(agents):
                tools = agent.get("tools", [])
                tools_str = ", ".join(tools) if tools else "—"

                table.add_row(
                    topic if idx == 0 else "",
                    agent.get("name", "—"),
                    agent.get("description", "—"),
                    tools_str,
                    "[green]● Active[/]",
                )

        console.print(table)

    console.print()
    success_message(
        f"Found {total_agents} agent{'s' if total_agents > 1 else ''} registered"
    )
    console.print()


@agent_app.command("get")
def agent_get(
    topic: str = typer.Option(..., "--topic", help="Agent topic"),
    name: str = typer.Option(..., "--name", help="Agent name"),
):
    """Get a specific agent's detailed information."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"[cyan]Fetching agent {name}...", total=None)
        try:
            agent = asyncio.run(sdk.get_agent(topic=topic, agent_name=name))
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to fetch agent: {e}")
            raise typer.Exit(1)

    console.print()

    if not agent:
        error_message(f"Agent not found: {topic}/{name}")
        raise typer.Exit(1)

    header = Panel(
        Align.center(f"[bold green]🤖 {name}[/]\n[dim]Topic:[/] [magenta]{topic}[/]"),
        border_style="green",
        box=box.DOUBLE,
    )
    console.print(header)
    console.print()

    if agent.get("description"):
        desc_panel = Panel(
            agent["description"],
            title="[bold white]📝 Description[/]",
            border_style="cyan",
            box=box.ROUNDED,
        )
        console.print(desc_panel)
        console.print()

    if agent.get("tools"):
        tools_content = "\n".join(f"  [cyan]• {tool}[/]" for tool in agent["tools"])
        tools_panel = Panel(
            tools_content,
            title="[bold white]🔧 Tools & Capabilities[/]",
            border_style="yellow",
            box=box.ROUNDED,
        )
        console.print(tools_panel)
        console.print()

    if agent.get("config"):
        config_json = json.dumps(agent["config"], indent=2)
        syntax = Syntax(config_json, "json", theme="monokai", line_numbers=True)
        config_panel = Panel(
            syntax,
            title="[bold white]⚙️  Configuration[/]",
            border_style="magenta",
            box=box.ROUNDED,
        )
        console.print(config_panel)
        console.print()

    metadata_table = Table(box=box.SIMPLE, show_header=False, border_style="dim")
    metadata_table.add_column("Key", style="cyan dim", no_wrap=True)
    metadata_table.add_column("Value", style="white")

    for key, value in agent.items():
        if key not in ["name", "description", "tools", "config", "topic"]:
            if type(value).__name__ in ("dict", "list"):
                value_str = json.dumps(value)
            else:
                value_str = str(value)
            metadata_table.add_row(key, value_str)

    if metadata_table.row_count > 0:
        metadata_panel = Panel(
            metadata_table,
            title="[bold white]ℹ️  Additional Information[/]",
            border_style="blue",
            box=box.ROUNDED,
        )
        console.print(metadata_panel)
        console.print()

    success_message("Agent details retrieved successfully")
    console.print()


@task_app.command("result")
def task_result(
    task_id: str = typer.Option(
        ..., "--task-id", help="Task id to retrieve the result"
    ),
):
    """Get task result with beautiful formatting."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[cyan]Retrieving result for {task_id[:8]}...", total=None
        )
        try:
            result = asyncio.run(sdk.get_result(task_id))
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to get task result: {e}")
            raise typer.Exit(1)

    console.print()

    if result is None:
        warning_message("No result found")
        console.print("  [dim]• Task may not be finished yet[/]")
        console.print("  [dim]• Task may have expired (24h TTL)[/]")
        console.print("  [dim]• Task ID may be incorrect[/]")
        raise typer.Exit(0)

    header = Panel(
        Align.center(
            f"[bold white]📋 Task Result[/]\n[dim]ID:[/] [cyan]{task_id[:16]}...[/]"
        ),
        border_style="green",
        box=box.DOUBLE,
    )
    console.print(header)
    console.print()

    result_json = json.dumps(result, indent=2)
    syntax = Syntax(
        result_json, "json", theme="monokai", line_numbers=True, word_wrap=True
    )

    result_panel = Panel(
        syntax,
        title="[bold white]📦 Result Data[/]",
        border_style="bright_cyan",
        box=box.ROUNDED,
    )
    console.print(result_panel)
    console.print()

    if isinstance(result, dict):
        metadata_items = []
        if result.get("timestamp"):
            metadata_items.append(
                f"[dim]⏰ Timestamp:[/] {format_timestamp(result['timestamp'])}"
            )
        if result.get("agent"):
            metadata_items.append(f"[dim]🤖 Agent:[/] [green]{result['agent']}[/]")
        if result.get("status"):
            status_color = "green" if result["status"] == "success" else "red"
            metadata_items.append(
                f"[dim]📊 Status:[/] [{status_color}]{result['status']}[/]"
            )

        if metadata_items:
            console.print("\n".join(metadata_items))
            console.print()

    success_message("Task result retrieved successfully")
    console.print()


@task_app.command("list")
def task_list(
    limit: int = typer.Option(
        100, "--limit", "-n", help="Maximum number of results to show"
    ),
):
    """List recent task results with beautiful formatting."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Loading task results...", total=None)
        try:
            results = asyncio.run(sdk.list_results(limit=limit))
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to list results: {e}")
            raise typer.Exit(1)

    console.print()

    if not results:
        warning_message("No task results found")
        console.print("  [dim]• No tasks have completed yet[/]")
        console.print("  [dim]• Results may have expired (24h TTL)[/]")
        raise typer.Exit(0)

    header = Panel(
        Align.center(
            f"[bold cyan]{len(results)}[/] task result{'s' if len(results) > 1 else ''} found"
        ),
        title="[bold white]📋 Task Results[/]",
        border_style="cyan",
        box=box.DOUBLE,
    )
    console.print(header)
    console.print()

    table = Table(
        box=box.DOUBLE_EDGE,
        border_style="bright_cyan",
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("Task ID", style="cyan", no_wrap=True)
    table.add_column("Status", style="white", justify="center")
    table.add_column("Agent", style="green")
    table.add_column("Completed At", style="dim")

    for result_data in results:
        task_id = result_data.get("task_id", "N/A")
        result = result_data.get("result", {})
        status = result.get("status", "unknown")
        agent_name = result.get("agent", "N/A")
        saved_at = result_data.get("saved_at", 0)

        if status == "success":
            status_display = "[green]✓ Success[/]"
        elif status == "failed" or status == "error":
            status_display = "[red]✗ Failed[/]"
        else:
            status_display = f"[yellow]⚠ {status}[/]"

        saved_time = format_timestamp(saved_at) if saved_at else "N/A"

        task_id_short = task_id[:16] + "..." if len(task_id) > 16 else task_id

        table.add_row(task_id_short, status_display, agent_name, saved_time)

    console.print(table)
    console.print()

    console.print(
        "[dim]💡 Tip: Use[/] omnidaemon task result --task-id <ID> [dim]to view full details[/]"
    )
    console.print()


@task_app.command("delete")
def task_delete(
    task_id: str = typer.Option(..., "--task-id", help="Task ID to delete"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a task result with confirmation."""
    console.print()

    if not confirm:
        warning_panel = Panel(
            Align.center(
                f"[bold yellow]⚠️  Warning[/]\n\n"
                f"You are about to delete task result:\n"
                f"[cyan]{task_id}[/]\n\n"
                f"[dim]This action cannot be undone.[/]"
            ),
            border_style="yellow",
            box=box.DOUBLE,
        )
        console.print(warning_panel)
        console.print()

        confirmed = typer.confirm("Are you sure you want to proceed?")
        if not confirmed:
            warning_message("Deletion cancelled")
            raise typer.Exit(0)

    console.print()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Deleting task result...", total=None)
        try:
            deleted = asyncio.run(sdk.delete_result(task_id))
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to delete result: {e}")
            raise typer.Exit(1)

    console.print()

    if deleted:
        success_message(f"Task result deleted: {task_id}")
    else:
        warning_message(f"Task result not found: {task_id}")
        raise typer.Exit(1)

    console.print()


# -------------------------
# Agent Delete Commands
# -------------------------
@agent_app.command("unsubscribe")
def agent_unsubscribe(
    topic: str = typer.Option(..., "--topic", "-t", help="Agent topic"),
    name: str = typer.Option(..., "--name", "-n", help="Agent name"),
):
    """
    Pause agent processing (unsubscribe).

    This temporarily stops the agent from consuming new messages but keeps:
    - Consumer group intact (messages continue to queue)
    - DLQ preserved (failed messages kept)
    - Agent data in storage

    To resume, simply restart the agent runner.
    """
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"[cyan]Unsubscribing agent '{name}'...", total=None)
        try:
            success = asyncio.run(sdk.unsubscribe_agent(topic=topic, agent_name=name))
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to unsubscribe agent: {e}")
            raise typer.Exit(1)

    console.print()

    if success:
        success_panel = Panel(
            Align.center(
                f"[bold green]✓ Agent Paused[/]\n\n"
                f"[green]🤖 {name}[/]\n"
                f"[dim]Topic:[/] [magenta]{topic}[/]\n\n"
                f"[dim]The agent has been unsubscribed.[/]\n"
                f"[dim]Messages will queue in Redis.[/]\n\n"
                f"[bold cyan]To resume:[/]\n"
                f"[dim]Simply restart your agent runner![/]"
            ),
            border_style="green",
            box=box.DOUBLE,
        )
        console.print(success_panel)
    else:
        warning_message(f"Agent '{name}' not found or not running")
        raise typer.Exit(1)

    console.print()


@agent_app.command("delete")
def agent_delete(
    topic: str = typer.Option(..., "--topic", "-t", help="Agent topic"),
    name: str = typer.Option(..., "--name", "-n", help="Agent name"),
    cleanup: bool = typer.Option(
        True, "--cleanup", help="Delete consumer group from Redis"
    ),
    delete_dlq: bool = typer.Option(
        False, "--delete-dlq", help="Also delete the dead-letter queue"
    ),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """
    Permanently delete an agent.

    This performs a complete cleanup:
    - Stops processing (unsubscribes)
    - Deletes consumer group from Redis (by default)
    - Optionally deletes DLQ
    - Removes agent data from storage

    The agent cannot be resumed after deletion.
    """
    console.print()

    if not confirm:
        cleanup_info = ""
        if cleanup:
            cleanup_info += "\n[yellow]✓[/] Consumer group will be deleted"
        else:
            cleanup_info += "\n[dim]✗ Consumer group will be kept[/]"

        if delete_dlq:
            cleanup_info += "\n[yellow]✓[/] Dead-letter queue will be deleted"
        else:
            cleanup_info += "\n[dim]✗ Dead-letter queue will be kept[/]"

        warning_panel = Panel(
            Align.center(
                f"[bold yellow]⚠️  Warning[/]\n\n"
                f"You are about to permanently delete agent:\n"
                f"[green]🤖 {name}[/]\n"
                f"[dim]From topic:[/] [magenta]{topic}[/]\n"
                f"{cleanup_info}\n\n"
                f"[dim]This action cannot be undone.[/]"
            ),
            border_style="yellow",
            box=box.DOUBLE,
        )
        console.print(warning_panel)
        console.print()

        confirmed = typer.confirm("Are you sure you want to proceed?")
        if not confirmed:
            warning_message("Deletion cancelled")
            raise typer.Exit(0)

    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"[cyan]Deleting agent '{name}'...", total=None)
        try:
            deleted = asyncio.run(
                sdk.delete_agent(
                    topic=topic,
                    agent_name=name,
                    delete_group=cleanup,
                    delete_dlq=delete_dlq,
                )
            )
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to delete agent: {e}")
            raise typer.Exit(1)

    console.print()

    if deleted:
        cleanup_summary = []
        cleanup_summary.append("[green]✓[/] Agent removed from storage")
        if cleanup:
            cleanup_summary.append("[green]✓[/] Consumer group deleted")
        if delete_dlq:
            cleanup_summary.append("[green]✓[/] DLQ deleted")

        success_panel = Panel(
            Align.center(
                f"[bold green]✓ Agent Deleted[/]\n\n"
                f"[green]🤖 {name}[/]\n"
                f"[dim]Topic:[/] [magenta]{topic}[/]\n\n" + "\n".join(cleanup_summary)
            ),
            border_style="green",
            box=box.DOUBLE,
        )
        console.print(success_panel)
    else:
        warning_message(f"Agent '{name}' not found in topic '{topic}'")
        raise typer.Exit(1)

    console.print()


@agent_app.command("delete-topic")
def agent_delete_topic(
    topic: str = typer.Option(..., "--topic", help="Topic to delete"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete all agents for a topic."""
    if not confirm:
        confirmed = typer.confirm(
            f"Are you sure you want to delete ALL agents from topic '{topic}'?"
        )
        if not confirmed:
            console.print("[yellow]Deletion cancelled.[/]")
            raise typer.Exit(0)

    try:
        count = asyncio.run(sdk.delete_topic(topic=topic))
    except Exception as e:
        console.print(f"[red]Failed to delete topic: {e}[/]", err=True)
        raise typer.Exit(1)

    console.print(f"[green]✓ Deleted {count} agent(s) from topic '{topic}'.[/]")


storage_app = typer.Typer(name="storage", help="Storage management commands")
app.add_typer(storage_app, name="storage")


@storage_app.command("health")
def storage_health_cmd():
    """Get storage backend health information with detailed metrics."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Checking storage health...", total=None)
        try:
            health_data = asyncio.run(sdk.storage_health())
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to get storage health: {e}")
            raise typer.Exit(1)

    console.print()

    status = health_data.get("status", "unknown")
    status_icon = "✓" if status == "healthy" else "✗"
    status_color = "green" if status == "healthy" else "red"

    header = Panel(
        Align.center(
            f"[bold {status_color}]{status_icon} {status.upper()}[/]\n"
            f"[dim]{health_data.get('backend', 'Unknown')} Storage[/]"
        ),
        border_style=status_color,
        box=box.DOUBLE,
    )
    console.print(header)
    console.print()

    cards = []

    if "total_agents" in health_data:
        cards.append(
            create_metric_card("Agents", str(health_data["total_agents"]), "🤖")
        )

    if "total_results" in health_data:
        cards.append(
            create_metric_card("Results", str(health_data["total_results"]), "📋")
        )

    if "total_metrics" in health_data:
        cards.append(
            create_metric_card("Metrics", str(health_data["total_metrics"]), "📊")
        )

    if "storage_size" in health_data:
        size = health_data["storage_size"]
        if isinstance(size, (int, float)):
            if size < 1024:
                size_str = f"{size}B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f}KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f}MB"
        else:
            size_str = str(size)
        cards.append(create_metric_card("Storage Size", size_str, "💾"))

    if cards:
        console.print(Columns(cards, equal=True, expand=True))
        console.print()

    detail_table = Table(
        box=box.SIMPLE,
        show_header=False,
        border_style="dim",
    )
    detail_table.add_column("Property", style="cyan dim")
    detail_table.add_column("Value", style="white")

    for key, value in health_data.items():
        if key not in [
            "status",
            "backend",
            "total_agents",
            "total_results",
            "total_metrics",
            "storage_size",
        ]:
            if isinstance(value, dict):
                value_str = json.dumps(value, indent=2)
            else:
                value_str = str(value)
            detail_table.add_row(key, value_str)

    if detail_table.row_count > 0:
        detail_panel = Panel(
            detail_table,
            title="[bold white]Additional Details[/]",
            border_style="blue",
            box=box.ROUNDED,
        )
        console.print(detail_panel)
        console.print()

    success_message("Storage health check completed")
    console.print()


@storage_app.command("clear-agents")
def storage_clear_agents(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """DELETE ALL agents. WARNING: Irreversible!"""
    if not confirm:
        confirmed = typer.confirm(
            "⚠️  WARNING: This will DELETE ALL agents! Are you absolutely sure?"
        )
        if not confirmed:
            console.print("[yellow]Operation cancelled.[/]")
            raise typer.Exit(0)

    try:
        count = asyncio.run(sdk.clear_agents())
    except Exception as e:
        console.print(f"[red]Failed to clear agents: {e}[/]", err=True)
        raise typer.Exit(1)

    console.print(f"[green]✓ Cleared {count} agent(s).[/]")


@storage_app.command("clear-results")
def storage_clear_results(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """DELETE ALL task results. WARNING: Irreversible!"""
    if not confirm:
        confirmed = typer.confirm(
            "⚠️  WARNING: This will DELETE ALL task results! Are you absolutely sure?"
        )
        if not confirmed:
            console.print("[yellow]Operation cancelled.[/]")
            raise typer.Exit(0)

    try:
        count = asyncio.run(sdk.clear_results())
    except Exception as e:
        console.print(f"[red]Failed to clear results: {e}[/]", err=True)
        raise typer.Exit(1)

    console.print(f"[green]✓ Cleared {count} result(s).[/]")


@storage_app.command("clear-metrics")
def storage_clear_metrics(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """DELETE ALL metrics. WARNING: Irreversible!"""
    if not confirm:
        confirmed = typer.confirm(
            "⚠️  WARNING: This will DELETE ALL metrics! Are you absolutely sure?"
        )
        if not confirmed:
            console.print("[yellow]Operation cancelled.[/]")
            raise typer.Exit(0)

    try:
        count = asyncio.run(sdk.clear_metrics())
    except Exception as e:
        console.print(f"[red]Failed to clear metrics: {e}[/]", err=True)
        raise typer.Exit(1)

    console.print(f"[green]✓ Cleared {count} metric(s).[/]")


@storage_app.command("clear-all")
def storage_clear_all(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """DELETE ALL DATA - Nuclear option with maximum safety."""
    console.print()

    if not confirm:
        danger_panel = Panel(
            Align.center(
                "[bold red on black] ⚠️  DANGER ZONE ⚠️  [/]\n\n"
                "[bold red]This will DELETE ALL DATA:[/]\n\n"
                "[red]• All Agents[/]\n"
                "[red]• All Task Results[/]\n"
                "[red]• All Metrics[/]\n"
                "[red]• All Configuration[/]\n\n"
                "[bold yellow]THIS ACTION IS IRREVERSIBLE![/]\n"
                "[dim]There is no undo, no backup, no recovery.[/]"
            ),
            border_style="bold red",
            box=box.DOUBLE_EDGE,
        )
        console.print(danger_panel)
        console.print()

        console.print("[bold red]Type 'DELETE EVERYTHING' to confirm:[/]")
        user_input = typer.prompt("", default="", show_default=False)

        if user_input != "DELETE EVERYTHING":
            warning_message("Operation cancelled - input did not match")
            raise typer.Exit(0)

        console.print()
        final_confirm = typer.confirm("[bold red]Are you ABSOLUTELY sure?[/]")
        if not final_confirm:
            warning_message("Operation cancelled")
            raise typer.Exit(0)

    console.print()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[red]Deleting all data...", total=None)
        try:
            counts = asyncio.run(sdk.clear_all())
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to clear all data: {e}")
            raise typer.Exit(1)

    console.print()

    result_table = Table(
        box=box.ROUNDED,
        border_style="green",
        show_header=True,
        header_style="bold green",
        title="[bold white]Deletion Summary[/]",
    )
    result_table.add_column("Data Type", style="cyan")
    result_table.add_column("Deleted Count", justify="right", style="green")

    result_table.add_row("Agents", str(counts.get("agents", 0)))
    result_table.add_row("Results", str(counts.get("results", 0)))
    result_table.add_row("Metrics", str(counts.get("metrics", 0)))
    result_table.add_row("Config", str(counts.get("config", 0)))

    console.print(result_table)
    console.print()

    success_message("All data has been cleared successfully")
    console.print()


config_app = typer.Typer(name="config", help="Configuration management commands")
app.add_typer(config_app, name="config")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Configuration key"),
    value: str = typer.Argument(..., help="Configuration value (JSON)"),
):
    """Save a configuration value."""
    try:
        parsed_value = json.loads(value)
    except json.JSONDecodeError:
        parsed_value = value

    try:
        asyncio.run(sdk.save_config(key, parsed_value))
    except Exception as e:
        console.print(f"[red]Failed to save config: {e}[/]", err=True)
        raise typer.Exit(1)

    console.print(f"[green]✓ Configuration '{key}' saved.[/]")


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Configuration key"),
    default: str = typer.Option(None, "--default", help="Default value if not found"),
):
    """Get a configuration value."""
    try:
        value = asyncio.run(sdk.get_config(key, default=default))
    except Exception as e:
        console.print(f"[red]Failed to get config: {e}[/]", err=True)
        raise typer.Exit(1)

    console.print(
        Panel(
            json.dumps(value, indent=2)
            if type(value).__name__ in ("dict", "list")
            else str(value),
            title=f"⚙️  Configuration: {key}",
            border_style="cyan",
        )
    )


@app.command()
def health():
    """Show comprehensive OmniDaemon system health."""
    console.print()
    console.print(OMNIDAEMON_BANNER)
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Running health check...", total=None)
        try:
            data = asyncio.run(sdk.health())
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to fetch health: {e}")
            raise typer.Exit(1)

    console.print()

    status = data.get("status", "unknown")
    event_bus_connected = data.get("event_bus_connected", False)
    storage_healthy = data.get("storage_healthy", False)
    has_active_consumers = data.get("has_active_consumers", False)
    registered_agents_count = data.get("registered_agents_count", 0)
    active_consumers = data.get("active_consumers", {})

    if status == "running":
        overall_status = "[bold green]● RUNNING[/]"
        status_color = "green"
        consumer_count = len(active_consumers)
        status_desc = (
            f"Agents actively processing events ({consumer_count} active consumer(s))"
        )
    elif status == "stopped":
        overall_status = "[bold yellow]● STOPPED[/]"
        status_color = "yellow"
        status_desc = f"{registered_agents_count} agent(s) registered but not running"
    elif status == "ready":
        overall_status = "[bold green]● READY[/]"
        status_color = "green"
        status_desc = "Infrastructure healthy, ready for agents"
    elif status == "degraded":
        overall_status = "[bold yellow]● DEGRADED[/]"
        status_color = "yellow"
        status_desc = "Some infrastructure components unavailable"
    else:
        overall_status = "[bold red]● DOWN[/]"
        status_color = "red"
        status_desc = "Infrastructure components unavailable"

    header = Panel(
        Align.center(
            f"{overall_status}\n"
            f"[dim]{status_desc}[/]\n\n"
            f"[dim]Runner ID:[/] [cyan]{data.get('runner_id', 'N/A')[:12]}...[/]"
        ),
        border_style=status_color,
        box=box.DOUBLE,
        title="[bold white]❤️  System Health[/]",
    )
    console.print(header)
    console.print()

    agents = data.get("agents", {})
    agent_count = sum(len(v) for v in agents.values())
    topic_count = len(agents)
    uptime = data.get("uptime_seconds", 0)

    if uptime < 60:
        uptime_str = f"{uptime:.0f}s"
    elif uptime < 3600:
        uptime_str = f"{uptime / 60:.1f}m"
    else:
        uptime_str = f"{uptime / 3600:.1f}h"

    cards = [
        create_metric_card("Active Agents", str(agent_count), "🤖"),
        create_metric_card("Topics", str(topic_count), "📡"),
        create_metric_card("Uptime", uptime_str, "⏱️"),
    ]

    console.print(Columns(cards, equal=True, expand=True))
    console.print()

    event_bus = "✓ Connected" if event_bus_connected else "✗ Disconnected"
    event_bus_color = "green" if event_bus_connected else "red"

    conn_table = Table(
        box=box.ROUNDED,
        border_style="cyan",
        show_header=True,
        header_style="bold cyan",
    )
    conn_table.add_column("Component", style="white")
    conn_table.add_column("Status", justify="center")
    conn_table.add_column("Details", style="dim")

    conn_table.add_row(
        "Event Bus",
        f"[{event_bus_color}]{event_bus}[/]",
        data.get("event_bus_type", "N/A"),
    )

    storage_status_data = data.get("storage_status", {})
    storage_status_str = storage_status_data.get("status", "unknown")

    if storage_status_str == "healthy":
        storage_icon = "✓ Healthy"
        storage_color = "green"
        storage_details = storage_status_data.get("backend", "N/A")
    elif storage_status_str == "error":
        storage_icon = "✗ Error"
        storage_color = "red"
        error_msg = storage_status_data.get("error", "Unknown error")
        storage_details = (
            f"{storage_status_data.get('backend', 'N/A')} - {error_msg[:30]}..."
        )
    else:
        storage_icon = "⚠ Unhealthy"
        storage_color = "yellow"
        storage_details = storage_status_data.get("backend", "N/A")

    conn_table.add_row(
        "Storage", f"[{storage_color}]{storage_icon}[/]", storage_details
    )

    conn_panel = Panel(
        conn_table,
        title="[bold white]🔌 Connections[/]",
        border_style="bright_cyan",
        box=box.ROUNDED,
    )
    console.print(conn_panel)
    console.print()

    if agents:
        topics_tree = Tree(
            "[bold magenta]📋 Subscribed Topics[/]",
            guide_style="dim",
        )
        for topic, agent_list in sorted(agents.items()):
            topic_branch = topics_tree.add(
                f"[cyan]{topic}[/] [dim]({len(agent_list)} agent{'s' if len(agent_list) > 1 else ''})[/]"
            )
            for agent in agent_list[:3]:
                topic_branch.add(f"[green]• {agent.get('name', 'unnamed')}[/]")
            if len(agent_list) > 3:
                topic_branch.add(f"[dim]... and {len(agent_list) - 3} more[/]")

        console.print(topics_tree)
        console.print()

    success_message("Health check completed successfully")
    console.print()


@app.command()
def metrics(
    topic: str = typer.Option(None, "--topic", "-t", help="Filter by topic"),
    limit: int = typer.Option(
        100, "--limit", "-n", help="Maximum number of metrics to show"
    ),
):
    """Display detailed performance metrics."""
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Loading metrics...", total=None)
        try:
            data = asyncio.run(sdk.metrics(topic=topic, limit=limit))
            progress.update(task, completed=True)
        except Exception as e:
            error_message(f"Failed to fetch metrics: {e}")
            raise typer.Exit(1)

    console.print()

    if not data:
        warning_message("No metrics data available")
        console.print("  [dim]• Agents may not have processed any tasks yet[/]")
        console.print("  [dim]• Try publishing a task first[/]")
        raise typer.Exit(0)

    title = "📊 Performance Metrics"
    if topic:
        title += f" - [magenta]{topic}[/]"

    header = Panel(
        Align.center(
            f"[bold white]{len(data)}[/] metric{'s' if len(data) > 1 else ''} recorded"
        ),
        title=title,
        border_style="cyan",
        box=box.DOUBLE,
    )
    console.print(header)
    console.print()

    total_received = 0
    total_processed = 0
    total_failed = 0

    for topic_name, agents in data.items():
        for agent_name, stats in agents.items():
            total_received += stats.get("tasks_received", 0)
            total_processed += stats.get("tasks_processed", 0)
            total_failed += stats.get("tasks_failed", 0)

    if total_received > 0:
        success_rate = (total_processed / total_received) * 100
    else:
        success_rate = 0

    cards = [
        create_metric_card("Received", str(total_received), "📨"),
        create_metric_card("Processed", str(total_processed), "✅"),
        create_metric_card("Failed", str(total_failed), "❌"),
        create_metric_card("Success Rate", f"{success_rate:.1f}%", "📈"),
    ]

    console.print(Columns(cards, equal=True, expand=True))
    console.print()

    table = Table(
        box=box.DOUBLE_EDGE,
        border_style="bright_cyan",
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("Agent", style="green")
    table.add_column("Topic", style="magenta")
    table.add_column("Received", justify="right", style="cyan")
    table.add_column("Processed", justify="right", style="green")
    table.add_column("Failed", justify="right", style="red")
    table.add_column("Avg Time", justify="right", style="yellow")

    metrics_list = []
    for topic_name, agents in data.items():
        for agent_name, stats in agents.items():
            metrics_list.append({"topic": topic_name, "agent": agent_name, **stats})

    metrics_list.sort(key=lambda x: x.get("tasks_received", 0), reverse=True)

    for metric in metrics_list[:limit]:
        agent_name = metric.get("agent", "N/A")
        topic_name = metric.get("topic", "N/A")
        received = metric.get("tasks_received", 0)
        processed = metric.get("tasks_processed", 0)
        failed = metric.get("tasks_failed", 0)
        avg_time = metric.get("avg_processing_time_sec", 0)

        if avg_time < 1:
            time_str = f"{avg_time * 1000:.0f}ms"
        else:
            time_str = f"{avg_time:.2f}s"

        table.add_row(
            agent_name,
            topic_name,
            str(received),
            str(processed),
            str(failed) if failed > 0 else "[dim]0[/]",
            time_str,
        )

    console.print(table)
    console.print()

    console.print("[dim]💡 Tips:[/]")
    console.print(
        "  [cyan]• Filter by topic:[/] omnidaemon metrics --topic <topic_name>"
    )
    console.print("  [cyan]• Adjust limit:[/] omnidaemon metrics --limit 50")
    console.print()


@app.command()
def info():
    """Show OmniDaemon welcome screen and quick start guide."""
    console.print()
    console.print(OMNIDAEMON_BANNER)
    console.print()

    welcome_panel = Panel(
        Align.center(
            "[bold white]Welcome to OmniDaemon![/]\n\n"
            "[dim]Universal Event-Driven Runtime Engine for AI Agents[/]\n"
            "[dim cyan]React • Process • Scale • Monitor Events in Real-Time[/]"
        ),
        border_style="bright_cyan",
        box=box.DOUBLE,
    )
    console.print(welcome_panel)
    console.print()

    quickstart = Table(
        box=box.ROUNDED,
        border_style="green",
        show_header=True,
        header_style="bold green",
        title="[bold white]⚡ Quick Start Guide[/]",
    )
    quickstart.add_column("Command", style="cyan bold", no_wrap=True)
    quickstart.add_column("Description", style="white")

    quickstart.add_row("omnidaemon health", "Check system status and health")
    quickstart.add_row("omnidaemon agent list", "View all registered agents")
    quickstart.add_row("omnidaemon task publish", "Publish a new task")
    quickstart.add_row("omnidaemon task list", "View recent task results")
    quickstart.add_row("omnidaemon metrics", "Display performance metrics")
    quickstart.add_row("omnidaemon storage health", "Check storage backend status")

    console.print(quickstart)
    console.print()

    features = Tree(
        "✨ [bold magenta]Core Capabilities[/]",
        guide_style="dim",
    )

    event_branch = features.add("[bold cyan]⚡ Event-Driven Engine[/]")
    event_branch.add("[dim]• Asynchronous event processing with Redis Streams[/]")
    event_branch.add("[dim]• Pub/Sub messaging with topic-based routing[/]")
    event_branch.add("[dim]• Consumer groups for parallel processing[/]")
    event_branch.add("[dim]• Dead letter queue and automatic retry[/]")
    event_branch.add("[dim]• Real-time event monitoring and metrics[/]")

    agent_branch = features.add("[bold green]🤖 AI Agent Runtime[/]")
    agent_branch.add("[dim]• Multi-framework support (CrewAI, AutoGen, LangGraph)[/]")
    agent_branch.add("[dim]• Hot reload and dynamic registration[/]")
    agent_branch.add("[dim]• Event-triggered agent execution[/]")
    agent_branch.add("[dim]• Background processing and scheduling[/]")

    storage_branch = features.add("[bold yellow]💾 Persistent State[/]")
    storage_branch.add("[dim]• Pluggable backends (JSON, Redis)[/]")
    storage_branch.add("[dim]• Task results with TTL[/]")
    storage_branch.add("[dim]• Performance metrics tracking[/]")
    storage_branch.add("[dim]• Health monitoring and diagnostics[/]")

    console.print(features)
    console.print()

    help_panel = Panel(
        "[cyan]📚 Documentation:[/] [link]https://github.com/omnirexflora-labs/OmniDaemon[/]\n"
        "[cyan]💬 Community:[/] Join our Discord or Slack\n"
        "[cyan]🐛 Issues:[/] Report on GitHub\n"
        "[cyan]📖 Full CLI Help:[/] [bold]omnidaemon --help[/]",
        title="[bold white]Need Help?[/]",
        border_style="blue",
        box=box.ROUNDED,
    )
    console.print(help_panel)
    console.print()

    info_message("Ready to build amazing AI agent workflows!")
    console.print()


if __name__ == "__main__":
    app()
