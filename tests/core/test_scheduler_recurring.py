import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.core.scheduler import ReminderScheduler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import ReminderDue
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        d = MemoryDatabase(f.name)
        d.initialize()
        yield d


@pytest.fixture
def bus():
    b = MagicMock(spec=EventBus)
    b.emit = AsyncMock()
    return b


@pytest.mark.asyncio
async def test_recurring_fires_due_occurrence_and_marks_completed(db, bus):
    # Daily recurrence with base_dt 2 hours ago — always within the 25h window
    base_dt = datetime.now(UTC) - timedelta(hours=2)
    occ_date_str = base_dt.date().isoformat()
    record = MemoryRecord(
        id="mem_rec001",
        category=MemoryCategory.REMINDER,
        title="Weekly standup",
        content="Do the standup",
        created_at=datetime.now(UTC),
        event_fields=EventFields(
            datetime=base_dt.isoformat(),
            status="pending",
            recurrence="FREQ=DAILY",
        ),
    )
    db.create(record)

    scheduler = ReminderScheduler(bus, db)
    await scheduler.check_reminders()

    bus.emit.assert_called_once()
    event = bus.emit.call_args[0][0]
    assert isinstance(event, ReminderDue)
    assert event.memory_id == "mem_rec001"

    # Record should have completed_occurrences set, status still pending
    updated = db.get("mem_rec001")
    assert updated.event_fields.status == "pending"
    assert occ_date_str in updated.metadata.get("completed_occurrences", [])


@pytest.mark.asyncio
async def test_recurring_does_not_refire_completed_occurrence(db, bus):
    base_dt = datetime.now(UTC) - timedelta(hours=2)
    occ_date_str = base_dt.date().isoformat()
    record = MemoryRecord(
        id="mem_rec002",
        category=MemoryCategory.REMINDER,
        title="Weekly standup",
        content="Do the standup",
        created_at=datetime.now(UTC),
        event_fields=EventFields(
            datetime=base_dt.isoformat(),
            status="pending",
            recurrence="FREQ=DAILY",
        ),
        metadata={"completed_occurrences": [occ_date_str]},
    )
    db.create(record)

    scheduler = ReminderScheduler(bus, db)
    await scheduler.check_reminders()

    bus.emit.assert_not_called()


@pytest.mark.asyncio
async def test_non_recurring_still_marks_done(db, bus):
    record = MemoryRecord(
        id="mem_single001",
        category=MemoryCategory.REMINDER,
        title="One-time reminder",
        content="Do the thing",
        created_at=datetime.now(UTC),
        event_fields=EventFields(
            datetime=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
            status="pending",
        ),
    )
    db.create(record)

    scheduler = ReminderScheduler(bus, db)
    await scheduler.check_reminders()

    bus.emit.assert_called_once()
    updated = db.get("mem_single001")
    assert updated.event_fields.status == "done"
