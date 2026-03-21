from datetime import datetime

from pydantic import BaseModel


class MemoryResponse(BaseModel):
    id: str
    content: str
    raw_input: str
    memory_type: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime
    source: str
    metadata: dict


class MemoryCreate(BaseModel):
    content: str
    raw_input: str = ""
    memory_type: str
    tags: list[str] = []
    source: str = "api"
    metadata: dict = {}


class MemoryUpdate(BaseModel):
    content: str | None = None
    memory_type: str | None = None
    tags: list[str] | None = None
    metadata: dict | None = None


class SearchRequest(BaseModel):
    query: str
    mode: str = "keyword"  # "keyword", "semantic", "hybrid"
    limit: int = 20


class ReminderResponse(BaseModel):
    id: str
    content: str
    memory_type: str
    tags: list[str]
    remind_at: datetime | None
    recurring_minutes: int | None
    created_at: datetime
    source: str
    metadata: dict
