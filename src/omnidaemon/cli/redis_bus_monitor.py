import asyncio
import json
import logging
import signal
import sys
import time
from typing import Dict, Any, Optional, List, Tuple

from tabulate import tabulate
from decouple import config
from omnidaemon.event_bus.redis_stream_bus import RedisStreamEventBus

try:
    from colorama import init as colorama_init, Fore, Style

    colorama_init()
except Exception:

    class Fore:
        RED = "\033[31m"
        GREEN = "\033[32m"
        YELLOW = "\033[33m"
        BLUE = "\033[34m"
        RESET = "\033[0m"

    class Style:
        BRIGHT = "\033[1m"
        NORMAL = "\033[0m"


logger = logging.getLogger("omni.bus")


# -------------------------
# Helper: Clear screen
# -------------------------
def clear_screen():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


# -------------------------
# Reusable formatting
# -------------------------
def color_for_dlq(dlq_count: int) -> str:
    return Fore.RED + Style.BRIGHT if dlq_count > 0 else Fore.GREEN


def color_for_pending(pending: int) -> str:
    if pending > 50:
        return Fore.RED + Style.BRIGHT
    if pending > 0:
        return Fore.YELLOW
    return Fore.GREEN


# -------------------------
# STATELESS BUS FUNCTIONS
# -------------------------


async def bus_list_streams(redis_url: Optional[str] = None):
    redis_url = redis_url or config("REDIS_URL", default="redis://localhost:6379/0")
    bus = RedisStreamEventBus(redis_url=redis_url)
    await bus.connect()
    try:
        keys = await bus._redis.keys("stream:*")

        def to_str(x):
            return x.decode() if isinstance(x, bytes) else x

        keys_str = [to_str(k) for k in keys]
        streams = [k for k in keys_str if not k.endswith(":dlq")]
        rows = []
        for s in streams:
            length = await bus._redis.xlen(s)
            rows.append([s, length])
        print(tabulate(rows, headers=["Stream", "Count"], tablefmt="github"))
    finally:
        await bus._redis.close()


async def bus_inspect_stream(
    stream: str, limit: int = 5, redis_url: Optional[str] = None
):
    """Inspect recent messages in a stream."""
    redis_url = redis_url or config("REDIS_URL", default="redis://localhost:6379/0")
    bus = RedisStreamEventBus(redis_url=redis_url)
    await bus.connect()
    try:
        if not stream.startswith("stream:"):
            stream = f"stream:{stream}"
        entries = await bus._redis.xrevrange(stream.encode(), count=limit)
        if not entries:
            print(f"No entries in {stream}")
            return
        for msg_id, fields in entries:
            print(f"ID: {msg_id.decode() if isinstance(msg_id, bytes) else msg_id}")
            data = fields.get(b"data") or fields.get("data")
            if isinstance(data, bytes):
                data = data.decode()
            try:
                print(json.dumps(json.loads(data), indent=2))
            except Exception:
                print(data)
            print("-" * 40)
    finally:
        await bus._redis.close()


async def bus_list_groups(stream: str, redis_url: Optional[str] = None):
    """List consumer groups for a stream."""
    redis_url = redis_url or config("REDIS_URL", default="redis://localhost:6379/0")
    bus = RedisStreamEventBus(redis_url=redis_url)
    await bus.connect()
    try:
        if not stream.startswith("stream:"):
            stream = f"stream:{stream}"
        try:
            groups = await bus._redis.xinfo_groups(stream.encode())
        except Exception:
            print(f"No groups for {stream}")
            return
        rows = []
        for g in groups:
            name = (
                g.get(b"name", g.get("name", b"")).decode()
                if isinstance(g.get(b"name"), bytes)
                else g.get("name", "")
            )
            consumers = g.get(b"consumers", g.get("consumers", 0))
            pending = g.get(b"pending", g.get("pending", 0))
            last_id = (
                g.get(b"last-delivered-id", g.get("last-delivered-id", b"")).decode()
                if isinstance(g.get(b"last-delivered-id"), bytes)
                else g.get("last-delivered-id", "")
            )
            rows.append([name, consumers, pending, last_id])
        print(
            tabulate(
                rows,
                headers=["Group", "Consumers", "Pending", "LastDelivered"],
                tablefmt="github",
            )
        )
    finally:
        await bus._redis.close()


