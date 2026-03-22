from datetime import UTC, datetime, timedelta

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import (
    EventFields,
    MemoryCategory,
    MemoryRecord,
    MemorySource,
)


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _make_record(**overrides) -> MemoryRecord:
    defaults = dict(
        id="mem_test1",
        category=MemoryCategory.PROFILE,
        title="Test memory",
        content="Test content",
        created_at=datetime.now(UTC),
        tags=["test"],
    )
    defaults.update(overrides)
    return MemoryRecord(**defaults)


def test_create_and_get(db):
    record = _make_record()
    db.create(record)
    result = db.get("mem_test1")
    assert result is not None
    assert result.id == "mem_test1"
    assert result.category == MemoryCategory.PROFILE
    assert result.title == "Test memory"


def test_get_nonexistent(db):
    assert db.get("nonexistent") is None


def test_delete(db):
    db.create(_make_record())
    assert db.delete("mem_test1") is True
    assert db.get("mem_test1") is None


def test_delete_nonexistent(db):
    assert db.delete("nonexistent") is False


def test_list_all(db):
    db.create(_make_record(id="mem_1"))
    db.create(_make_record(id="mem_2", category=MemoryCategory.GENERAL))
    result = db.list_all()
    assert len(result) == 2


def test_list_by_category(db):
    db.create(_make_record(id="mem_1", category=MemoryCategory.PROFILE))
    db.create(_make_record(id="mem_2", category=MemoryCategory.EVENT))
    result = db.list_by_category(MemoryCategory.PROFILE)
    assert len(result) == 1
    assert result[0].id == "mem_1"


def test_event_fields_roundtrip(db):
    record = _make_record(
        category=MemoryCategory.EVENT,
        event_fields=EventFields(
            datetime="2026-03-25T14:00:00",
            status="pending",
            recurrence="weekly",
        ),
    )
    db.create(record)
    result = db.get("mem_test1")
    assert result.event_fields is not None
    assert result.event_fields.datetime == "2026-03-25T14:00:00"
    assert result.event_fields.recurrence == "weekly"


def test_source_roundtrip(db):
    record = _make_record(
        source=MemorySource(platform="telegram", chat_id="123", message_ids=["msg1"]),
    )
    db.create(record)
    result = db.get("mem_test1")
    assert result.source is not None
    assert result.source.platform == "telegram"
    assert result.source.chat_id == "123"


def test_upcoming_events(db):
    now = datetime.now(UTC)
    future = (now + timedelta(days=2)).isoformat()
    past = (now - timedelta(days=2)).isoformat()

    db.create(
        _make_record(
            id="mem_future",
            category=MemoryCategory.EVENT,
            event_fields=EventFields(datetime=future, status="pending"),
        )
    )
    db.create(
        _make_record(
            id="mem_past",
            category=MemoryCategory.EVENT,
            event_fields=EventFields(datetime=past, status="pending"),
        )
    )
    results = db.get_upcoming_events(days=7)
    assert len(results) == 1
    assert results[0].id == "mem_future"


def test_keyword_search(db):
    db.create(_make_record(id="mem_1", title="Coffee preference", content="Likes black coffee"))
    db.create(_make_record(id="mem_2", title="Tea preference", content="Likes green tea"))
    results = db.search_keyword("coffee")
    assert len(results) >= 1
    assert any(r.id == "mem_1" for r in results)


def test_create_memory_with_needs_review(db, sample_record):
    sample_record.needs_review = True
    db.create(sample_record)
    retrieved = db.get(sample_record.id)
    assert retrieved is not None
    assert retrieved.needs_review is True


def test_create_memory_default_needs_review(db, sample_record):
    db.create(sample_record)
    retrieved = db.get(sample_record.id)
    assert retrieved is not None
    assert retrieved.needs_review is False


def test_list_memories_filter_needs_review(db, sample_record):
    db.create(sample_record)

    review_record = sample_record.model_copy(
        update={"id": "mem_review123", "needs_review": True}
    )
    db.create(review_record)

    all_memories = db.list_all()
    assert len(all_memories) == 2

    review_only = db.list_all(needs_review=True)
    assert len(review_only) == 1
    assert review_only[0].id == "mem_review123"

    no_review = db.list_all(needs_review=False)
    assert len(no_review) == 1
    assert no_review[0].id == sample_record.id


def test_update_memory_needs_review(db, sample_record):
    db.create(sample_record)
    sample_record.needs_review = True
    db.update(sample_record)
    retrieved = db.get(sample_record.id)
    assert retrieved.needs_review is True


def test_delete_many(db, sample_record):
    record2 = sample_record.model_copy(update={"id": "mem_second123"})
    record3 = sample_record.model_copy(update={"id": "mem_third1234"})
    db.create(sample_record)
    db.create(record2)
    db.create(record3)
    deleted = db.delete_many([sample_record.id, record2.id])
    assert deleted == 2
    assert db.get(sample_record.id) is None
    assert db.get(record2.id) is None
    assert db.get(record3.id) is not None


@pytest.fixture
def sample_record():
    return _make_record()
