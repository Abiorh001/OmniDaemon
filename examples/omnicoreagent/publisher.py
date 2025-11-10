import asyncio
from omnidaemon import OmniDaemonSDK, EventEnvelope, PayloadBase


sdk = OmniDaemonSDK()


async def publish_tasks(sdk: OmniDaemonSDK):
    payload = {
        "content": """
                Show me all Docker containers that have been running for more than 24 hours,
their memory usage above 500MB, and sort them by CPU usage. Also check if
any of them have restart policies set to 'always' but have restarted more
than 3 times in the last hour.

""",
        "webhook": "http://localhost:8004/document_conversion_result",
    }
    topic = "file_system.tasks"
    event_payload = EventEnvelope(
        topic=topic,
        payload=PayloadBase(
            content=payload["content"],
            webhook=payload.get("webhook"),
        ),
    )
    await sdk.publish_task(event_envelope=event_payload)


if __name__ == "__main__":
    asyncio.run(publish_tasks(sdk=sdk))