async def bus_inspect_dlq(topic: str, limit: int = 5, redis_url: Optional[str] = None):
    """Inspect dead-letter queue for a topic."""
    redis_url = redis_url or config("REDIS_URL", default="redis://localhost:6379/0")
    bus = RedisStreamEventBus(redis_url=redis_url)
    await bus.connect()
    try:
        entries = await bus.read_dlq(topic, limit=limit)
        if not entries:
            print("No DLQ entries")
            return
        for msg_id, data in entries:
            print(f"DLQ ID: {msg_id}")
            try:
                print(json.dumps(data, indent=2))
            except Exception:
                print(data)
            print("-" * 40)
    finally:
        await bus._redis.close()


async def bus_get_stats(redis_url: Optional[str] = None, as_json: bool = False):
    """Get one-shot stats across all topics — NO get_stream_info."""
    redis_url = redis_url or config("REDIS_URL", default="redis://localhost:6379/0")
    bus = RedisStreamEventBus(redis_url=redis_url)
    await bus.connect()
    try:
        keys = await bus._redis.keys("stream:*")
        streams = [k for k in keys if not k.endswith(":dlq")]

        snapshot = {"timestamp": time.time(), "topics": {}}
        for s in streams:
            stream_key = s if isinstance(s, bytes) else s.encode()
            topic = (s.decode() if isinstance(s, bytes) else s).replace(
                "stream:", "", 1
            )

            # Get stream length
            length = await bus._redis.xlen(stream_key)

            # Get DLQ length
            dlq_key = f"stream:{topic}:dlq".encode()
            dlq_length = await bus._redis.xlen(dlq_key)

            # Get consumer groups
            try:
                groups_raw = await bus._redis.xinfo_groups(stream_key)
                groups = []
                for g in groups_raw:
                    name = (
                        g.get(b"name", b"").decode()
                        if isinstance(g.get(b"name"), bytes)
                        else g.get("name", "")
                    )
                    consumers = g.get(b"consumers", 0)
                    pending = g.get(b"pending", 0)
                    last_id = (
                        g.get(b"last-delivered-id", b"").decode()
                        if isinstance(g.get(b"last-delivered-id"), bytes)
                        else g.get("last-delivered-id", "")
                    )
                    groups.append(
                        {
                            "name": name,
                            "consumers": consumers,
                            "pending": pending,
                            "last_delivered_id": last_id,
                        }
                    )
            except Exception:
                groups = []

            snapshot["topics"][topic] = {
                "length": length,
                "dlq_length": dlq_length,
                "groups": groups,
            }

        # Redis memory info
        redis_info = {}
        try:
            info_raw = await bus._redis.info()
            used_mem = (
                info_raw.get("used_memory_human", "-")
                if isinstance(info_raw, dict)
                else "-"
            )
            redis_info = {"used_memory_human": used_mem}
        except Exception:
            redis_info = {"used_memory_human": "-"}

        result = {"snapshot": snapshot, "redis_info": redis_info}
        if as_json:
            print(json.dumps(result, indent=2, default=str))
        else:
            rows = []
            for topic, d in snapshot["topics"].items():
                groups = d.get("groups", [])
                group_name = groups[0]["name"] if groups else "-"
                rows.append(
                    [topic, d["length"], len(groups), d["dlq_length"], group_name]
                )
            print("Snapshot:")
            print(
                tabulate(
                    rows,
                    headers=["Topic", "Len", "Groups", "DLQ", "PrimaryGroup"],
                    tablefmt="github",
                )
            )
    finally:
        await bus._redis.close()


