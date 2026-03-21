from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.core.models import QueueItem
from bearmemori.core.processor import Processor
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, MemoryStored
from bearmemori.llm.client import ClassificationResult, ExtractionResult
from bearmemori.storage.models import MemoryCategory, MemoryRecord


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def processor(bus, mock_llm, mock_db):
    return Processor(bus=bus, llm=mock_llm, db=mock_db)


@pytest.mark.asyncio
async def test_process_item_stores_memory(processor, bus, mock_llm, mock_db):
    stored_events = []
    bus.on(MemoryStored, lambda e: stored_events.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", category="profile", confidence=0.9
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="User likes dark mode",
        category="profile",
        title="Dark mode preference",
        tags=["ui"],
    )

    item = QueueItem(input_type="text", content="I like dark mode", source_chat_id="123")
    await processor.process_item(item)

    mock_db.create.assert_called_once()
    created_record = mock_db.create.call_args[0][0]
    assert isinstance(created_record, MemoryRecord)
    assert created_record.category == MemoryCategory.PROFILE
    assert created_record.title == "Dark mode preference"
    assert len(stored_events) == 1
    assert stored_events[0].source_chat_id == "123"
    assert stored_events[0].category == "profile"


@pytest.mark.asyncio
async def test_process_item_requests_followup(processor, bus, mock_llm):
    followup_events = []
    bus.on(FollowUpRequired, lambda e: followup_events.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="followup", question="What changed?"
    )
    mock_llm.generate_followup.return_value = "Can you tell me more?"

    item = QueueItem(input_type="text", content="something changed", source_chat_id="123")
    await processor.process_item(item)

    assert len(followup_events) == 1
    assert followup_events[0].source_chat_id == "123"


@pytest.mark.asyncio
async def test_process_item_stores_reminder(processor, bus, mock_llm, mock_db):
    stored_events = []
    bus.on(MemoryStored, lambda e: stored_events.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", category="reminder", confidence=0.95
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="Take meds every 8 hours",
        category="reminder",
        title="Take meds every 8 hours",
        tags=["health"],
        event_fields={
            "datetime": "2026-03-21T20:00:00",
            "status": "pending",
            "recurrence": "every 8 hours",
        },
    )

    item = QueueItem(
        input_type="text",
        content="remind me every 8 hours to take meds",
        source_chat_id="123",
    )
    await processor.process_item(item)

    mock_db.create.assert_called_once()
    created_record = mock_db.create.call_args[0][0]
    assert isinstance(created_record, MemoryRecord)
    assert created_record.category == MemoryCategory.REMINDER
    assert created_record.title == "Take meds every 8 hours"
    assert created_record.event_fields.datetime == "2026-03-21T20:00:00"
    assert created_record.event_fields.recurrence == "every 8 hours"
    assert created_record.source.chat_id == "123"
    assert len(stored_events) == 1
    assert stored_events[0].category == "reminder"
