from unittest.mock import AsyncMock

import pytest

from bearmemori.core.followup import FollowUpManager
from bearmemori.core.processor import Processor
from bearmemori.core.queue import QueueManager
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import (
    FollowUpRequired,
    InputReceived,
    MemoryStored,
    SendMessage,
)
from bearmemori.llm.client import ClassificationResult, ExtractionResult
from bearmemori.storage.database import MemoryDatabase


@pytest.fixture
def db(tmp_path):
    database = MemoryDatabase(str(tmp_path / "test.db"))
    database.initialize()
    return database


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def wired_system(db, mock_llm):
    bus = EventBus()
    queue = QueueManager(bus, max_size=100)
    processor = Processor(bus=bus, llm=mock_llm, db=db, embedding_model="test")
    followup = FollowUpManager(bus)

    bus.on(InputReceived, queue.handle_input)
    bus.on(FollowUpRequired, followup.handle_followup_required)

    return {"bus": bus, "queue": queue, "processor": processor, "followup": followup}


@pytest.mark.asyncio
async def test_full_store_flow(wired_system, mock_llm, db):
    bus = wired_system["bus"]
    queue = wired_system["queue"]
    processor = wired_system["processor"]

    stored = []
    bus.on(MemoryStored, lambda e: stored.append(e))

    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", memory_type="preference", confidence=0.95
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="User likes dark mode", memory_type="preference", tags=["ui"]
    )
    mock_llm.get_embedding.return_value = [0.1, 0.2, 0.3]

    # Simulate input
    await bus.emit(
        InputReceived(input_type="text", content="I like dark mode", source_chat_id="42")
    )

    # Process the queued item
    item = await queue.get_next()
    await processor.process_item(item)

    assert len(stored) == 1
    assert stored[0].content == "User likes dark mode"

    # Verify it's in the database
    memories = db.list_memories()
    assert len(memories) == 1
    assert memories[0].content == "User likes dark mode"


@pytest.mark.asyncio
async def test_followup_flow(wired_system, mock_llm, db):
    bus = wired_system["bus"]
    queue = wired_system["queue"]
    processor = wired_system["processor"]
    followup = wired_system["followup"]

    sent = []
    bus.on(SendMessage, lambda e: sent.append(e))

    # First input: LLM needs clarification
    mock_llm.classify_input.return_value = ClassificationResult(
        action="followup", question="What changed?"
    )
    mock_llm.generate_followup.return_value = "Can you be more specific about what changed?"

    await bus.emit(
        InputReceived(input_type="text", content="something changed", source_chat_id="42")
    )
    item = await queue.get_next()
    await processor.process_item(item)

    assert len(sent) == 1
    assert followup.has_active_followup("42")

    # Second input: follow-up response
    mock_llm.classify_input.return_value = ClassificationResult(
        action="store", memory_type="fact", confidence=0.9
    )
    mock_llm.extract_memory.return_value = ExtractionResult(
        content="Theme changed to dark mode", memory_type="fact", tags=["ui"]
    )
    mock_llm.get_embedding.return_value = [0.1, 0.2]

    # Simulate follow-up input
    followup_event = InputReceived(
        input_type="text", content="the theme changed to dark mode", source_chat_id="42"
    )
    checked = followup.check_followup(followup_event)
    assert checked is not None
    assert checked.context is not None

    await bus.emit(checked)
    item = await queue.get_next()
    await processor.process_item(item)

    memories = db.list_memories()
    assert len(memories) == 1
