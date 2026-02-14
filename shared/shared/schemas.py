from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict
from shared.enums import (
    MemoryStatus,
    MediaType,
    TaskState,
    EventStatus,
    EventSourceType,
    JobType,
    JobStatus,
    AuditAction,
    EntityType,
)


# Memory schemas
class MemoryCreate(BaseModel):
    owner_user_id: int
    content: str | None = None
    media_type: MediaType | None = None
    media_file_id: str | None = None
    source_chat_id: int | None = None
    source_message_id: int | None = None


class MemoryUpdate(BaseModel):
    content: str | None = None
    status: MemoryStatus | None = None
    is_pinned: bool | None = None
    media_local_path: str | None = None


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_user_id: int
    content: str | None
    media_type: MediaType | None
    media_file_id: str | None
    media_local_path: str | None
    status: MemoryStatus
    pending_expires_at: datetime | None
    is_pinned: bool
    created_at: datetime
    updated_at: datetime


class TagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    created_at: datetime


# Memory tag schemas (for memory_tags table)
class MemoryTagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tag: str
    status: str
    suggested_at: datetime | None
    confirmed_at: datetime | None


class MemoryWithTags(MemoryResponse):
    tags: list[MemoryTagResponse]


# Tag schemas
class TagAdd(BaseModel):
    memory_id: str
    tag_name: str


class TagsAddRequest(BaseModel):
    tags: list[str]
    status: str = "confirmed"


# Task schemas
class TaskCreate(BaseModel):
    memory_id: str
    owner_user_id: int
    description: str
    due_at: datetime | None = None
    recurrence_minutes: int | None = None


class TaskUpdate(BaseModel):
    description: str | None = None
    state: TaskState | None = None
    due_at: datetime | None = None
    recurrence_minutes: int | None = None


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    memory_id: str
    owner_user_id: int
    description: str
    state: TaskState
    due_at: datetime | None
    recurrence_minutes: int | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskUpdateResponse(BaseModel):
    task: TaskResponse
    recurring_task_id: str | None = None


# Reminder schemas
class ReminderCreate(BaseModel):
    owner_user_id: int
    text: str
    fire_at: datetime
    source_chat_id: int | None = None
    source_message_id: int | None = None


class ReminderUpdate(BaseModel):
    text: str | None = None
    fire_at: datetime | None = None


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_user_id: int
    text: str
    fire_at: datetime
    fired: bool
    created_at: datetime
    updated_at: datetime


# Event schemas
class EventCreate(BaseModel):
    owner_user_id: int
    event_time: datetime
    description: str
    status: EventStatus = EventStatus.pending
    source_type: EventSourceType
    source_detail: str | None = None
    source_chat_id: int | None = None
    source_message_id: int | None = None


class EventUpdate(BaseModel):
    event_time: datetime | None = None
    description: str | None = None
    status: EventStatus | None = None


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_user_id: int
    event_time: datetime
    description: str
    status: EventStatus
    source_type: EventSourceType
    source_detail: str | None
    created_at: datetime
    updated_at: datetime


# Settings schemas
class UserSettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    timezone: str
    language: str
    created_at: datetime
    updated_at: datetime


class UserSettingsUpdate(BaseModel):
    timezone: str | None = None
    language: str | None = None


# Search schemas
class SearchResult(BaseModel):
    entity_type: EntityType
    entity_id: str
    content: str
    created_at: datetime
    score: float | None = None


# Audit schemas
class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: int
    entity_type: EntityType
    entity_id: str
    action: AuditAction
    detail: dict[str, Any] | None
    created_at: datetime


# Backup schemas
class BackupStatus(BaseModel):
    backup_id: str
    user_id: int
    started_at: datetime
    completed_at: datetime | None
    status: str
    file_path: str | None
    error_message: str | None = None


# LLM Job schemas
class LLMJobCreate(BaseModel):
    job_type: JobType
    payload: dict[str, Any]
    user_id: int | None = None


class LLMJobUpdate(BaseModel):
    status: JobStatus | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None


class LLMJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    job_type: JobType
    payload: dict[str, Any]
    user_id: int | None
    status: JobStatus
    result: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


# Redis message schemas
class TelegramOutboundMessage(BaseModel):
    chat_id: int
    text: str
    reply_to_message_id: int | None = None
    parse_mode: str | None = None


class ReminderNotification(BaseModel):
    reminder_id: str
    user_id: int
    text: str
    fire_at: datetime
