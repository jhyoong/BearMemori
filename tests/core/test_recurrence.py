from datetime import UTC, datetime

import pytest

from bearmemori.core.recurrence import CalendarOccurrence, expand_occurrences
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord


def _make_record(event_dt: str, recurrence: str | None = None, status: str = "pending") -> MemoryRecord:
    return MemoryRecord(
        id="mem_test001",
        category=MemoryCategory.EVENT,
        title="Test Event",
        content="Test content",
        created_at=datetime.now(UTC),
        event_fields=EventFields(datetime=event_dt, status=status, recurrence=recurrence),
    )


def test_expand_non_recurring_in_range():
    record = _make_record("2026-04-10T10:00:00+00:00")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert len(result) == 1
    assert result[0].memory_id == "mem_test001"
    assert result[0].status == "pending"
    assert result[0].is_recurring is False
    assert result[0].occurrence_dt == datetime(2026, 4, 10, 10, 0, 0, tzinfo=UTC)


def test_expand_non_recurring_out_of_range():
    record = _make_record("2026-05-10T10:00:00+00:00")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert result == []


def test_expand_no_event_fields():
    record = MemoryRecord(
        id="mem_test002",
        category=MemoryCategory.GENERAL,
        title="No event",
        content="content",
        created_at=datetime.now(UTC),
    )
    result = expand_occurrences(record, datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 30, tzinfo=UTC))
    assert result == []


def test_expand_non_recurring_done_status():
    record = _make_record("2026-04-10T10:00:00+00:00", status="done")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert len(result) == 1
    assert result[0].status == "done"
