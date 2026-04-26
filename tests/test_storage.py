from datetime import UTC, datetime, timedelta

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import (
    Actor,
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
    db.create(record, actor=Actor.API)
    result = db.get("mem_test1")
    assert result is not None
    assert result.id == "mem_test1"
    assert result.category == MemoryCategory.PROFILE
    assert result.title == "Test memory"


def test_get_nonexistent(db):
    assert db.get("nonexistent") is None


def test_delete(db):
    db.create(_make_record(), actor=Actor.API)
    assert db.delete("mem_test1", actor=Actor.API) is True
    assert db.get("mem_test1") is None


def test_delete_nonexistent(db):
    assert db.delete("nonexistent", actor=Actor.API) is False


def test_list_all(db):
    db.create(_make_record(id="mem_1"), actor=Actor.API)
    db.create(_make_record(id="mem_2", category=MemoryCategory.GENERAL), actor=Actor.API)
    result = db.list_all()
    assert len(result) == 2


def test_list_by_category(db):
    db.create(_make_record(id="mem_1", category=MemoryCategory.PROFILE), actor=Actor.API)
    db.create(_make_record(id="mem_2", category=MemoryCategory.EVENT), actor=Actor.API)
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
    db.create(record, actor=Actor.API)
    result = db.get("mem_test1")
    assert result.event_fields is not None
    assert result.event_fields.datetime == "2026-03-25T14:00:00+00:00"
    assert result.event_fields.recurrence == "weekly"


def test_source_roundtrip(db):
    record = _make_record(
        source=MemorySource(platform="telegram", chat_id="123", message_ids=["msg1"]),
    )
    db.create(record, actor=Actor.API)
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
        ),
        actor=Actor.API,
    )
    db.create(
        _make_record(
            id="mem_past",
            category=MemoryCategory.EVENT,
            event_fields=EventFields(datetime=past, status="pending"),
        ),
        actor=Actor.API,
    )
    results = db.get_upcoming_events(days=7)
    assert len(results) == 1
    assert results[0].id == "mem_future"


def test_keyword_search(db):
    db.create(
        _make_record(id="mem_1", title="Coffee preference", content="Likes black coffee"),
        actor=Actor.API,
    )
    db.create(
        _make_record(id="mem_2", title="Tea preference", content="Likes green tea"),
        actor=Actor.API,
    )
    results = db.search_keyword("coffee")
    assert len(results) >= 1
    assert any(r.id == "mem_1" for r in results)


def test_create_memory_with_needs_review(db, sample_record):
    sample_record.needs_review = True
    db.create(sample_record, actor=Actor.API)
    retrieved = db.get(sample_record.id)
    assert retrieved is not None
    assert retrieved.needs_review is True


def test_create_memory_default_needs_review(db, sample_record):
    db.create(sample_record, actor=Actor.API)
    retrieved = db.get(sample_record.id)
    assert retrieved is not None
    assert retrieved.needs_review is False


def test_list_memories_filter_needs_review(db, sample_record):
    db.create(sample_record, actor=Actor.API)

    review_record = sample_record.model_copy(update={"id": "mem_review123", "needs_review": True})
    db.create(review_record, actor=Actor.API)

    all_memories = db.list_all()
    assert len(all_memories) == 2

    review_only = db.list_all(needs_review=True)
    assert len(review_only) == 1
    assert review_only[0].id == "mem_review123"

    no_review = db.list_all(needs_review=False)
    assert len(no_review) == 1
    assert no_review[0].id == sample_record.id


def test_update_memory_needs_review(db, sample_record):
    db.create(sample_record, actor=Actor.API)
    sample_record.needs_review = True
    db.update(sample_record, actor=Actor.API)
    retrieved = db.get(sample_record.id)
    assert retrieved.needs_review is True


def test_delete_many(db, sample_record):
    record2 = sample_record.model_copy(update={"id": "mem_second123"})
    record3 = sample_record.model_copy(update={"id": "mem_third1234"})
    db.create(sample_record, actor=Actor.API)
    db.create(record2, actor=Actor.API)
    db.create(record3, actor=Actor.API)
    deleted = db.delete_many([sample_record.id, record2.id], actor=Actor.API)
    assert deleted == 2
    assert db.get(sample_record.id) is None
    assert db.get(record2.id) is None
    assert db.get(record3.id) is not None


def test_create_and_get_with_image_path(db):
    record = _make_record(id="mem_img1", image_path="images/mem_img1.jpg")
    db.create(record, actor=Actor.API)
    result = db.get("mem_img1")
    assert result is not None
    assert result.image_path == "images/mem_img1.jpg"


def test_image_path_defaults_to_none(db):
    record = _make_record(id="mem_noimg")
    db.create(record, actor=Actor.API)
    result = db.get("mem_noimg")
    assert result is not None
    assert result.image_path is None


