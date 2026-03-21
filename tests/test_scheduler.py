from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from bearmemori.core.scheduler import ReminderScheduler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import ReminderDue
from bearmemori.storage.models import Memory


def _make_reminder(**overrides) -> Memory:
    defaults = {
        "id": "rem-1",
        "content": "Take meds",
        "raw_input": "remind me to take meds",
        "memory_type": "reminder",
        "tags": ["health"],
        "source": "telegram",
        "remind_at": datetime.now() - timedelta(minutes=5),
        "recurring_minutes": None,
        "metadata": {"source_chat_id": "42"},
    }
    defaults.update(overrides)
    return Memory(**defaults)


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
    reminder = _make_reminder()
    mock_db.get_due_reminders.return_value = [reminder]

    fired = []
    bus.on(ReminderDue, lambda e: fired.append(e))

    await scheduler.check_reminders()

    assert len(fired) == 1
    assert fired[0].memory_id == "rem-1"
    assert fired[0].content == "Take meds"
    assert fired[0].source_chat_id == "42"


@pytest.mark.asyncio
async def test_check_nulls_oneoff_reminder(scheduler, mock_db):
    reminder = _make_reminder(recurring_minutes=None)
    mock_db.get_due_reminders.return_value = [reminder]

    await scheduler.check_reminders()

    mock_db.update.assert_called_once()
    updated = mock_db.update.call_args[0][0]
    assert updated.remind_at is None


@pytest.mark.asyncio
async def test_check_advances_recurring_reminder(scheduler, mock_db):
    original_time = datetime.now() - timedelta(minutes=5)
    reminder = _make_reminder(
        remind_at=original_time,
        recurring_minutes=480,
    )
    mock_db.get_due_reminders.return_value = [reminder]

    await scheduler.check_reminders()

    mock_db.update.assert_called_once()
    updated = mock_db.update.call_args[0][0]
    expected_next = original_time + timedelta(minutes=480)
    assert updated.remind_at == expected_next
    assert updated.recurring_minutes == 480


@pytest.mark.asyncio
async def test_check_no_due_reminders(scheduler, bus, mock_db):
    mock_db.get_due_reminders.return_value = []

    fired = []
    bus.on(ReminderDue, lambda e: fired.append(e))

    await scheduler.check_reminders()

    assert len(fired) == 0
    mock_db.update.assert_not_called()
