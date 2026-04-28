from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MemoryCategory(str, Enum):
    PROFILE = "profile"
    GENERAL = "general"
    EVENT = "event"
    LOCATION = "location"
    TASK = "task"
    REMINDER = "reminder"


class Actor(str, Enum):
    TELEGRAM = "telegram"
    WEBAPP = "webapp"
    API = "api"
    REFLECTION = "reflection"


class AuditAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ARCHIVE = "archive"


class AuditEntry(BaseModel):
    id: int
    memory_id: str
    action: str  # AuditAction value
    actor: Actor
    timestamp: datetime
    title_snapshot: str | None = None
    category_snapshot: str | None = None


class MemorySource(BaseModel):
    platform: str
    chat_id: str
    message_ids: list[str] = Field(default_factory=list)


class EventFields(BaseModel):
    datetime: str  # ISO 8601 string
    status: Literal["pending", "done"] = "pending"
    recurrence: str | None = None


class MemoryDraft(BaseModel):
    category: MemoryCategory
    title: str
    content: str
    event_fields: EventFields | None = None
    tags: list[str] = Field(default_factory=list)
    importance: int = 5
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
    importance: int = 5
    source: MemorySource | None = None
    metadata: dict = Field(default_factory=dict)
    needs_review: bool = False
    image_path: str | None = None
    archived: bool = False

    @classmethod
    def from_draft(cls, draft: MemoryDraft, record_id: str) -> MemoryRecord:
        return cls(
            id=record_id,
            category=draft.category,
            title=draft.title,
            content=draft.content,
            created_at=datetime.now(UTC),
            event_fields=draft.event_fields,
            tags=draft.tags,
            importance=draft.importance,
            source=draft.source,
            needs_review=False,
        )


class PendingMemory(BaseModel):
    pending_id: str
    draft: MemoryDraft
    ttl_seconds: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    chat_id: str = ""
    message_id: int | None = None
    image_bytes: bytes | None = None


class ReflectionProposal(BaseModel):
    id: str
    proposal_type: Literal["merge", "archive", "rerank"]
    status: Literal["pending", "approved", "rejected"]
    memory_ids: list[str]
    recommended_keep_id: str | None = None
    recommended_importance: int | None = None
    reasoning: str
    resolution_note: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None