async def bus_watch_live(
    interval: int = 2, as_json: bool = False, redis_url: Optional[str] = None
):
    """Start live dashboard."""
    redis_url = redis_url or config("REDIS_URL", default="redis://localhost:6379/0")
    bus = RedisStreamEventBus(redis_url=redis_url)
    await bus.connect()

    print("Starting OmniDaemon Live Monitor. Ctrl-C to exit.\n")

    gen = bus.monitor_generator()
    stop_future = asyncio.get_event_loop().create_future()

    def _signal_handler():
        if not stop_future.done():
            stop_future.set_result(True)

    try:
        asyncio.get_event_loop().add_signal_handler(signal.SIGINT, _signal_handler)
        asyncio.get_event_loop().add_signal_handler(signal.SIGTERM, _signal_handler)
    except NotImplementedError:
        pass  # Windows

    # State for live view
    state: Dict[str, Dict[str, Any]] = {}
    counters: Dict[str, Dict[str, int]] = {}
    throughput: Dict[str, float] = {}

    async def aggregator():
        async for ev in gen:
            if not ev:
                continue
            evt = ev.get("event")
            if evt == "snapshot":
                snap = ev.get("data", {})
                for topic, data in snap.get("topics", {}).items():
                    state[topic] = {
                        "length": data.get("length", 0),
                        "pending": data.get("pending", 0),
                        "dlq": data.get("dlq", 0),
                        "groups": data.get("groups", []),
                    }
                    if topic not in counters:
                        counters[topic] = {
                            "processed": 0,
                            "dlq_push": 0,
                            "reclaimed": 0,
                        }
            else:
                topic = ev.get("topic") or (ev.get("data") or {}).get("topic")
                if not topic:
                    continue
                if topic not in counters:
                    counters[topic] = {"processed": 0, "dlq_push": 0, "reclaimed": 0}
                if evt == "processed":
                    counters[topic]["processed"] += 1
                elif evt == "dlq_push":
                    counters[topic]["dlq_push"] += 1
                elif evt == "reclaimed_processed":
                    counters[topic]["reclaimed"] += 1

    agg_task = asyncio.create_task(aggregator())

    last_snapshot_time = 0.0
    last_processed: Dict[str, int] = {}

    try:
        while not stop_future.done():
            # Auto-discover streams
            def to_str(x):
                return x.decode() if isinstance(x, bytes) else x

            keys = await bus._redis.keys("stream:*")
            topics = set()
            keys_str = [to_str(k) for k in keys]

            for k in keys_str:
                if not k.endswith(":dlq"):
                    topic = k.replace("stream:", "", 1)
                    topics.add(topic)

            snapshot = {"timestamp": time.time(), "topics": {}}
            for topic in sorted(topics):
                info = state.get(
                    topic, {"length": 0, "pending": 0, "dlq": 0, "groups": []}
                )
                cnt = counters.get(
                    topic, {"processed": 0, "dlq_push": 0, "reclaimed": 0}
                )
                last = last_processed.get(topic, cnt["processed"])
                curr = cnt["processed"]
                dt = (
                    (time.time() - last_snapshot_time)
                    if last_snapshot_time
                    else interval
                )
                rate = (curr - last) / max(dt, 1e-6)
                last_processed[topic] = curr

                group_names = [g.get("name", "N/A") for g in info.get("groups", [])][
                    :1
                ] or ["N/A"]
                snapshot["topics"][topic] = {
                    "length": info["length"],
                    "pending": info["pending"],
                    "dlq": info["dlq"],
                    "group": group_names[0],
                    "counters": cnt,
                    "rate": rate,
                }

            if as_json:
                print(json.dumps(snapshot, indent=2, default=str))
            else:
                clear_screen()
                ts = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(snapshot["timestamp"])
                )
                header = f"OmniDaemon Live Monitor  |  {ts}"
                print(header)
                print("=" * len(header))

                rows = []
                for topic, d in snapshot["topics"].items():
                    color_dlq = color_for_dlq(d["dlq"])
                    color_pending = color_for_pending(d["pending"])
                    rows.append(
                        [
                            topic,
                            d["length"],
                            f"{color_pending}{d['pending']}{Fore.RESET}",
                            f"{color_dlq}{d['dlq']}{Fore.RESET}",
                            d["group"],
                            d["counters"]["processed"],
                            d["counters"]["dlq_push"],
                            d["counters"]["reclaimed"],
                            f"{d['rate']:.2f}",
                        ]
                    )

                headers = [
                    "Topic",
                    "Len",
                    "Pending",
                    "DLQ",
                    "Group",
                    "Processed",
                    "DLQ",
                    "Reclaimed",
                    "Proc/s",
                ]
                print(tabulate(rows, headers=headers, tablefmt="github"))

                try:
                    info = await bus._redis.info()
                    mem = info.get("used_memory_human", "-")
                except Exception:
                    mem = "-"
                print()
                print(f"Redis Memory: {mem}  |  Topics: {len(snapshot['topics'])}")
                print("Ctrl-C to quit.")

            last_snapshot_time = time.time()
            await asyncio.sleep(interval)

    finally:
        agg_task.cancel()
        try:
            await agg_task
        except asyncio.CancelledError:
            pass
        await bus._redis.close()
        print("\nExiting monitor...")
