from datetime import datetime

from pydantic import BaseModel, Field


class Memory(BaseModel):
    id: str
    content: str
    raw_input: str
    memory_type: str
    tags: list[str] = Field(default_factory=list)
    embedding: bytes | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    source: str = "unknown"
    metadata: dict = Field(default_factory=dict)
    remind_at: datetime | None = None
    recurring_minutes: int | None = None
