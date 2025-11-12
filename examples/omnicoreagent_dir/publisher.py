import asyncio
from omnidaemon import OmniDaemonSDK, EventEnvelope, PayloadBase

sdk = OmniDaemonSDK()

async def publish_docker_monitor_task(sdk: OmniDaemonSDK):
    """
    Publishes a Docker monitoring task to OmniDaemon.
    The task instructs sub-agents to check running containers, resource usage,
    restart policies, and sort by CPU usage.
    """
    task_payload = {
        "task_name": "docker_monitor",
        "description": "Monitor long-running Docker containers and resource usage",
        "criteria": {
            "uptime_hours_gt": 24,
            "memory_mb_gt": 500,
            "restart_policy": "always",
            "max_restarts_last_hour": 3
        },
        "sort_by": "cpu_usage",
        "webhook": "http://localhost:8004/docker_monitor_result",
        "reply_to": "docker.monitor.response",
        "priority": "high",
    }

    topic = "docker.monitor.tasks"
    event_payload = EventEnvelope(
        topic=topic,
        payload=PayloadBase(
            content=task_payload,
            webhook=task_payload.get("webhook"),
            reply_to=task_payload.get("reply_to")
        ),
    )

    await sdk.publish_task(event_envelope=event_payload)
    print(f"Task published to topic '{topic}' with reply_to '{task_payload.get('reply_to')}'.")

if __name__ == "__main__":
    asyncio.run(publish_docker_monitor_task(sdk))
