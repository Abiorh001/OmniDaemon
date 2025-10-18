from pydantic import BaseModel, Field
from typing import Any, Dict, Optional, Callable, Awaitable
import uuid


class EventEnvelope(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str
    payload: Dict[str, Any]
    meta: Dict[str, Any] = Field(default_factory=dict)
    tenant: Optional[str] = None
