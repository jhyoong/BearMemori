from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryRecord


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _seed(db, mid="mem_x", title="t", cat=MemoryCategory.GENERAL, archived=False):
    record = MemoryRecord(
        id=mid,
        category=cat,
        title=title,
        content="c",
        created_at=datetime.now(UTC),
        archived=archived,
    )
    db.create(record, actor=Actor.API)
    return record


def test_update_writes_update_audit(db):
    record = _seed(db, title="old")
    record.title = "new"
    db.update(record, actor=Actor.WEBAPP)
    entries = db.list_audit(memory_id=record.id)
    actions = [e.action for e in entries]
    assert actions == ["update", "create"]
    update_entry = entries[0]
    assert update_entry.actor == Actor.WEBAPP
    assert update_entry.title_snapshot == "new"


def test_update_archive_transition_writes_archive_action(db):
    record = _seed(db, archived=False)
    record.archived = True
    db.update(record, actor=Actor.API)
    entries = db.list_audit(memory_id=record.id)
    assert entries[0].action == "archive"


def test_update_unarchive_transition_writes_update_action(db):
    record = _seed(db, archived=True)
    record.archived = False
    db.update(record, actor=Actor.API)
    entries = db.list_audit(memory_id=record.id)
    assert entries[0].action == "update"


def test_update_actor_required(db):
    record = _seed(db)
    with pytest.raises(TypeError):
        db.update(record)
