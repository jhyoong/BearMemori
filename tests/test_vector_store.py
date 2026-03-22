from datetime import UTC, datetime

import pytest

from bearmemori.storage.models import EventFields, MemoryCategory, MemoryRecord
from bearmemori.storage.vector_store import VectorStore


@pytest.fixture
def store(tmp_path):
    vs = VectorStore(persist_dir=str(tmp_path / "chroma"))
    vs.init()
    return vs


def _make_record(**overrides) -> MemoryRecord:
    defaults = dict(
        id="mem_test1",
        category=MemoryCategory.PROFILE,
        title="Coffee preference",
        content="User likes black coffee",
        created_at=datetime.now(UTC),
        tags=["coffee"],
    )
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def test_add_and_search(store):
    store.add(_make_record())
    results = store.search("coffee", top_k=5)
    assert len(results) >= 1
    assert results[0]["id"] == "mem_test1"


def test_search_with_category_filter(store):
    store.add(_make_record(id="mem_1", category=MemoryCategory.PROFILE))
    store.add(
        _make_record(
            id="mem_2",
            category=MemoryCategory.EVENT,
            title="Meeting",
            content="Team meeting",
        )
    )
    results = store.search("meeting", top_k=5, category="event")
    assert all(r["metadata"]["category"] == "event" for r in results)


def test_delete(store):
    store.add(_make_record())
    store.delete("mem_test1")
    results = store.search("coffee", top_k=5)
    assert not any(r["id"] == "mem_test1" for r in results)


def test_event_metadata(store):
    record = _make_record(
        category=MemoryCategory.EVENT,
        event_fields=EventFields(datetime="2026-03-25T14:00:00"),
    )
    store.add(record)
    results = store.search("coffee", top_k=5)
    assert results[0]["metadata"]["event_datetime"] == "2026-03-25T14:00:00"