def test_create_normalizes_event_datetime_to_utc(db):
    """Event datetime with non-UTC offset should be stored as UTC."""
    record = _make_record(
        id="mem_tz1",
        category=MemoryCategory.REMINDER,
        event_fields=EventFields(
            datetime="2026-03-25T23:34:00+08:00",
            status="pending",
        ),
    )
    db.create(record, actor=Actor.API)
    result = db.get("mem_tz1")
    # +08:00 offset means 15:34 UTC
    assert result.event_fields.datetime == "2026-03-25T15:34:00+00:00"


def test_update_normalizes_event_datetime_to_utc(db):
    """Event datetime should be normalized on update too."""
    record = _make_record(
        id="mem_tz2",
        category=MemoryCategory.REMINDER,
        event_fields=EventFields(
            datetime="2026-03-25T12:00:00+00:00",
            status="pending",
        ),
    )
    db.create(record, actor=Actor.API)

    record.event_fields = EventFields(
        datetime="2026-03-26T10:00:00+05:30",
        status="pending",
    )
    db.update(record, actor=Actor.API)
    result = db.get("mem_tz2")
    # +05:30 offset means 04:30 UTC
    assert result.event_fields.datetime == "2026-03-26T04:30:00+00:00"


def test_get_due_events_finds_non_utc_reminder(db):
    """Non-UTC offset reminder should be found by get_due_events after normalization."""
    from datetime import datetime as dt
    from unittest.mock import patch as mock_patch

    # Event at 23:34 +08:00 = 15:34 UTC
    record = _make_record(
        id="mem_due_tz",
        category=MemoryCategory.REMINDER,
        event_fields=EventFields(
            datetime="2026-03-25T23:34:00+08:00",
            status="pending",
        ),
    )
    db.create(record, actor=Actor.API)

    # Mock "now" to 16:00 UTC (after 15:34 UTC)
    fake_now = dt(2026, 3, 25, 16, 0, 0, tzinfo=UTC)
    with mock_patch("bearmemori.storage.database.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        mock_dt.fromisoformat = dt.fromisoformat
        due = db.get_due_events()

    assert len(due) == 1
    assert due[0].id == "mem_due_tz"


def test_create_normalizes_naive_datetime(db):
    """Naive datetime (no timezone) should be stored as-is with +00:00 suffix."""
    record = _make_record(
        id="mem_naive",
        category=MemoryCategory.REMINDER,
        event_fields=EventFields(
            datetime="2026-03-25T15:00:00",
            status="pending",
        ),
    )
    db.create(record, actor=Actor.API)
    result = db.get("mem_naive")
    assert result.event_fields.datetime == "2026-03-25T15:00:00+00:00"


def test_count_all(db):
    assert db.count_all() == 0
    db.create(_make_record(id="mem_c1"), actor=Actor.API)
    db.create(_make_record(id="mem_c2"), actor=Actor.API)
    assert db.count_all() == 2


def test_count_needs_review(db):
    assert db.count_needs_review() == 0
    db.create(_make_record(id="mem_nr1", needs_review=True), actor=Actor.API)
    db.create(_make_record(id="mem_nr2", needs_review=False), actor=Actor.API)
    db.create(_make_record(id="mem_nr3", needs_review=True), actor=Actor.API)
    assert db.count_needs_review() == 2


def test_count_recent(db):
    result = db.count_recent(hours=24)
    assert result == {"created": 0, "updated": 0}
    db.create(_make_record(id="mem_r1"), actor=Actor.API)
    db.create(_make_record(id="mem_r2"), actor=Actor.API)
    result = db.count_recent(hours=24)
    assert result["created"] == 2
    assert result["updated"] == 2


def test_list_recently_updated(db):
    now = datetime.now(UTC)
    db.create(_make_record(id="mem_lu1"), actor=Actor.API)
    db.create(_make_record(id="mem_lu2"), actor=Actor.API)
    since = now - timedelta(hours=1)
    results = db.list_recently_updated(since=since, limit=50)
    assert len(results) == 2
    future = now + timedelta(hours=1)
    results = db.list_recently_updated(since=future, limit=50)
    assert len(results) == 0


def test_list_recently_updated_respects_limit(db):
    db.create(_make_record(id="mem_lim1"), actor=Actor.API)
    db.create(_make_record(id="mem_lim2"), actor=Actor.API)
    db.create(_make_record(id="mem_lim3"), actor=Actor.API)
    since = datetime.now(UTC) - timedelta(hours=1)
    results = db.list_recently_updated(since=since, limit=2)
    assert len(results) == 2


@pytest.fixture
def sample_record():
    return _make_record()
