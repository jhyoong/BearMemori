from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from bearmemori.core.scheduler import ReminderScheduler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import ReminderDue
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord, MemorySource


def _make_record(**overrides) -> MemoryRecord:
    defaults = {
        "id": "rem-1",
        "category": MemoryCategory.REMINDER,
        "title": "Reminder",
        "content": "Take meds",
        "created_at": datetime.now(UTC),
        "raw_input": "remind me to take meds",
        "event_fields": EventFields(
            datetime="2026-03-21T10:00:00",
            status="pending",
            recurrence=None,
        ),
        "tags": ["health"],
        "source": MemorySource(platform="telegram", chat_id="42"),
        "metadata": {},
    }
    defaults.update(overrides)
    return MemoryRecord(**defaults)


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def scheduler(bus, mock_db):
    return ReminderScheduler(bus=bus, db=mock_db, poll_interval_seconds=60)


@pytest.mark.asyncio
async def test_check_fires_due_reminder(scheduler, bus, mock_db):
    record = _make_record()
    mock_db.get_due_events.return_value = [record]

    fired = []
    bus.on(ReminderDue, lambda e: fired.append(e))

    await scheduler.check_reminders()

    assert len(fired) == 1
    assert fired[0].memory_id == "rem-1"
    assert fired[0].content == "Take meds"
    assert fired[0].source_chat_id == "42"
    assert fired[0].remind_at_iso == "2026-03-21T10:00:00"


@pytest.mark.asyncio
async def test_check_marks_event_done(scheduler, mock_db):
    record = _make_record()
    mock_db.get_due_events.return_value = [record]

    await scheduler.check_reminders()

    mock_db.update.assert_called_once()
    updated = mock_db.update.call_args[0][0]
    assert updated.event_fields.status == "done"


@pytest.mark.asyncio
async def test_check_recurring_fires_and_tracks_occurrence(scheduler, bus, mock_db):
    # Use FREQ=DAILY with base_dt 2 hours ago — always within the 25h window
    base_dt = datetime.now(UTC) - timedelta(hours=2)
    occ_date_str = base_dt.date().isoformat()
    record = _make_record(
        event_fields=EventFields(
            datetime=base_dt.isoformat(),
            status="pending",
            recurrence="FREQ=DAILY",
        ),
        metadata={},
    )
    mock_db.get_due_events.return_value = [record]

    fired = []
    bus.on(ReminderDue, lambda e: fired.append(e))

    await scheduler.check_reminders()

    assert len(fired) == 1
    assert fired[0].memory_id == "rem-1"
    mock_db.update.assert_called_once()
    updated = mock_db.update.call_args[0][0]
    # Status stays pending for recurring records
    assert updated.event_fields.status == "pending"
    assert occ_date_str in updated.metadata.get("completed_occurrences", [])


@pytest.mark.asyncio
async def test_check_no_due_events(scheduler, bus, mock_db):
    mock_db.get_due_events.return_value = []

    fired = []
    bus.on(ReminderDue, lambda e: fired.append(e))

    await scheduler.check_reminders()

    assert len(fired) == 0
    mock_db.update.assert_not_called()
