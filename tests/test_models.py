from bearmemori.storage.models import (
    EventFields,
    MemoryCategory,
    MemoryDraft,
    MemoryRecord,
    PendingMemory,
)


def test_memory_category_values():
    assert MemoryCategory.PROFILE == "profile"
    assert MemoryCategory.GENERAL == "general"
    assert MemoryCategory.EVENT == "event"
    assert MemoryCategory.LOCATION == "location"
    assert MemoryCategory.TASK == "task"
    assert MemoryCategory.REMINDER == "reminder"


def test_memory_draft_creation():
    draft = MemoryDraft(
        category=MemoryCategory.PROFILE,
        title="Likes coffee",
        content="User prefers black coffee in the morning",
        tags=["preference", "coffee"],
    )
    assert draft.title == "Likes coffee"
    assert draft.event_fields is None
    assert draft.source is None


def test_memory_record_from_draft():
    draft = MemoryDraft(
        category=MemoryCategory.EVENT,
        title="Dentist appointment",
        content="Dentist at 2pm on Friday",
        event_fields=EventFields(datetime="2026-03-25T14:00:00"),
        tags=["health"],
    )
    record = MemoryRecord.from_draft(draft, record_id="mem_abc123")
    assert record.id == "mem_abc123"
    assert record.category == MemoryCategory.EVENT
    assert record.title == "Dentist appointment"
    assert record.event_fields.datetime == "2026-03-25T14:00:00"
    assert record.event_fields.status == "pending"
    assert record.created_at is not None


def test_pending_memory_creation():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
    )
    pm = PendingMemory(
        pending_id="pend_abc123",
        draft=draft,
        ttl_seconds=3600,
    )
    assert pm.pending_id == "pend_abc123"
    assert pm.ttl_seconds == 3600
    assert pm.created_at is not None


def test_memory_record_needs_review_default():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
    )
    record = MemoryRecord.from_draft(draft, "mem_test123")
    assert record.needs_review is False


def test_memory_record_needs_review_set():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
    )
    record = MemoryRecord.from_draft(draft, "mem_test123")
    record.needs_review = True
    assert record.needs_review is True
