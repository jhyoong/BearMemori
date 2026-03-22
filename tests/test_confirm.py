from unittest.mock import MagicMock

import pytest

from bearmemori.core.confirm import ConfirmHandler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryStored
from bearmemori.storage.models import MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def pending_store():
    return PendingStore()


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_vector_store():
    return MagicMock()


@pytest.fixture
def handler(bus, pending_store, mock_db, mock_vector_store):
    return ConfirmHandler(
        bus=bus,
        pending_store=pending_store,
        db=mock_db,
        vector_store=mock_vector_store,
    )


def _make_draft(**overrides):
    defaults = dict(category=MemoryCategory.GENERAL, title="Test", content="Test content")
    defaults.update(overrides)
    return MemoryDraft(**defaults)


@pytest.mark.asyncio
async def test_confirm_stores_memory(handler, bus, pending_store, mock_db, mock_vector_store):
    stored_events = []
    bus.on(MemoryStored, lambda e: stored_events.append(e))

    pid = pending_store.add(_make_draft(), chat_id="123")

    await handler.handle_confirmed(MemoryConfirmed(pending_id=pid, source_chat_id="123"))

    mock_db.create.assert_called_once()
    record = mock_db.create.call_args[0][0]
    assert record.title == "Test"
    assert record.category == MemoryCategory.GENERAL

    mock_vector_store.add.assert_called_once_with(record)

    assert pending_store.get(pid) is None
    assert len(stored_events) == 1


@pytest.mark.asyncio
async def test_confirm_nonexistent_is_noop(handler, mock_db):
    event = MemoryConfirmed(pending_id="pend_nonexistent", source_chat_id="123")
    await handler.handle_confirmed(event)
    mock_db.create.assert_not_called()


@pytest.mark.asyncio
async def test_discard_removes_pending(handler, bus, pending_store):
    pid = pending_store.add(_make_draft(), chat_id="123")
    await handler.handle_discarded(MemoryDiscarded(pending_id=pid, source_chat_id="123"))
    assert pending_store.get(pid) is None


@pytest.mark.asyncio
async def test_discard_cleans_up_image(handler, pending_store, tmp_path):
    img = tmp_path / "test.jpg"
    img.write_bytes(b"fake")
    pid = pending_store.add(_make_draft(), chat_id="123", image_path=str(img))

    await handler.handle_discarded(MemoryDiscarded(pending_id=pid, source_chat_id="123"))

    assert not img.exists()
