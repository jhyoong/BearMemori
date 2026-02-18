from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryAction:
    action: str
    memory_id: str


@dataclass(frozen=True)
class TaskAction:
    action: str
    task_id: str


@dataclass(frozen=True)
class DueDateChoice:
    memory_id: str
    choice: str


@dataclass(frozen=True)
class ReminderTimeChoice:
    memory_id: str
    choice: str


@dataclass(frozen=True)
class ConfirmDelete:
    memory_id: str
    confirmed: bool


@dataclass(frozen=True)
class SearchDetail:
    memory_id: str


@dataclass(frozen=True)
class TagConfirm:
    memory_id: str
    action: str
