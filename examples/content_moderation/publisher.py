import argparse
import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from omnidaemon import EventEnvelope, OmniDaemonSDK, PayloadBase

from ingest import publish_ingested_file
from schema import ModerationEvent
from state import STATE_DIR, load_directory_snapshot, save_directory_snapshot

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    WATCHDOG_AVAILABLE = False

MODERATION_TOPIC = "content_moderation.tasks"
DEFAULT_REPLY_TOPIC = "content_moderation.review"

sdk = OmniDaemonSDK()

STATE_DIR.mkdir(parents=True, exist_ok=True)


class ModerationFileCache:
    """Tracks recently published files to avoid duplicate publications within a short window."""

    def __init__(self, dedup_window_seconds: float = 2.0) -> None:
        self._cache: Dict[
            str, Tuple[float, int, float]
        ] = {}  # path -> (mtime, size, last_published)
        self.dedup_window = dedup_window_seconds

    def should_publish(self, path: Path) -> bool:
        try:
            stat = path.stat()
        except OSError:
            logger.warning("Cannot stat file %s, skipping", path)
            return False

        key = str(path.resolve())
        fingerprint = (stat.st_mtime, stat.st_size)
        now = time.time()

        cached = self._cache.get(key)
        if cached:
            cached_fingerprint = (cached[0], cached[1])
            last_published = cached[2]

            # If fingerprint matches and we published recently, skip
            if (
                cached_fingerprint == fingerprint
                and (now - last_published) < self.dedup_window
            ):
                logger.debug(
                    "Skipping %s (published %.1fs ago)", path.name, now - last_published
                )
                return False

            # If fingerprint changed, it's a new version
            if cached_fingerprint != fingerprint:
                logger.info(
                    "File %s changed (mtime or size), will republish", path.name
                )

        # Update cache and allow publication
        self._cache[key] = (*fingerprint, now)
        return True


_file_cache = ModerationFileCache(dedup_window_seconds=2.0)


def snapshot_directory(directory: Path) -> Dict[str, Dict[str, str]]:
    snapshot: Dict[str, Dict[str, str]] = {}
    for root, _, files in os.walk(directory):
        for filename in files:
            path = Path(root) / filename
            try:
                stats = path.stat()
            except OSError:
                continue
            snapshot[str(path.resolve())] = {
                "mtime": str(stats.st_mtime),
                "size": str(stats.st_size),
            }
    return snapshot


def diff_snapshots(
    old: Dict[str, Dict[str, str]],
    new: Dict[str, Dict[str, str]],
) -> Tuple[List[Path], List[Path]]:
    new_files: List[Path] = []
    modified_files: List[Path] = []

    for path_str, meta in new.items():
        if path_str not in old:
            new_files.append(Path(path_str))
        elif (
            old[path_str]["mtime"] != meta["mtime"]
            or old[path_str]["size"] != meta["size"]
        ):
            modified_files.append(Path(path_str))

    return new_files, modified_files


async def publish_event(payload: dict, reply_to: Optional[str]) -> None:
    try:
        event = ModerationEvent.from_raw(payload)
        envelope = EventEnvelope(
            topic=MODERATION_TOPIC,
            payload=PayloadBase(
                content=json.dumps(event.to_payload()),
                reply_to=reply_to,
            ),
            source="content-moderation-cli",
        )
        await sdk.publish_task(envelope)
        logger.info(
            "Published moderation event for task=%s ingested_path=%s",
            event.task,
            event.ingested_path,
        )
    except Exception as exc:
        logger.exception("Failed to publish moderation event: %s", exc)
        raise


async def publish_cycle(
    directories: Iterable[Path],
    reply_topic: Optional[str],
    metadata: Optional[dict],
    mode: str = "cycle",
) -> None:
    event = ModerationEvent(
        task="report" if mode == "report" else "cycle",
        directories=[str(path.resolve()) for path in directories] or None,
        requested_by=os.getenv("USER", "unknown"),
        metadata=metadata,
    )
    await publish_event(event.to_payload(), reply_topic)


async def process_file(
    path: Path, reply_topic: Optional[str], metadata: Optional[dict]
) -> None:
    """Process a single file: check cache, ingest, and publish moderation event."""
    if not path.exists():
        logger.warning("File no longer exists: %s", path)
        return

    if not _file_cache.should_publish(path):
        logger.debug("Skipping %s (recently published or unchanged)", path.name)
        return

    try:
        destination = await publish_ingested_file(
            path, metadata=metadata, reply_topic=reply_topic
        )
        logger.info(
            "✅ Published moderation event for %s (ingested to %s)",
            path.name,
            destination,
        )
    except Exception as exc:
        logger.exception("❌ Failed to process file %s: %s", path, exc)


async def manual_scan(
    directories: Iterable[Path],
    reply_topic: Optional[str],
    metadata: Optional[dict],
) -> None:
    """Scan directories once and publish events for new/modified files."""
    for directory in directories:
        directory = directory.resolve()
        if not directory.exists():
            logger.warning("Directory does not exist: %s", directory)
            continue

        logger.info("Scanning directory: %s", directory)
        snapshot_old = load_directory_snapshot(directory)
        snapshot_new = snapshot_directory(directory)
        new_files, modified_files = diff_snapshots(snapshot_old, snapshot_new)

        total = len(new_files) + len(modified_files)
        if total > 0:
            logger.info(
                "Found %d new files, %d modified files in %s",
                len(new_files),
                len(modified_files),
                directory,
            )

        for file_path in new_files + modified_files:
            await process_file(file_path, reply_topic, metadata)

        save_directory_snapshot(directory, snapshot_new)


