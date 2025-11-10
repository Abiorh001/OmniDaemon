import asyncio
import json
import logging
import time
from typing import Optional, Callable, Dict, Any
from redis import asyncio as aioredis
from decouple import config

logger = logging.getLogger("redis_stream_bus")
logger.setLevel(logging.INFO)


class RedisStreamEventBus:
    """
    Redis Streams Event Bus implementation for production use.

    This implementation uses Redis Streams to provide durable, reliable messaging
    with advanced features for production deployments.

    Features:
        - Durable messaging: Messages are persisted in Redis Streams
        - Consumer groups: Support for load balancing and fault tolerance
        - Message reclaiming: Automatic retry of stuck messages
        - Dead-letter queues (DLQ): Failed messages after max retries
        - Monitoring: Emits metrics to a dedicated Redis stream
        - Auto-reconnection: Handles connection failures gracefully

    Args:
        redis_url: Redis connection URL (default: from REDIS_URL env var)
        default_maxlen: Maximum number of messages to keep in streams (default: 10,000)
        reclaim_interval: Seconds between reclaim attempts (default: 30)
        default_reclaim_idle_ms: Milliseconds before a pending message is reclaimed (default: 180,000)
        default_dlq_retry_limit: Maximum retry attempts before sending to DLQ (default: 3)

    Attributes:
        redis_url: Redis connection URL
        default_maxlen: Default maximum stream length
        reclaim_interval: Reclaim loop interval in seconds
        default_reclaim_idle_ms: Default idle time before reclaim
        default_dlq_retry_limit: Default DLQ retry limit
        _redis: Redis client instance
        _connect_lock: Lock for connection operations
        _consumers: Dictionary of active consumer groups
        _in_flight: Dictionary tracking messages currently being processed
        _running: Whether the event bus is active
    """

    def __init__(
        self,
        redis_url: str = config("REDIS_URL"),
        default_maxlen: int = 10_000,
        reclaim_interval: int = 30,
        default_reclaim_idle_ms: int = 180_000,
        default_dlq_retry_limit: int = 3,
    ) -> None:
        self.redis_url = redis_url
        self.default_maxlen = default_maxlen
        self.reclaim_interval = reclaim_interval
        self.default_reclaim_idle_ms = default_reclaim_idle_ms
        self.default_dlq_retry_limit = default_dlq_retry_limit

        self._redis: Optional[aioredis.Redis] = None
        self._connect_lock = asyncio.Lock()

        self._consumers: Dict[str, Dict[str, Any]] = {}
        self._in_flight: Dict[str, set] = {}
        self._running = False

    async def connect(self) -> None:
        """
        Establish connection to Redis.

        This method creates a Redis client connection. It is idempotent and thread-safe
        using a connection lock.

        Raises:
            ConnectionError: If Redis connection fails
        """
        async with self._connect_lock:
            if self._redis:
                return
            self._redis = aioredis.from_url(self.redis_url, decode_responses=True)
            logger.info(f"[RedisStreamBus] connected: {self.redis_url}")

    async def close(self) -> None:
        """
        Close Redis connection and stop all consumers.

        This method gracefully shuts down the event bus by:
        1. Setting _running to False to stop all loops
        2. Cancelling all consume and reclaim tasks
        3. Closing the Redis connection

        Note:
            This method is idempotent and safe to call multiple times.
        """
        self._running = False
        for meta in list(self._consumers.values()):
            consume_tasks = meta.get("consume_tasks", [])
            reclaim_tasks = meta.get("reclaim_tasks", [])
            for task in consume_tasks:
                task.cancel()
            for task in reclaim_tasks:
                task.cancel()

        if self._redis:
            await self._redis.close()
            self._redis = None
        logger.info("[RedisStreamBus] closed")

    async def publish(
        self, event_payload: Dict[str, Any], maxlen: Optional[int] = None
    ) -> str:
        """
        Publish an event message to a Redis stream.

        This method publishes a message to the stream named `omni-stream:{topic}`.
        The stream length is automatically managed using the maxlen parameter.

        Args:
            event_payload: Dictionary containing event data. Must include:
                - topic: The topic name to publish to
                - id: Optional task ID
                - payload: Dictionary with content, webhook, reply_to, etc.
                - correlation_id: Optional correlation ID
                - causation_id: Optional causation ID
                - source: Optional source identifier
                - delivery_attempts: Optional delivery attempt counter
            maxlen: Maximum stream length (default: self.default_maxlen)

        Returns:
            The task ID from event_payload (or "N/A" if not provided)

        Raises:
            ValueError: If event_payload is missing the 'topic' field
            ConnectionError: If Redis is not connected
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        topic = event_payload.get("topic")
        if not topic:
            raise ValueError("Event payload must include 'topic' field")
        data = {
            "content": event_payload.get("payload", {}).get("content"),
            "webhook": event_payload.get("payload", {}).get("webhook"),
            "reply_to": event_payload.get("payload", {}).get("reply_to"),
            "topic": topic,
            "task_id": event_payload.get("id"),
            "correlation_id": event_payload.get("correlation_id"),
            "causation_id": event_payload.get("causation_id"),
            "source": event_payload.get("source"),
            "delivery_attempts": event_payload.get("delivery_attempts", 0),
            "created_at": event_payload.get("created_at", time.time()),
        }
        stream_name = f"omni-stream:{topic}"
        payload = json.dumps(data, default=str)
        maxlen = maxlen or self.default_maxlen
        msg_id = await self._redis.xadd(
            stream_name, {"data": payload}, maxlen=maxlen, approximate=True
        )
        logger.debug(f"[RedisStreamBus] published {stream_name} id={msg_id}")
        return event_payload.get("id", "N/A")

    async def subscribe(
        self,
        topic: str,
        agent_name: str,
        callback: Callable[[Dict[str, Any]], Any],
        group_name: Optional[str] = None,
        consumer_name: Optional[str] = None,
        config: Dict[str, Any] = {},
    ) -> None:
        """
        Subscribe an agent callback to a topic using Redis consumer groups.

        This method creates a consumer group (if it doesn't exist) and starts
        consuming messages from the specified topic. It supports multiple concurrent
        consumers for load balancing and automatic message reclaiming for fault tolerance.

        Args:
            topic: The topic name to subscribe to
            agent_name: Unique identifier for the agent/consumer
            callback: Callable function to process messages. Can be async or sync.
            group_name: Optional custom consumer group name. If not provided,
                       defaults to `group:{topic}:{agent_name}`
            consumer_name: Optional custom consumer name. If not provided,
                          defaults to `consumer:{agent_name}`
            config: Optional configuration dictionary:
                - consumer_count: Number of concurrent consumers (default: 1)
                - reclaim_idle_ms: Milliseconds before reclaiming pending messages
                - dlq_retry_limit: Maximum retries before sending to DLQ

        Note:
            Each consumer runs in its own asyncio task. The reclaim loop also runs
            in a separate task to handle stuck messages.

        Raises:
            ConnectionError: If Redis is not connected
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        reclaim_idle_ms = config.get("reclaim_idle_ms")
        dlq_retry_limit = config.get("dlq_retry_limit")
        consumer_count = int(config.get("consumer_count", 1))
        effective_reclaim_idle_ms = reclaim_idle_ms or self.default_reclaim_idle_ms
        effective_dlq_retry_limit = dlq_retry_limit or self.default_dlq_retry_limit
        stream_name = f"omni-stream:{topic}"

        group = group_name or (f"group:{topic}:{agent_name}")
        consumer = consumer_name or f"consumer:{agent_name}"
        dlq_stream = f"omni-dlq:{group}"

        try:
            await self._redis.xgroup_create(stream_name, group, id="$", mkstream=True)
            logger.info(f"[RedisStreamBus] created group {group} for {stream_name}")
        except aioredis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(f"[RedisStreamBus] group {group} exists")
            else:
                raise

        self._running = True
        consume_tasks = []
        reclaim_tasks = []
        for i in range(consumer_count):
            consumer_name = f"{consumer}-{i + 1}"
            consume_task = asyncio.create_task(
                self._consume_loop(
                    stream_name=stream_name,
                    topic=topic,
                    group=group,
                    consumer=consumer_name,
                    callback=callback,
                )
            )
            reclaim_task = asyncio.create_task(
                self._reclaim_loop(
                    stream_name=stream_name,
                    topic=topic,
                    group=group,
                    consumer=consumer_name,
                    callback=callback,
                    reclaim_idle_ms=effective_reclaim_idle_ms,
                    dlq_retry_limit=effective_dlq_retry_limit,
                )
            )
            consume_tasks.append(consume_task)
            reclaim_tasks.append(reclaim_task)
        self._consumers[group] = {
            "topic": topic,
            "agent_name": agent_name,
            "stream": stream_name,
            "callback": callback,
            "group": group,
            "dlq": dlq_stream,
            "config": {
                "reclaim_idle_ms": effective_reclaim_idle_ms,
                "dlq_retry_limit": effective_dlq_retry_limit,
                "consumer_count": consumer_count,
            },
            "consume_tasks": consume_tasks,
            "reclaim_tasks": reclaim_tasks,
        }

        logger.info(
            f"[RedisStreamBus] subscribed topic={topic} group={group} consumers={consumer_count}"
        )

    async def _consume_loop(
        self,
        stream_name: str,
        topic: str,
        group: str,
        consumer: str,
        callback: Callable[[Dict[str, Any]], Any],
    ) -> None:
        """
        Main consumption loop for a consumer in a consumer group.

        This method continuously reads messages from the Redis stream using XREADGROUP,
        processes them through the callback, and acknowledges successful processing.
        Failed messages remain in the pending entries list for the reclaim loop to handle.

        Args:
            stream_name: The Redis stream name (e.g., "omni-stream:topic")
            topic: The logical topic name
            group: The consumer group name
            consumer: The consumer name within the group
            callback: The callback function to process messages

        Note:
            - Messages are read in batches of up to 10
            - Blocking read with 5-second timeout
            - Supports both async and sync callbacks
            - Automatically handles connection failures
        """
        logger.info(
            f"[RedisStreamBus] consumer loop start topic={topic} group={group} consumer={consumer}"
        )
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

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
                            if group not in self._in_flight:
                                self._in_flight[group] = set()
                            self._in_flight[group].add(msg_id)
                            try:
                                payload["processing_consumer"] = consumer
                                if asyncio.iscoroutinefunction(callback):
                                    await callback(payload)
                                else:
                                    loop = asyncio.get_running_loop()
                                    await loop.run_in_executor(None, callback, payload)
                                await self._redis.xack(stream_name, group, msg_id)
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
                            finally:
                                self._in_flight[group].discard(msg_id)

                except asyncio.CancelledError:
                    logger.info(
                        f"[RedisStreamBus] consume loop cancelled topic={topic}"
                    )
                    break
                except Exception as err:
                    err_msg = str(err).lower()
                    if "connection closed" in err_msg or "connection reset" in err_msg:
                        logger.info(
                            f"[RedisStreamBus] connection closed for topic={topic}, stopping loop"
                        )
                        break

                    logger.exception(
                        f"[RedisStreamBus] error in consume loop topic={topic}: {err}"
                    )
                    await asyncio.sleep(1)
        finally:
            logger.info(f"[RedisStreamBus] consumer loop stopped topic={topic}")

    async def _reclaim_loop(
        self,
        stream_name: str,
        topic: str,
        group: str,
        consumer: str,
        callback: Callable[[Dict[str, Any]], Any],
        reclaim_idle_ms: Optional[int] = None,
        dlq_retry_limit: Optional[int] = None,
    ) -> None:
        """
        Reclaim loop for handling stuck/pending messages.

        This method periodically checks for pending messages that have been idle
        for longer than reclaim_idle_ms. It attempts to reprocess them, and if
        they exceed the retry limit, sends them to the dead-letter queue.

        Args:
            stream_name: The Redis stream name
            topic: The logical topic name
            group: The consumer group name
            consumer: The consumer name handling reclaims
            callback: The callback function to retry processing
            reclaim_idle_ms: Milliseconds before a message is considered stuck
            dlq_retry_limit: Maximum retry attempts before sending to DLQ

        Note:
            - Runs every reclaim_interval seconds
            - Checks up to 50 pending messages per iteration
            - Tracks retry counts in Redis hash
            - Automatically handles connection failures
        """
        logger.info(f"[RedisStreamBus] reclaim loop start topic={topic} group={group}")
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        retry_key = f"retry_counts:{group}"
        reclaim_idle_ms = reclaim_idle_ms or self.default_reclaim_idle_ms
        dlq_retry_limit = dlq_retry_limit or self.default_dlq_retry_limit

        while self._running:
            try:
                pending = []
                try:
                    pending = await self._redis.xpending_range(
                        stream_name, group, "-", "+", count=50
                    )
                except Exception:
                    logger.debug(
                        f"[RedisStreamBus] xpending_range unavailable for {group}, skipping reclaim"
                    )
                    await asyncio.sleep(self.reclaim_interval)
                    continue

                for entry in pending:
                    try:
                        if isinstance(entry, dict):
                            msg_id = entry.get("message_id") or entry.get("id")
                            idle = entry.get("time_since_delivered", 0)
                        elif isinstance(entry, (tuple, list)):
                            msg_id = entry[0]
                            idle = int(entry[2]) if len(entry) > 2 else 0
                        else:
                            continue

                        if not msg_id or idle < reclaim_idle_ms:
                            continue
                        if (
                            group in self._in_flight
                            and msg_id in self._in_flight[group]
                        ):
                            logger.info(
                                f"[RedisStreamBus] Skipping reclaim of {msg_id}: still in-flight"
                            )
                            continue
                        logger.info(
                            f"consumer group {group} reclaiming message id {msg_id} meant for topic {topic}"
                        )

                        claimed = await self._redis.xclaim(
                            stream_name,
                            group,
                            consumer,
                            min_idle_time=reclaim_idle_ms,
                            message_ids=[msg_id],
                        )

                        if not claimed:
                            continue

                        logger.info(
                            f"[RedisStreamBus] reclaimed {msg_id} (idle={idle}ms) for group {group}"
                        )
                        await self._emit_monitor(
                            {
                                "topic": topic,
                                "event": "reclaim_attempt",
                                "msg_id": msg_id,
                                "group": group,
                                "consumer": consumer,
                                "timestamp": time.time(),
                            }
                        )

                        for msg in claimed:
                            _id = msg[0]
                            fields = msg[1]
                            raw = fields.get("data")
                            try:
                                payload = json.loads(raw) if raw else {"raw": raw}
                            except Exception:
                                payload = {"raw": raw}

                            retry_count = await self._redis.hincrby(retry_key, _id, 1)  # type: ignore[misc]
                            await self._redis.expire(retry_key, 3600)  # type: ignore[misc]
                            retry_count = int(retry_count)

                            if retry_count > dlq_retry_limit:
                                logger.error(
                                    f"[RedisStreamBus] Max delivery attempts ({1 + dlq_retry_limit}) exceeded for {_id} after {dlq_retry_limit} retries. Sending to DLQ."
                                )
                                retry_count -= 1
                                payload["delivery_attempts"] += retry_count
                                await self._send_to_dlq(
                                    group,
                                    stream_name,
                                    _id,
                                    payload,
                                    error=f"Max retries ({1 + dlq_retry_limit}) exceeded",
                                    retry_count=retry_count,
                                )
                                await self._redis.xack(stream_name, group, _id)  # type: ignore[misc]
                                await self._redis.hdel(retry_key, _id)  # type: ignore[misc]
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
                            else:
                                try:
                                    logger.info(
                                        f"[RedisStreamBus] Retry #{retry_count} for {_id} in group {group}"
                                    )
                                    payload["delivery_attempts"] += retry_count
                                    payload["processing_consumer"] = consumer
                                    if asyncio.iscoroutinefunction(callback):
                                        await callback(payload)
                                    else:
                                        loop = asyncio.get_running_loop()
                                        await loop.run_in_executor(
                                            None, callback, payload
                                        )
                                    await self._redis.xack(stream_name, group, _id)  # type: ignore[misc]
                                    await self._redis.hdel(retry_key, _id)  # type: ignore[misc]
                                    await self._emit_monitor(
                                        {
                                            "topic": topic,
                                            "event": "reclaimed",
                                            "msg_id": _id,
                                            "group": group,
                                            "consumer": consumer,
                                            "timestamp": time.time(),
                                        }
                                    )
                                except Exception as err2:
                                    logger.exception(
                                        f"[RedisStreamBus] Retry #{retry_count} failed for {_id}: {err2}"
                                    )

                    except Exception as e:
                        logger.exception(
                            f"[RedisStreamBus] reclaim entry handling error: {e}"
                        )

                await asyncio.sleep(self.reclaim_interval)

            except asyncio.CancelledError:
                logger.info(f"[RedisStreamBus] reclaim loop cancelled topic={topic}")
                break
            except Exception as e:
                err_msg = str(e).lower()
                if "connection closed" in err_msg or "connection reset" in err_msg:
                    logger.info(
                        f"[RedisStreamBus] connection closed in reclaim loop topic={topic}, stopping"
                    )
                    break

                logger.exception(f"[RedisStreamBus] reclaim loop error: {e}")
                await asyncio.sleep(self.reclaim_interval)

        logger.info(f"[RedisStreamBus] reclaim loop stopped topic={topic}")

    async def _send_to_dlq(
        self,
        group: str,
        stream_name: str,
        msg_id: str,
        payload: Dict[str, Any],
        error: str,
        retry_count: int,
    ) -> None:
        """
        Send a failed message to the dead-letter queue.

        This method publishes a message to the per-group DLQ stream with metadata
        about the failure, including the original message, error, and retry count.

        Args:
            group: The consumer group name
            stream_name: The original stream name
            msg_id: The message ID that failed
            payload: The original message payload
            error: Error message describing the failure
            retry_count: Number of retry attempts made

        Note:
            DLQ stream name format: `omni-dlq:{group}`
            DLQ messages include original message, error details, and timestamps.
        """
        if not self._redis:
            logger.error("[RedisStreamBus] Cannot send to DLQ: Redis not connected")
            return

        dlq_stream = f"omni-dlq:{group}"
        dlq_payload = {
            "topic": stream_name.replace("omni-stream:", ""),
            "original_stream": stream_name,
            "original_id": msg_id,
            "failed_message": payload,
            "error": error,
            "retry_count": retry_count,
            "failed_at": time.time(),
        }
        try:
            await self._redis.xadd(
                dlq_stream,
                {"data": json.dumps(dlq_payload, default=str)},
                maxlen=self.default_maxlen,
                approximate=True,
            )
            logger.info(f"[RedisStreamBus] Sent {msg_id} to DLQ: {dlq_stream}")
        except Exception as e:
            logger.critical(
                f"[RedisStreamBus] FAILED to write to DLQ {dlq_stream}: {e}"
            )

    async def _emit_monitor(self, metric: Dict[str, Any]) -> None:
        """
        Emit a monitoring metric to the Redis metrics stream.

        This method publishes metrics to the `omni-metrics` stream, which serves
        as the single source of truth for all event bus events (processed, reclaimed,
        DLQ pushes, etc.).

        Args:
            metric: Dictionary containing metric data:
                - topic: The topic name
                - event: Event type (e.g., "processed", "reclaim_attempt", "dlq_push")
                - msg_id: The message ID
                - group: The consumer group name
                - consumer: The consumer name
                - timestamp: Event timestamp

        Note:
            Metrics stream has a maximum length of 1,000,000 entries.
            Failures to emit metrics are logged but don't raise exceptions.
        """
        if not self._redis:
            return  # Silently fail if not connected
        try:
            await self._redis.xadd(
                "omni-metrics",
                {"data": json.dumps(metric, default=str)},
                maxlen=1_000_000,
                approximate=True,
            )
        except Exception as e:
            logger.error(f"[RedisStreamBus] Failed to emit metric: {e}")

    async def unsubscribe(
        self,
        topic: str,
        agent_name: str,
        delete_group: bool = False,
        delete_dlq: bool = False,
    ) -> None:
        """
        Unsubscribe an agent from a topic by stopping its consumer group.

        This method stops message consumption for the specified agent by cancelling
        all consume and reclaim tasks. Optionally, it can permanently delete the
        consumer group and dead-letter queue.

        Args:
            topic: The topic name to unsubscribe from
            agent_name: The agent/consumer identifier
            delete_group: If True, permanently delete the consumer group from Redis
            delete_dlq: If True, permanently delete the associated dead-letter queue

        Note:
            - If delete_group is False, the group remains and can be resumed
            - If delete_dlq is False, failed messages remain in the DLQ for inspection
            - This method is idempotent - safe to call multiple times
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        group_name = f"group:{topic}:{agent_name}"

        stream_name = f"omni-stream:{topic}"
        dlq_name = f"omni-dlq:{group_name}"

        meta = self._consumers.get(group_name)
        if not meta:
            return

        for task in meta["consume_tasks"]:
            task.cancel()
        for task in meta["reclaim_tasks"]:
            task.cancel()

        del self._consumers[group_name]

        logger.info(f"[RedisStreamBus] Stopped consumption for {group_name}")

        if delete_group:
            try:
                await self._redis.xgroup_destroy(stream_name, group_name)
                logger.info(f"[RedisStreamBus] Deleted consumer group {group_name}")
            except Exception as e:
                if "NOGROUP" not in str(e):
                    logger.error(f"Failed to delete group: {e}")

        if delete_dlq:
            try:
                await self._redis.delete(dlq_name)
                logger.info(f"[RedisStreamBus] Deleted DLQ {dlq_name}")
            except Exception as e:
                logger.warning(f"Failed to delete DLQ: {e}")
        else:
            logger.info(f"[RedisStreamBus] DLQ preserved at {dlq_name}")

    async def get_consumers(self) -> Dict[str, Dict[str, Any]]:
        """
        Return current consumers and their configurations.

        This method queries Redis directly for actual consumer groups, making it
        work even from new instances (like CLI tools) that don't have the in-memory
        _consumers dictionary populated.

        Returns:
            Dictionary mapping consumer group names to their metadata:
                - topic: The subscribed topic
                - stream: The Redis stream name
                - consumers_count: Number of active consumers in the group
                - pending_messages: Number of unprocessed messages
                - source: Either "memory" (from _consumers) or "redis_query"

        Note:
            If _consumers is populated, it returns that data. Otherwise, it discovers
            consumer groups by scanning Redis streams matching "omni-stream:*".
        """
        if not self._redis:
            await self.connect()
        assert self._redis is not None  # Type narrowing after connect

        if self._consumers:
            return self._consumers

        discovered_consumers = {}

        try:
            stream_pattern = "omni-stream:*"
            cursor = 0
            stream_keys = []

            while True:
                cursor, keys = await self._redis.scan(
                    cursor, match=stream_pattern, count=100
                )
                stream_keys.extend(
                    [k.decode() if isinstance(k, bytes) else k for k in keys]
                )
                if cursor == 0:
                    break

            for stream_key in stream_keys:
                try:
                    topic = stream_key.replace("omni-stream:", "")
                    groups_info = await self._redis.xinfo_groups(stream_key)

                    for group_info in groups_info:
                        group_name = (
                            group_info.get(b"name", b"").decode()
                            if isinstance(group_info.get(b"name"), bytes)
                            else group_info.get("name", "")
                        )
                        consumers_count = (
                            group_info.get(b"consumers", 0)
                            if isinstance(group_info.get(b"consumers"), bytes)
                            else group_info.get("consumers", 0)
                        )
                        pending = (
                            group_info.get(b"pending", 0)
                            if isinstance(group_info.get(b"pending"), bytes)
                            else group_info.get("pending", 0)
                        )

                        if group_name:
                            discovered_consumers[group_name] = {
                                "topic": topic,
                                "stream": stream_key,
                                "consumers_count": consumers_count,
                                "pending_messages": pending,
                                "source": "redis_query",
                            }
                except Exception as e:
                    logger.debug(f"Failed to get consumer groups for {stream_key}: {e}")
                    continue

        except Exception as e:
            logger.warning(f"Failed to discover consumers from Redis: {e}")

        return discovered_consumers
