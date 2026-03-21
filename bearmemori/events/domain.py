from typing import Any

from bearmemori.events.types import Event


class InputReceived(Event):
    input_type: str  # "text", "image", "log"
    content: Any
    source_chat_id: str
    context: dict | None = None


class InputQueued(Event):
    priority: int
    input_type: str
    source_chat_id: str


class FollowUpRequired(Event):
    question: str
    source_chat_id: str
    context: dict


class MemoryStored(Event):
    memory_id: str
    content: str
    memory_type: str
    source_chat_id: str


class MemoryUpdated(Event):
    memory_id: str


class MemoryDeleted(Event):
    memory_id: str


class SendMessage(Event):
    chat_id: str
    text: str
