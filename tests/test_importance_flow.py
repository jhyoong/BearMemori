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


@pytest.mark.asyncio
async def test_telegram_preview_shows_importance():
    from unittest.mock import AsyncMock, MagicMock

    from bearmemori.events.bus import EventBus
    from bearmemori.events.domain import MemoryPending
    from bearmemori.interfaces.telegram import TelegramInterface

    bus = EventBus()
    interface = TelegramInterface(bus=bus, token="fake", allowed_user_id=12345)

    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    event = MemoryPending(
        pending_id="pend_imp_test",
        preview_data={
            "title": "Test memory",
            "category": "general",
            "content": "Some content",
            "tags": [],
            "importance": 8,
        },
        source_chat_id="42",
    )

    await interface.handle_memory_pending(event)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "Importance: 8/10" in call_kwargs["text"]
