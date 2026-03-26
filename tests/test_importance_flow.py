from unittest.mock import MagicMock

import pytest

from bearmemori.core.processor import Processor
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryPending
from bearmemori.llm.client import ExtractionResult
from bearmemori.storage.pending_store import PendingStore


@pytest.mark.asyncio
async def test_create_pending_includes_importance_in_draft():
    bus = EventBus()
    pending_store = PendingStore()
    llm = MagicMock()
    processor = Processor(bus=bus, llm=llm, pending_store=pending_store)

    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

    extraction = ExtractionResult(
        content="Important meeting",
        category="event",
        title="Team standup",
        tags=["work"],
        importance=8,
    )

    await processor._create_pending(extraction, "meeting tomorrow", "42")

    assert len(pending_events) == 1
    assert pending_events[0].preview_data["importance"] == 8

    # Check the draft stored in pending store has correct importance
    pending = pending_store.get(pending_events[0].pending_id)
    assert pending.draft.importance == 8
