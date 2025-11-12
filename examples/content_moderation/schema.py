from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, ValidationError, model_validator


class ModerationMetadata(BaseModel):
    tenant_id: Optional[str] = Field(default=None)
    campaign_id: Optional[str] = Field(default=None)
    content_type: Optional[str] = Field(
        default=None, description="e.g. text, image, audio"
    )
    source: Optional[str] = Field(
        default=None, description="Upstream system or workflow"
    )
    extra: Dict[str, Any] = Field(default_factory=dict)


class ModerationEvent(BaseModel):
    task: str = Field(..., description="single_file | cycle | report")
    ingested_path: Optional[str] = Field(
        None, description="Normalized path of ingested file"
    )
    original_path: Optional[str] = Field(None, description="Original source path")
    directories: Optional[List[str]] = Field(default=None)
    ingest_timestamp: Optional[str] = None
    requested_by: Optional[str] = None
    metadata: Optional[ModerationMetadata] = None

    @model_validator(mode="after")
    def validate_event(self) -> "ModerationEvent":
        if self.task == "single_file" and not self.ingested_path:
            raise ValueError("single_file task requires ingested_path")

        if self.directories and self.task == "single_file":
            self.directories = None

        if self.directories:
            for path_str in self.directories:
                path = Path(path_str)
                if not path.is_absolute():
                    raise ValueError(f"Directory path must be absolute: {path_str}")
        return self

    def to_payload(self) -> Dict[str, Any]:
        data = self.model_dump(exclude_none=True)
        return data

    @classmethod
    def from_raw(cls, raw: Any) -> "ModerationEvent":
        if isinstance(raw, cls):
            return raw
        if isinstance(raw, dict):
            return cls(**raw)
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid moderation event JSON: {exc}")
            return cls(**parsed)
        raise TypeError(f"Unsupported moderation event payload type: {type(raw)}")


class ModerationDecision(BaseModel):
    status: str = Field(
        ..., description="approved | flagged | removed | error | skipped"
    )
    severity: Optional[str] = Field(
        default=None, description="low | medium | high | critical"
    )
    actions: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
    file_path: Optional[str] = None
    source_event_id: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None

    @classmethod
    def from_agent_response(
        cls, raw: Any, source_event_id: Optional[str] = None
    ) -> "ModerationDecision":
        if isinstance(raw, cls):
            decision = raw
        elif isinstance(raw, dict):
            decision = cls(**raw)
        elif isinstance(raw, str):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid moderation response JSON: {exc}")
            decision = cls(**data)
        else:
            raise TypeError(f"Unsupported moderation response type: {type(raw)}")

        decision.source_event_id = source_event_id
        decision.raw_response = decision.raw_response or decision.model_dump(
            exclude={"raw_response"}
        )
        return decision


__all__ = ["ModerationEvent", "ModerationMetadata", "ModerationDecision"]
