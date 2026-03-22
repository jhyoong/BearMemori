import time

import pytest

from bearmemori.core.cleanup import PendingCleanupTask
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryDiscarded, SendMessage
from bearmemori.storage.models import MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def pending_store():
    return PendingStore(default_ttl=1)


@pytest.fixture
def cleanup(bus, pending_store):
    return PendingCleanupTask(bus=bus, pending_store=pending_store)


def _make_draft():
    return MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
    )


@pytest.mark.asyncio
async def test_cleanup_discards_expired_and_notifies(cleanup, bus, pending_store):
    discarded_events = []
    send_events = []
    bus.on(MemoryDiscarded, lambda e: discarded_events.append(e))
    bus.on(SendMessage, lambda e: send_events.append(e))

    pending_store.add(_make_draft(), chat_id="123")
    pending_store.add(_make_draft(), chat_id="456")
    time.sleep(1.1)

    await cleanup.run_once()

    assert len(discarded_events) == 2
    assert len(send_events) == 2
    chat_ids = {e.chat_id for e in send_events}
    assert "123" in chat_ids
    assert "456" in chat_ids


@pytest.mark.asyncio
async def test_cleanup_skips_non_expired(cleanup, pending_store):
    pending_store.add(_make_draft(), chat_id="123")
    count = await cleanup.run_once()
    assert count == 0
