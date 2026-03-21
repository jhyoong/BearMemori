import time

from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.models import MemoryDraft, MemoryCategory


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
