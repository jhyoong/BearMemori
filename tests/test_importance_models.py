from datetime import UTC, datetime

from bearmemori.storage.models import (
    MemoryCategory,
    MemoryDraft,
    MemoryRecord,
    PendingMemory,
)


def test_memory_record_default_importance():
    record = MemoryRecord(
        id="mem_test",
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        created_at=datetime.now(UTC),
    )
    assert record.importance == 5


def test_memory_record_custom_importance():
    record = MemoryRecord(
        id="mem_test",
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        created_at=datetime.now(UTC),
        importance=9,
    )
    assert record.importance == 9


def test_memory_draft_default_importance():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
    )
    assert draft.importance == 5


def test_memory_draft_custom_importance():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        importance=8,
    )
    assert draft.importance == 8


def test_pending_memory_importance():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        importance=7,
    )
    pending = PendingMemory(
        pending_id="pend_test",
        draft=draft,
        ttl_seconds=3600,
    )
    assert pending.draft.importance == 7


def test_from_draft_preserves_importance():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        importance=8,
    )
    record = MemoryRecord.from_draft(draft, "mem_test")
    assert record.importance == 8
