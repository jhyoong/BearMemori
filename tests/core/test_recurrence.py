from datetime import UTC, datetime

from bearmemori.core.recurrence import expand_occurrences
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord


def _make_record(
    event_dt: str, recurrence: str | None = None, status: str = "pending"
) -> MemoryRecord:
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
    result = expand_occurrences(
        record, datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 30, tzinfo=UTC)
    )
    assert result == []


def test_expand_non_recurring_done_status():
    record = _make_record("2026-04-10T10:00:00+00:00", status="done")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert len(result) == 1
    assert result[0].status == "done"


def test_expand_weekly_recurring_in_range():
    # Every Tuesday starting 2026-04-07
    record = _make_record("2026-04-07T10:00:00+00:00", recurrence="FREQ=WEEKLY;BYDAY=TU")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    # Tuesdays in April 2026: Apr 7, 14, 21, 28
    assert len(result) == 4
    assert all(occ.is_recurring for occ in result)
    assert all(occ.status == "pending" for occ in result)
    assert result[0].occurrence_dt.day == 7
    assert result[1].occurrence_dt.day == 14
    assert result[2].occurrence_dt.day == 21
    assert result[3].occurrence_dt.day == 28


def test_expand_recurring_with_completed_occurrences():
    record = _make_record("2026-04-07T10:00:00+00:00", recurrence="FREQ=WEEKLY;BYDAY=TU")
    record.metadata["completed_occurrences"] = ["2026-04-07", "2026-04-14"]
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert len(result) == 4
    assert result[0].status == "done"
    assert result[1].status == "done"
    assert result[2].status == "pending"
    assert result[3].status == "pending"


def test_expand_recurring_invalid_rrule_returns_empty():
    record = _make_record("2026-04-07T10:00:00+00:00", recurrence="NOT_A_VALID_RRULE")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert result == []


def test_expand_recurring_no_occurrences_in_range():
    # Every year on Jan 1, range is April
    record = _make_record("2026-01-01T10:00:00+00:00", recurrence="FREQ=YEARLY")
    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = expand_occurrences(record, start, end)
    assert result == []
