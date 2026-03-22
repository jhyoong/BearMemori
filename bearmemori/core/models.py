from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class QueueItem(BaseModel):
    priority: int = 10
    input_type: str  # "text", "image", "log"
    content: Any
    context: dict | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    source_chat_id: str = ""

    def __lt__(self, other: "QueueItem") -> bool:
        if self.priority != other.priority:
            return self.priority < other.priority
        return self.created_at < other.created_at
