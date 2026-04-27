from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryRecord


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def test_audit_row_not_committed_when_memory_insert_fails(db, monkeypatch):
    record = MemoryRecord(
        id="mem_dup",
        category=MemoryCategory.GENERAL,
        title="t",
        content="c",
        created_at=datetime.now(UTC),
    )
    db.create(record, actor=Actor.API)

    duplicate = MemoryRecord(
        id="mem_dup",  # PK collision
        category=MemoryCategory.GENERAL,
        title="t2",
        content="c",
        created_at=datetime.now(UTC),
    )
    with pytest.raises(Exception):
        db.create(duplicate, actor=Actor.WEBAPP)

    entries = db.list_audit(memory_id="mem_dup")
    actors = {e.actor for e in entries}
    # only the original create's audit row exists
    assert actors == {Actor.API}
    assert len([e for e in entries if e.action == "create"]) == 1
