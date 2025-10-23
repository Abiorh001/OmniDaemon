import asyncio
from omnidaemon.sdk import OmniDaemonSDK
from omnidaemon.result_store import RedisResultStore
from decouple import config

sdk = OmniDaemonSDK(
    result_store=RedisResultStore(
        redi_url=config("REDIS_URL", default="redis://localhost")
    )
)


async def publish_tasks(sdk: OmniDaemonSDK):
    payload = {
        "content": """
                **1. Create a Directory:** I will create a directory named "test_directory".
**2. Create Files:** I will create two text files inside "test_directory": "file1.txt" and "file2.txt".
**3. Write Content:** I will write some sample content into both files.
**4. List Directory:** I will list the contents of "test_directory" to confirm the files were created.
**5. Read File:** I will read the content of "file1.txt" to verify the content was written correctly.
**6. Edit File:** I will edit "file2.txt" to replace some text.
**7. Move File:** I will move "file1.txt" to "file3.txt
"""
        # "webhook": "http://localhost:8004/document_conversion_result",
    }
    topic = "file_system.tasks"
    await sdk.publish_task(topic=topic, payload=payload)


if __name__ == "__main__":
    asyncio.run(publish_tasks(sdk=sdk))