class WatchdogHandler(FileSystemEventHandler):  # pragma: no cover - requires watchdog
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        reply_topic: Optional[str],
        metadata: Optional[dict],
    ) -> None:
        super().__init__()
        self.loop = loop
        self.reply_topic = reply_topic
        self.metadata = metadata
        self._processing = set()  # Track files currently being processed

    def _schedule_file_processing(self, file_path: Path) -> None:
        """Schedule file processing with deduplication."""
        key = str(file_path.resolve())
        if key in self._processing:
            logger.debug("File %s already being processed, skipping", file_path.name)
            return

        self._processing.add(key)
        future = asyncio.run_coroutine_threadsafe(
            self._process_with_cleanup(file_path),
            self.loop,
        )

        def cleanup(_):
            self._processing.discard(key)

        future.add_done_callback(cleanup)

    async def _process_with_cleanup(self, file_path: Path) -> None:
        """Process file and handle errors."""
        try:
            # Small delay to ensure file is fully written
            await asyncio.sleep(0.1)
            await process_file(file_path, self.reply_topic, self.metadata)
        except Exception as exc:
            logger.exception(
                "Error processing file %s in watchdog handler: %s", file_path, exc
            )

    def on_created(self, event):
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        logger.info("📁 Watchdog detected new file: %s", file_path.name)
        self._schedule_file_processing(file_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        file_path = Path(event.src_path)
        logger.info("📝 Watchdog detected modified file: %s", file_path.name)
        self._schedule_file_processing(file_path)


async def watch_directories_watchdog(
    directories: Iterable[Path],
    reply_topic: Optional[str],
    metadata: Optional[dict],
) -> None:
    """Watch directories using native filesystem events (watchdog)."""
    if not WATCHDOG_AVAILABLE:
        raise RuntimeError("watchdog is not installed; install it or omit --watchdog")

    directories = [path.resolve() for path in directories]
    for directory in directories:
        if not directory.exists():
            raise SystemExit(f"Directory does not exist: {directory}")

    # Do initial scan to catch files created before watcher started
    logger.info("Performing initial scan of directories...")
    await manual_scan(directories, reply_topic, metadata)
    logger.info("Initial scan complete. Starting watchdog monitoring...")

    observer = Observer()
    loop = asyncio.get_event_loop()
    handler = WatchdogHandler(loop, reply_topic, metadata)
    for directory in directories:
        observer.schedule(handler, str(directory), recursive=True)
        logger.info("Watching directory: %s", directory)

    observer.start()
    logger.info(
        "✅ Watchdog watcher running for: %s", ", ".join(str(d) for d in directories)
    )
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down watchdog watcher...")
    finally:
        observer.stop()
        observer.join(timeout=5)
        logger.info("Watchdog watcher stopped")


async def watch_directories_polling(
    directories: Iterable[Path],
    reply_topic: Optional[str],
    metadata: Optional[dict],
    interval: float,
) -> None:
    """Watch directories using polling (fallback when watchdog unavailable)."""
    directories = [path.resolve() for path in directories]
    for directory in directories:
        if not directory.exists():
            raise SystemExit(f"Directory does not exist: {directory}")

    logger.info(
        "Polling watcher running for: %s (interval=%.1fs)",
        ", ".join(str(d) for d in directories),
        interval,
    )
    while True:
        await manual_scan(directories, reply_topic, metadata)
        await asyncio.sleep(interval)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Trigger content moderation tasks or watch for changes"
    )
    parser.add_argument(
        "--directories",
        nargs="*",
        type=Path,
        help="Directories to monitor (defaults to configured directories)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Analyze a single file immediately",
    )
    parser.add_argument(
        "--task",
        choices=["cycle", "single_file", "report"],
        default="cycle",
        help="Type of moderation task to trigger",
    )
    parser.add_argument(
        "--reply-topic",
        type=str,
        default=DEFAULT_REPLY_TOPIC,
        help="Topic to receive moderation results (blank to disable)",
    )
    parser.add_argument(
        "--metadata",
        type=str,
        help="Additional metadata as JSON string",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously watch directories for new/modified files",
    )
    parser.add_argument(
        "--watchdog",
        action="store_true",
        help="Use watchdog (native filesystem events) instead of polling",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Polling interval when watching without watchdog (seconds)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    directories = args.directories or []
    metadata = json.loads(args.metadata) if args.metadata else None
    reply_topic = args.reply_topic or None

    if args.task == "single_file":
        if not args.file:
            raise SystemExit("--file is required for single_file task")
        await process_file(args.file, reply_topic, metadata)
        return

    if args.task == "report":
        await publish_cycle(directories, reply_topic, metadata, mode="report")
        return

    # task == cycle
    if args.watch:
        if not directories:
            raise SystemExit("--directories is required when using --watch")
        if args.watchdog:
            await watch_directories_watchdog(directories, reply_topic, metadata)
        else:
            await watch_directories_polling(
                directories, reply_topic, metadata, args.interval
            )
    else:
        if directories:
            await manual_scan(directories, reply_topic, metadata)
        else:
            await publish_cycle([], reply_topic, metadata)


if __name__ == "__main__":
    asyncio.run(main())
