from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryRecord


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _record(record_id="mem_x", title="hello", category=MemoryCategory.GENERAL):
    return MemoryRecord(
        id=record_id,
        category=category,
        title=title,
        content="content",
        created_at=datetime.now(UTC),
    )


def test_create_writes_audit_row(db):
    db.create(_record("mem_a", title="alpha"), actor=Actor.API)
    entries = db.list_audit()
    assert len(entries) == 1
    e = entries[0]
    assert e.memory_id == "mem_a"
    assert e.action == "create"
    assert e.actor == Actor.API
    assert e.title_snapshot == "alpha"
    assert e.category_snapshot == "general"


def test_create_actor_required(db):
    with pytest.raises(TypeError):
        db.create(_record())  # missing actor
