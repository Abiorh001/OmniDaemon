import asyncio
from src.omnidaemon.sdk import OmniDaemonSDK

# sdk = OmniDaemonSDK()
from redis import asyncio as aioredis
from src.omnidaemon.result_store import RedisResultStore

redis = aioredis.from_url("redis://localhost")
sdk = OmniDaemonSDK(result_store=RedisResultStore(redis))


async def publish_tasks(sdk: OmniDaemonSDK):
    tasks = [
        (
            "document.conversion.tasks",
            {
                "content": "what can you do for me",
                "webhook": "http://localhost:8004/document_conversion_result",
            },
        ),
        (
            "recipe.tasks",
            {
                "content": "what can i cook with rice and apple",
                # "webhook": "http://localhost:8000/document_conversion_result",
            },
        ),
    ]
    for topic, payload in tasks:
        task_id = await sdk.publish_task(topic, payload)
        await asyncio.sleep(5)
        result = await sdk.get_result(task_id)
        print(result)


if __name__ == "__main__":
    asyncio.run(publish_tasks(sdk=sdk))
