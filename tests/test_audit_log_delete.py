from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryRecord


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _seed(db, mid, title, cat=MemoryCategory.GENERAL):
    db.create(
        MemoryRecord(
            id=mid,
            category=cat,
            title=title,
            content="c",
            created_at=datetime.now(UTC),
        ),
        actor=Actor.API,
    )


def test_delete_writes_audit_row_with_snapshot(db):
    _seed(db, "mem_x", "to-delete", MemoryCategory.EVENT)
    db.delete("mem_x", actor=Actor.WEBAPP)
    entries = db.list_audit(memory_id="mem_x")
    assert [e.action for e in entries] == ["delete", "create"]
    delete_entry = entries[0]
    assert delete_entry.actor == Actor.WEBAPP
    assert delete_entry.title_snapshot == "to-delete"
    assert delete_entry.category_snapshot == "event"


def test_delete_missing_memory_writes_no_audit(db):
    deleted = db.delete("does_not_exist", actor=Actor.API)
    assert deleted is False
    entries = db.list_audit(action="delete")
    assert entries == []


def test_delete_many_writes_one_audit_per_id(db):
    _seed(db, "m1", "one")
    _seed(db, "m2", "two")
    _seed(db, "m3", "three")
    deleted = db.delete_many(["m1", "m2", "missing"], actor=Actor.REFLECTION)
    assert deleted == 2
    entries = db.list_audit(action="delete")
    assert {e.memory_id for e in entries} == {"m1", "m2"}
    assert all(e.actor == Actor.REFLECTION for e in entries)
    titles = {e.memory_id: e.title_snapshot for e in entries}
    assert titles == {"m1": "one", "m2": "two"}


def test_delete_many_empty_list(db):
    assert db.delete_many([], actor=Actor.API) == 0
    assert db.list_audit(action="delete") == []
