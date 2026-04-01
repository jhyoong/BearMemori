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
    record: MemoryRecord,
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
    record: MemoryRecord,
    start: datetime,
    end: datetime,
) -> list[CalendarOccurrence]:
    from dateutil import rrule as rrulelib

    completed = set(record.metadata.get("completed_occurrences", []))
    base_dt = datetime.fromisoformat(record.event_fields.datetime)

    try:
        rule = rrulelib.rrulestr(record.event_fields.recurrence, dtstart=base_dt)
    except Exception:
        return []

    occurrences = []
    for occ_dt in rule.between(start, end, inc=True):
        occ_date_str = occ_dt.date().isoformat()
        status = "done" if occ_date_str in completed else "pending"
        occurrences.append(
            CalendarOccurrence(
                memory_id=record.id,
                title=record.title,
                category=record.category.value,
                occurrence_dt=occ_dt,
                status=status,
                is_recurring=True,
            )
        )

    return occurrences


def parse_rrule_to_form(rrule_str: str) -> dict:
    """Parse an RRULE string into form field values."""
    if not rrule_str:
        return {
            "freq": "",
            "interval": 1,
            "byday": [],
            "bymonthday": "",
            "until": "",
            "count": "",
        }

    parts: dict[str, str] = {}
    for part in rrule_str.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            parts[k.upper()] = v

    return {
        "freq": parts.get("FREQ", "").lower(),
        "interval": int(parts.get("INTERVAL", 1)),
        "byday": parts.get("BYDAY", "").split(",") if parts.get("BYDAY") else [],
        "bymonthday": parts.get("BYMONTHDAY", ""),
        "until": parts.get("UNTIL", ""),
        "count": parts.get("COUNT", ""),
    }


def build_rrule_from_form(
    freq: str,
    interval: int = 1,
    byday: list[str] | None = None,
    bymonthday: str = "",
    until: str = "",
    count: str = "",
) -> str:
    """Build an RRULE string from form field values."""
    if not freq:
        return ""

    parts = [f"FREQ={freq.upper()}"]
    if interval and int(interval) > 1:
        parts.append(f"INTERVAL={int(interval)}")
    if byday:
        filtered = [d for d in byday if d]
        if filtered:
            parts.append(f"BYDAY={','.join(filtered)}")
    if bymonthday:
        parts.append(f"BYMONTHDAY={bymonthday}")
    if until:
        parts.append(f"UNTIL={until}")
    elif count:
        parts.append(f"COUNT={count}")

    return ";".join(parts)
