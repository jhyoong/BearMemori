from unittest.mock import MagicMock

import pytest

from bearmemori.core.confirm import ConfirmHandler
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryConfirmed, MemoryDiscarded, MemoryStored
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


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
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


@pytest.fixture
def vector_store():
    return VectorStore()


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
async def test_discard_with_image_bytes_is_noop(handler, pending_store):
    pid = pending_store.add(_make_draft(), chat_id="123", image_bytes=b"fake-image")
    await handler.handle_discarded(MemoryDiscarded(pending_id=pid, source_chat_id="123"))
    assert pending_store.get(pid) is None


@pytest.mark.asyncio
async def test_confirm_saves_image_to_disk(bus, pending_store, mock_db, mock_vector_store, tmp_path):
    handler = ConfirmHandler(
        bus=bus,
        pending_store=pending_store,
        db=mock_db,
        vector_store=mock_vector_store,
        image_storage_dir=str(tmp_path),
    )

    pid = pending_store.add(
        _make_draft(),
        chat_id="123",
        image_bytes=b"fake-jpeg-data",
    )

    await handler.handle_confirmed(MemoryConfirmed(pending_id=pid, source_chat_id="123"))

    record = mock_db.create.call_args[0][0]
    assert record.image_path is not None
    assert record.image_path.endswith(".jpg")

    # Verify file was written to disk
    image_file = tmp_path / f"{record.id}.jpg"
    assert image_file.exists()
    assert image_file.read_bytes() == b"fake-jpeg-data"


@pytest.mark.asyncio
async def test_confirm_without_image_has_no_image_path(handler, pending_store, mock_db):
    pid = pending_store.add(_make_draft(), chat_id="123")
    await handler.handle_confirmed(MemoryConfirmed(pending_id=pid, source_chat_id="123"))

    record = mock_db.create.call_args[0][0]
    assert record.image_path is None


@pytest.mark.asyncio
async def test_confirm_with_needs_review(bus, pending_store, mock_db, mock_vector_store):
    handler = ConfirmHandler(bus, pending_store, mock_db, mock_vector_store)
    draft = MemoryDraft(category=MemoryCategory.GENERAL, title="Test", content="Test content")
    pending_id = pending_store.add(draft, chat_id="123")

    event = MemoryConfirmed(pending_id=pending_id, source_chat_id="123", needs_review=True)
    await handler.handle_confirmed(event)

    # Verify the record stored in db has needs_review=True
    record = mock_db.create.call_args[0][0]
    assert record.needs_review is True

    # Also verify the record was added to vector store
    mock_vector_store.add.assert_called_once()
