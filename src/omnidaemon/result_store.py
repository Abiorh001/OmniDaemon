# src/omnidaemon/result_store.py

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import asyncio


class ResultStore(ABC):
    @abstractmethod
    async def save_result(self, task_id: str, result: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        pass


class RedisResultStore(ResultStore):
    def __init__(self, redis_client):
        self._redis = redis_client

    async def save_result(self, task_id: str, result: Dict[str, Any]) -> None:
        import json

        key = f"omni:result:{task_id}"
        await self._redis.setex(key, 86400, json.dumps(result, default=str))

    async def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        key = f"omni:result:{task_id}"
        data = await self._redis.get(key)
        if data:
            import json

            return json.loads(data)
        return None
