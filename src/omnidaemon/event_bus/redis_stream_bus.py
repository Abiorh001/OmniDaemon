import asyncio
import json
import logging
import time
from typing import Optional, Callable, Dict, Any, AsyncGenerator, List
from redis import asyncio as aioredis
from decouple import config

logger = logging.getLogger("redis_stream_bus")
logger.setLevel(logging.INFO)


class RedisStreamEventBus:
    """
    Redis Streams Event Bus (production-ready):
      - durable streams (xadd)
      - per-subscriber unique consumer groups (fan-out) by default
      - optional shared group mode for load-balancing (not shown here; use group_name param)
      - DLQ for failed messages
      - pending reclaim (xclaim) loop
      - stream trimming (maxlen) per publish
      - real-time monitor: console summary and async generator for metrics
    """

    def __init__(
        self,
        redis_url: str = config("REDIS_URL", default="redis://localhost:6379/0"),
        default_maxlen: int = 10_000,
        reclaim_idle_ms: int = 60_000,
        reclaim_interval: int = 30,
        dlq_retry_limit: int = 3,
    ):
        self.redis_url = redis_url
        self.default_maxlen = default_maxlen
        self.reclaim_idle_ms = reclaim_idle_ms
        self.reclaim_interval = reclaim_interval
        self.dlq_retry_limit = dlq_retry_limit

        self._redis: Optional[aioredis.Redis] = None
        self._connect_lock = asyncio.Lock()

        self._callbacks: Dict[str, Callable[[dict], Any]] = {}

        self._consumers: Dict[str, Dict[str, Any]] = {}
        self._running = False

        self._monitor_queues: List[asyncio.Queue] = []
        self._monitor_task: Optional[asyncio.Task] = None

    # ----------------
    # Connection
    # ----------------
    async def connect(self):
        async with self._connect_lock:
            if self._redis:
                return
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            logger.info(f"[RedisStreamBus] connected -> {self.redis_url}")

    async def close(self):
        self._running = False
        # cancel consumer tasks
        for meta in list(self._consumers.values()):
            t = meta.get("task")
            r = meta.get("reclaim_task")
            if t:
                t.cancel()
            if r:
                r.cancel()
        if self._monitor_task:
            self._monitor_task.cancel()
        if self._redis:
            await self._redis.close()
            self._redis = None
        logger.info("[RedisStreamBus] closed")

    # ----------------
    # Publish
    # ----------------
    async def publish(
        self, topic: str, message: Any, maxlen: Optional[int] = None
    ) -> str:
        """
        Publish message to stream:{topic}.
        Returns the assigned stream id.
        """
        if not self._redis:
            await self.connect()
        stream_name = f"stream:{topic}"
        payload = json.dumps(message)
        maxlen = maxlen or self.default_maxlen
        msg_id = await self._redis.xadd(
            stream_name, {"data": payload}, maxlen=maxlen, approximate=True
        )
        logger.debug(f"[RedisStreamBus] published {stream_name} id={msg_id}")

    # ----------------
    # Subscribe
    # ----------------
    async def subscribe(
        self,
        topic: str,
        callback: Callable[[dict], Any],
        *,
        group_name: Optional[str] = None,
        consumer_name: Optional[str] = None,
        shared: bool = False,
    ):
        """
        Subscribe a callback to topic. Default behavior creates a unique group
        per subscription (fan-out). If shared=True, use group_name or group:{topic}.
        """
        if not self._redis:
            await self.connect()

        stream_name = f"stream:{topic}"

        group = group_name or (
            f"group:{topic}" if shared else f"group:{topic}:{callback.__name__}"
        )
        consumer = consumer_name or f"consumer:{topic}:{id(self)}"
        dlq_stream = f"{stream_name}:dlq"

        # register callback
        self._callbacks[topic] = callback

        # ensure stream & group exist (mkstream True)
        try:
            await self._redis.xgroup_create(stream_name, group, id="$", mkstream=True)
            logger.info(f"[RedisStreamBus] created group {group} for {stream_name}")
        except aioredis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(f"[RedisStreamBus] group {group} exists")
            else:
                raise

        self._running = True
        consume_task = asyncio.create_task(
            self._consume_loop(
                stream_name, topic, group, consumer, dlq_stream, callback
            )
        )
        reclaim_task = asyncio.create_task(
            self._reclaim_loop(stream_name, topic, group, consumer)
        )
        self._consumers[topic] = {
            "group": group,
            "consumer": consumer,
            "task": consume_task,
            "reclaim_task": reclaim_task,
            "dlq": dlq_stream,
        }
        # ensure monitor running
        if not self._monitor_task:
            self._monitor_task = asyncio.create_task(
                self._monitor_loop(poll_interval=2)
            )

        logger.info(
            f"[RedisStreamBus] subscribed topic={topic} group={group} consumer={consumer}"
        )

    # ----------------
    # Consumer loop
    # ----------------
    async def _consume_loop(
        self,
        stream_name: str,
        topic: str,
        group: str,
        consumer: str,
        dlq_stream: str,
        callback: Callable,
    ):
        """
        Loop reading from group (XREADGROUP) and calling callback.
        On failure pushes message to DLQ; returns message is xacked to avoid retries.
        """
        logger.info(
            f"[RedisStreamBus] consumer loop start topic={topic} group={group} consumer={consumer}"
        )
        try:
            while self._running:
                try:
                    entries = await self._redis.xreadgroup(
                        groupname=group,
                        consumername=consumer,
                        streams={stream_name: ">"},
                        count=10,
                        block=5000,
                    )
                    if not entries:
                        continue
                    for _, msgs in entries:
                        for msg_id, fields in msgs:
                            raw = fields.get("data")
                            try:
                                payload = json.loads(raw)
                            except Exception:
                                payload = {"raw": raw}
                            try:
                                # dispatch
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(payload)
                                else:
                                    loop = asyncio.get_running_loop()
                                    await loop.run_in_executor(None, callback, payload)
                                # ack on success
                                await self._redis.xack(stream_name, group, msg_id)
                                # publish monitor metric
                                await self._emit_monitor(
                                    {
                                        "topic": topic,
                                        "event": "processed",
                                        "msg_id": msg_id,
                                        "group": group,
                                        "consumer": consumer,
                                        "timestamp": time.time(),
                                    }
                                )
                            except Exception as cb_err:
                                logger.exception(
                                    f"[RedisStreamBus] callback error topic={topic} id={msg_id}: {cb_err}"
                                )
                                # push to DLQ with metadata
                                dlq_payload = {
                                    "failed_message": payload,
                                    "error": str(cb_err),
                                    "failed_at": time.time(),
                                    "original_id": msg_id,
                                }
                                await self._redis.xadd(
                                    dlq_stream,
                                    {"data": json.dumps(dlq_payload)},
                                    maxlen=self.default_maxlen,
                                    approximate=True,
                                )
                                # ack so it won't re-deliver infinitely
                                await self._redis.xack(stream_name, group, msg_id)
                                await self._emit_monitor(
                                    {
                                        "topic": topic,
                                        "event": "dlq_push",
                                        "msg_id": msg_id,
                                        "group": group,
                                        "consumer": consumer,
                                        "timestamp": time.time(),
                                    }
                                )
                except asyncio.CancelledError:
                    raise
                except Exception as err:
                    logger.exception(
                        f"[RedisStreamBus] error in consume loop topic={topic}: {err}"
                    )
                    await asyncio.sleep(1)
        finally:
            logger.info(f"[RedisStreamBus] consumer loop stopped topic={topic}")

    # ----------------
    # Reclaim loop
    # ----------------
    async def _reclaim_loop(
        self, stream_name: str, topic: str, group: str, consumer: str
    ):
        """
        Reclaim pending messages idle longer than reclaim_idle_ms and hand them to the current consumer.
        """
        logger.info(f"[RedisStreamBus] reclaim loop start topic={topic} group={group}")
        while self._running:
            try:
                # XPENDING range returns entries with idle times
                # Using xpending_range if available or xpending + xclaim fallback
                pending = []
                try:
                    # newer redis-py: xpending_range
                    pending = await self._redis.xpending_range(
                        stream_name, group, "-", "+", count=50
                    )
                except Exception:
                    # fallback to XPENDING summary + XPENDING to fetch IDs - keep simple: use XPENDING summary then XCLAIM of ranges isn't as available
                    info = await self._redis.xpending(stream_name, group)
                    # info may be tuple or dict; graceful fallback
                    # if not iterable entries, we skip reclaim loop iteration
                    pending = []
                # pending entries are either tuples or dicts depending on API
                for entry in pending:
                    try:
                        # normalize
                        if isinstance(entry, dict):
                            msg_id = entry.get("message_id") or entry.get("id")
                            idle = entry.get("elapsed", 0)
                        elif isinstance(entry, tuple) or isinstance(entry, list):
                            msg_id = entry[0]
                            idle = int(entry[2]) if len(entry) > 2 else 0
                        else:
                            continue
                        if idle >= self.reclaim_idle_ms:
                            # claim to current consumer
                            claimed = await self._redis.xclaim(
                                stream_name,
                                group,
                                consumer,
                                min_idle_time=self.reclaim_idle_ms,
                                message_ids=[msg_id],
                            )
                            if claimed:
                                logger.warning(
                                    f"[RedisStreamBus] reclaimed {msg_id} -> {consumer} (topic={topic})"
                                )

                                for msg in claimed:
                                    _id = msg[0]
                                    fields = msg[1]
                                    raw = fields.get("data")
                                    try:
                                        payload = json.loads(raw)
                                    except Exception:
                                        payload = {"raw": raw}
                                    try:
                                        if asyncio.iscoroutinefunction(
                                            self._callbacks[topic]
                                        ):
                                            await self._callbacks[topic](payload)
                                        else:
                                            loop = asyncio.get_running_loop()
                                            await loop.run_in_executor(
                                                None, self._callbacks[topic], payload
                                            )
                                        await self._redis.xack(stream_name, group, _id)
                                        await self._emit_monitor(
                                            {
                                                "topic": topic,
                                                "event": "reclaimed_processed",
                                                "msg_id": _id,
                                                "group": group,
                                                "consumer": consumer,
                                                "timestamp": time.time(),
                                            }
                                        )
                                    except Exception as err2:
                                        logger.exception(
                                            f"[RedisStreamBus] error processing reclaimed {msg_id}: {err2}"
                                        )
                                        # push to DLQ
                                        dlq_stream = f"{stream_name}:dlq"
                                        dlq_payload = {
                                            "failed_message": payload,
                                            "error": str(err2),
                                            "failed_at": time.time(),
                                            "original_id": _id,
                                        }
                                        await self._redis.xadd(
                                            dlq_stream,
                                            {"data": json.dumps(dlq_payload)},
                                            maxlen=self.default_maxlen,
                                            approximate=True,
                                        )
                                        await self._redis.xack(stream_name, group, _id)
                                        await self._emit_monitor(
                                            {
                                                "topic": topic,
                                                "event": "dlq_push",
                                                "msg_id": _id,
                                                "group": group,
                                                "consumer": consumer,
                                                "timestamp": time.time(),
                                            }
                                        )
                    except Exception as e:
                        logger.exception(
                            f"[RedisStreamBus] reclaim entry handling error: {e}"
                        )
                await asyncio.sleep(self.reclaim_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"[RedisStreamBus] reclaim loop error: {e}")
                await asyncio.sleep(self.reclaim_interval)
        logger.info(f"[RedisStreamBus] reclaim loop stopped topic={topic}")

    # ----------------
    # Monitor (console + generator)
    # ----------------
    async def _emit_monitor(self, metric: dict):
        """
        Push monitor events (small or snapshot) into all active monitor queues.
        Updates live counters and broadcasts to dashboard watchers.
        """

        if not hasattr(self, "_monitor_queues"):
            self._monitor_queues = []

        event_type = metric.get("event")
        data = metric.get("data")

        topic = metric.get("topic")
        if topic:
            if not hasattr(self, "_counters"):
                self._counters = {}
            if topic not in self._counters:
                self._counters[topic] = {"processed": 0, "dlq_push": 0, "reclaimed": 0}

            if event_type == "processed":
                self._counters[topic]["processed"] += 1
            elif event_type == "dlq_push":
                self._counters[topic]["dlq_push"] += 1
            elif event_type == "reclaimed_processed":
                self._counters[topic]["reclaimed"] += 1

        # Snapshot events (multi-topic)
        elif event_type == "snapshot" and data and "topics" in data:
            if not hasattr(self, "_counters"):
                self._counters = {}
            for topic_name, topic_data in data["topics"].items():
                if topic_name not in self._counters:
                    self._counters[topic_name] = topic_data.get(
                        "counters", {"processed": 0, "dlq_push": 0, "reclaimed": 0}
                    )

        # Broadcast the metric to all monitor queues
        for q in list(self._monitor_queues):
            try:
                q.put_nowait(metric)
            except Exception:
                pass

    async def _monitor_loop(self, poll_interval: int = 2):
        """
        Periodically poll Redis streams info (not only subscribed topics)
        and push aggregate snapshot to monitor queues.
        """
        logger.info("[RedisStreamBus] monitor loop started")
        counters = getattr(self, "_counters", {})
        try:
            while self._running:
                snapshot = {"timestamp": time.time(), "topics": {}}

                try:
                    all_keys = await self._redis.keys("stream:*")
                    # filter out DLQ streams
                    topics = [
                        k.replace("stream:", "")
                        for k in all_keys
                        if not k.endswith(":dlq")
                    ]
                except Exception as e:
                    logger.error(f"Error listing Redis streams: {e}")
                    topics = []

                # Collect info for each topic
                for topic in topics:
                    stream = f"stream:{topic}"
                    group_info = []
                    pending_total = 0
                    try:
                        group_info = await self._redis.xinfo_groups(stream)
                        for g in group_info:
                            if isinstance(g, dict) and "pending" in g:
                                pending_total += g["pending"]
                    except Exception:
                        pass

                    dlq_len = 0
                    try:
                        dlq_len = await self._redis.xlen(f"{stream}:dlq")
                    except Exception:
                        pass

                    try:
                        length = await self._redis.xlen(stream)
                    except Exception:
                        length = 0

                    if topic not in counters:
                        counters[topic] = {
                            "processed": 0,
                            "dlq_push": 0,
                            "reclaimed": 0,
                        }

                    snapshot["topics"][topic] = {
                        "length": length,
                        "pending": pending_total,
                        "dlq": dlq_len,
                        "groups": group_info,
                        "counters": counters[topic],
                    }

                # Emit snapshot for watchers
                await self._emit_monitor({"event": "snapshot", "data": snapshot})

                await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            pass
        finally:
            logger.info("[RedisStreamBus] monitor loop stopped")

    async def monitor_generator(self) -> AsyncGenerator[dict, None]:
        if not getattr(self, "_running", False):
            self._running = True

        if (
            not hasattr(self, "_monitor_task")
            or self._monitor_task is None
            or self._monitor_task.done()
        ):
            self._monitor_task = asyncio.create_task(
                self._monitor_loop(poll_interval=2)
            )
        else:
            logger.info("[RedisStreamBus] monitor loop already running")

        q = asyncio.Queue()
        self._monitor_queues.append(q)

        try:
            while self._running:
                ev = await q.get()
                yield ev
        finally:
            try:
                self._monitor_queues.remove(q)
            except Exception:
                pass
