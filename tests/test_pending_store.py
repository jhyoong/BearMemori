import time

from bearmemori.storage.models import MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore


def _make_draft(**overrides) -> MemoryDraft:
    defaults = dict(
        category=MemoryCategory.PROFILE,
        title="Test",
        content="Test content",
    )
    defaults.update(overrides)
    return MemoryDraft(**defaults)


def test_add_and_get():
    store = PendingStore()
    pid = store.add(_make_draft())
    assert pid.startswith("pend_")
    result = store.get(pid)
    assert result is not None
    assert result.draft.title == "Test"


def test_remove():
    store = PendingStore()
    pid = store.add(_make_draft())
    assert store.remove(pid) is True
    assert store.get(pid) is None


def test_remove_nonexistent():
    store = PendingStore()
    assert store.remove("nonexistent") is False


def test_expiry():
    store = PendingStore(default_ttl=1)
    pid = store.add(_make_draft())
    time.sleep(1.1)
    assert store.get(pid) is None


def test_cleanup():
    store = PendingStore(default_ttl=1)
    store.add(_make_draft())
    store.add(_make_draft())
    time.sleep(1.1)
    removed = store.cleanup()
    assert removed == 2


def test_add_with_chat_id_and_image_path():
    store = PendingStore()
    pid = store.add(_make_draft(), chat_id="123", image_path="/tmp/test.jpg")
    result = store.get(pid)
    assert result is not None
    assert result.chat_id == "123"
    assert result.image_path == "/tmp/test.jpg"


def test_add_stores_message_id():
    store = PendingStore()
    pid = store.add(_make_draft(), chat_id="123")
    result = store.get(pid)
    assert result.chat_id == "123"
    assert result.message_id is None

    store.set_message_id(pid, 42)
    result = store.get(pid)
    assert result.message_id == 42


def test_cleanup_returns_expired_ids():
    store = PendingStore(default_ttl=1)
    pid1 = store.add(_make_draft(), chat_id="123")
    pid2 = store.add(_make_draft(), chat_id="456")
    time.sleep(1.1)
    expired = store.cleanup_with_details()
    assert len(expired) == 2
    expired_ids = {e.pending_id for e in expired}
    assert pid1 in expired_ids
    assert pid2 in expired_ids
