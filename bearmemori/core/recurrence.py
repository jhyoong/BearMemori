from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from bearmemori.storage.models import MemoryRecord


class CalendarOccurrence(BaseModel):
    memory_id: str
    title: str
    category: str
    occurrence_dt: datetime
    status: str  # "pending" or "done"
    is_recurring: bool


def expand_occurrences(
    record: "MemoryRecord",
    start: datetime,
    end: datetime,
) -> list[CalendarOccurrence]:
    if record.event_fields is None:
        return []

    if not record.event_fields.recurrence:
        occ_dt = datetime.fromisoformat(record.event_fields.datetime)
        if start <= occ_dt <= end:
            return [
                CalendarOccurrence(
                    memory_id=record.id,
                    title=record.title,
                    category=record.category.value,
                    occurrence_dt=occ_dt,
                    status=record.event_fields.status,
                    is_recurring=False,
                )
            ]
        return []

    return _expand_recurring(record, start, end)


def _expand_recurring(
    record: "MemoryRecord",
    start: datetime,
    end: datetime,
) -> list[CalendarOccurrence]:
    # Placeholder -- implemented in Task 3
    return []


def parse_rrule_to_form(rrule_str: str) -> dict:
    # Placeholder -- implemented in Task 4
    return {}


def build_rrule_from_form(**kwargs) -> str:
    # Placeholder -- implemented in Task 4
    return ""
