import tempfile
from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        d = MemoryDatabase(f.name)
        d.initialize()
        yield d


def _event_record(
    record_id: str, dt: str, recurrence: str | None = None, category=MemoryCategory.EVENT
) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=category,
        title=f"Event {record_id}",
        content="content",
        created_at=datetime.now(UTC),
        event_fields=EventFields(datetime=dt, status="pending", recurrence=recurrence),
    )


def test_get_events_in_range_non_recurring(db):
    db.create(_event_record("mem_001", "2026-04-10T10:00:00+00:00"))
    db.create(_event_record("mem_002", "2026-05-10T10:00:00+00:00"))  # outside range

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = db.get_events_in_range(start, end)

    ids = [r.id for r in result]
    assert "mem_001" in ids
    assert "mem_002" not in ids


def test_get_events_in_range_includes_recurring_starting_before_range(db):
    # Recurring weekly starting in March -- should appear in April range
    db.create(
        _event_record("mem_003", "2026-03-03T10:00:00+00:00", recurrence="FREQ=WEEKLY;BYDAY=TU")
    )

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = db.get_events_in_range(start, end)

    ids = [r.id for r in result]
    assert "mem_003" in ids


def test_get_events_in_range_excludes_done_recurring(db):
    r = _event_record("mem_004", "2026-03-03T10:00:00+00:00", recurrence="FREQ=WEEKLY;BYDAY=TU")
    r.event_fields.status = "done"
    db.create(r)

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = db.get_events_in_range(start, end)

    ids = [r.id for r in result]
    assert "mem_004" not in ids


def test_get_events_in_range_only_event_task_reminder(db):
    db.create(
        _event_record("mem_005", "2026-04-10T10:00:00+00:00", category=MemoryCategory.GENERAL)
    )

    start = datetime(2026, 4, 1, tzinfo=UTC)
    end = datetime(2026, 4, 30, 23, 59, 59, tzinfo=UTC)
    result = db.get_events_in_range(start, end)

    ids = [r.id for r in result]
    assert "mem_005" not in ids
