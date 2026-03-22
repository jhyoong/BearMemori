from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.core.models import QueueItem
from bearmemori.core.processor import Processor
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import FollowUpRequired, MemoryPending
from bearmemori.llm.client import ClassificationResult, ExtractionResult


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_pending_store():
    store = MagicMock()
    store.add.return_value = "pend_abc123"
    return store


@pytest.fixture
def processor(bus, mock_llm, mock_pending_store):
    return Processor(bus=bus, llm=mock_llm, pending_store=mock_pending_store)


@pytest.mark.asyncio
async def test_process_item_creates_pending_memory(processor, bus, mock_llm, mock_pending_store):
    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

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

    mock_pending_store.add.assert_called_once()
    assert len(pending_events) == 1
    assert pending_events[0].pending_id == "pend_abc123"
    assert pending_events[0].source_chat_id == "123"
    assert pending_events[0].preview_data["title"] == "Dark mode preference"


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
async def test_process_item_stores_reminder(processor, bus, mock_llm, mock_pending_store):
    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

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

    mock_pending_store.add.assert_called_once()
    assert len(pending_events) == 1
    assert pending_events[0].preview_data["category"] == "reminder"


@pytest.mark.asyncio
async def test_process_image_without_caption(processor, bus, mock_llm, mock_pending_store):
    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

    mock_llm.describe_image.return_value = ExtractionResult(
        content="A sunset over the ocean",
        category="general",
        title="Ocean sunset",
        tags=["photo", "nature"],
    )

    item = QueueItem(
        input_type="image",
        content={"image_bytes": b"fake-image", "caption": "", "image_path": "/tmp/test.jpg"},
        source_chat_id="123",
    )
    await processor.process_item(item)

    mock_llm.describe_image.assert_called_once_with(b"fake-image", caption="")
    mock_pending_store.add.assert_called_once()
    assert len(pending_events) == 1


@pytest.mark.asyncio
async def test_process_edit_re_extracts_memory(processor, bus, mock_llm, mock_pending_store):
    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

    # Set up the original pending memory
    original_pending = MagicMock()
    original_pending.draft.content = "Dentist on Tuesday"
    original_pending.chat_id = "123"
    original_pending.image_path = None
    mock_pending_store.get.return_value = original_pending

    mock_pending_store.add.return_value = "pend_new123"

    mock_llm.extract_memory.return_value = ExtractionResult(
        content="Dentist appointment on Wednesday",
        category="reminder",
        title="Dentist on Wednesday",
        tags=["health"],
        event_fields={
            "datetime": "2026-04-16T10:00:00",
            "status": "pending",
            "recurrence": None,
        },
    )

    item = QueueItem(
        input_type="text",
        content="Actually it's Wednesday not Tuesday",
        source_chat_id="123",
        context={"edit_pending_id": "pend_abc123"},
    )
    await processor.process_item(item)

    # Old pending should be removed
    mock_pending_store.remove.assert_called_with("pend_abc123")
    # New pending should be created
    mock_pending_store.add.assert_called_once()
    assert len(pending_events) == 1
    assert pending_events[0].preview_data["title"] == "Dentist on Wednesday"


@pytest.mark.asyncio
async def test_process_image_with_caption(processor, bus, mock_llm, mock_pending_store):
    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", category="general", confidence=0.9
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="Photo of new apartment kitchen",
        category="general",
        title="New apartment kitchen",
        tags=["home"],
    )

    item = QueueItem(
        input_type="image",
        content={
            "image_bytes": b"fake-image",
            "caption": "My new kitchen",
            "image_path": "/tmp/test.jpg",
        },
        source_chat_id="123",
    )
    await processor.process_item(item)

    mock_llm.classify_input.assert_called_once_with("My new kitchen")
    mock_pending_store.add.assert_called_once()
    assert len(pending_events) == 1
