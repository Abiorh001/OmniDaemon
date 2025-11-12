import asyncio
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional


from omnidaemon import EventEnvelope, OmniDaemonSDK, PayloadBase

from schema import ModerationEvent
from state import INGEST_ROOT

MODERATION_TOPIC = "content_moderation.tasks"
DEFAULT_REPLY_TOPIC = "content_moderation.review"

sdk = OmniDaemonSDK()


def ingest_file(source_path: Path) -> Path:
    """Copy the source file into the managed ingest workspace."""
    source_path = source_path.expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"File not found: {source_path}")

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    relative_name = f"{timestamp}_{source_path.name}"
    destination = INGEST_ROOT / relative_name
    destination.parent.mkdir(parents=True, exist_ok=True)

    shutil.copy2(source_path, destination)
    return destination


def build_event_payload(
    ingested_path: Path,
    original_path: Path,
    metadata: Optional[Dict] = None,
    task: str = "single_file",
) -> ModerationEvent:
    return ModerationEvent(
        task=task,
        ingested_path=str(ingested_path),
        original_path=str(original_path),
        ingest_timestamp=datetime.utcnow().isoformat() + "Z",
        requested_by=os.getenv("USER", "unknown"),
        metadata=metadata,
    )


async def publish_ingested_file(
    source_path: Path,
    metadata: Optional[Dict] = None,
    reply_topic: Optional[str] = DEFAULT_REPLY_TOPIC,
) -> str:
    ingested_path = ingest_file(source_path)
    event = build_event_payload(ingested_path, source_path, metadata)

    envelope = EventEnvelope(
        topic=MODERATION_TOPIC,
        payload=PayloadBase(
            content=json.dumps(event.to_payload()),
            reply_to=reply_topic,
        ),
        source="content-moderation-ingestor",
    )
    await sdk.publish_task(envelope)
    return str(ingested_path)


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Ingest a single file and trigger moderation"
    )
    parser.add_argument("file", type=Path, help="Path to the file to ingest")
    parser.add_argument("--metadata", type=str, help="Optional JSON metadata")
    parser.add_argument(
        "--reply-topic",
        type=str,
        default=DEFAULT_REPLY_TOPIC,
        help="Topic for moderation replies (blank to disable)",
    )
    args = parser.parse_args()

    metadata = json.loads(args.metadata) if args.metadata else None
    reply_topic = args.reply_topic or None

    destination = await publish_ingested_file(
        args.file, metadata=metadata, reply_topic=reply_topic
    )
    print(f"Ingested {args.file} to {destination} and published moderation event")


if __name__ == "__main__":
    asyncio.run(main())
