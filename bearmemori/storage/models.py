from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MemoryCategory(str, Enum):
    PROFILE = "profile"
    GENERAL = "general"
    EVENT = "event"
    LOCATION = "location"
    TASK = "task"
    REMINDER = "reminder"


class MemorySource(BaseModel):
    platform: str
    chat_id: str
    message_ids: list[str] = Field(default_factory=list)


class EventFields(BaseModel):
    datetime: str  # ISO 8601 string
    status: str = "pending"
    recurrence: str | None = None


class MemoryDraft(BaseModel):
    category: MemoryCategory
    title: str
    content: str
    event_fields: EventFields | None = None
    tags: list[str] = Field(default_factory=list)
    source: MemorySource | None = None


class MemoryRecord(BaseModel):
    id: str
    category: MemoryCategory
    title: str
    content: str
    created_at: datetime
    raw_input: str = ""
    event_fields: EventFields | None = None
    tags: list[str] = Field(default_factory=list)
    source: MemorySource | None = None
    metadata: dict = Field(default_factory=dict)

    @classmethod
    def from_draft(cls, draft: MemoryDraft, record_id: str) -> MemoryRecord:
        return cls(
            id=record_id,
            category=draft.category,
            title=draft.title,
            content=draft.content,
            created_at=datetime.now(timezone.utc),
            event_fields=draft.event_fields,
            tags=draft.tags,
            source=draft.source,
        )


class PendingMemory(BaseModel):
    pending_id: str
    draft: MemoryDraft
    ttl_seconds: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
