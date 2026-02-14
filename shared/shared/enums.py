from enum import StrEnum


class MemoryStatus(StrEnum):
    confirmed = "confirmed"
    pending = "pending"


class TaskState(StrEnum):
    NOT_DONE = "NOT_DONE"
    DONE = "DONE"


class EventStatus(StrEnum):
    pending = "pending"
    confirmed = "confirmed"
    rejected = "rejected"


class EventSourceType(StrEnum):
    email = "email"
    manual = "manual"


class MediaType(StrEnum):
    image = "image"


class JobType(StrEnum):
    image_tag = "image_tag"
    intent_classify = "intent_classify"
    followup = "followup"
    task_match = "task_match"
    email_extract = "email_extract"


class JobStatus(StrEnum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class AuditAction(StrEnum):
    created = "created"
    confirmed = "confirmed"
    deleted = "deleted"
    expired = "expired"
    fired = "fired"
    updated = "updated"
    rejected = "rejected"
    requeued = "requeued"


class EntityType(StrEnum):
    memory = "memory"
    task = "task"
    reminder = "reminder"
    event = "event"
    llm_job = "llm_job"
