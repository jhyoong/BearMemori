from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _seed(db, memory_id, action, actor, ts, title="t", category="general"):
    db._conn.execute(
        """INSERT INTO audit_log
           (memory_id, action, actor, timestamp, title_snapshot, category_snapshot)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (memory_id, action, actor.value, ts, title, category),
    )
    db._conn.commit()


def test_list_audit_newest_first(db):
    _seed(db, "m1", "create", Actor.API, "2026-04-26T00:00:00+00:00")
    _seed(db, "m2", "create", Actor.WEBAPP, "2026-04-26T01:00:00+00:00")
    entries = db.list_audit()
    assert [e.memory_id for e in entries] == ["m2", "m1"]


def test_list_audit_filter_by_actor(db):
    _seed(db, "m1", "create", Actor.API, "2026-04-26T00:00:00+00:00")
    _seed(db, "m2", "create", Actor.WEBAPP, "2026-04-26T01:00:00+00:00")
    entries = db.list_audit(actor=Actor.WEBAPP)
    assert len(entries) == 1
    assert entries[0].memory_id == "m2"


def test_list_audit_filter_by_action_and_memory(db):
    _seed(db, "m1", "create", Actor.API, "2026-04-26T00:00:00+00:00")
    _seed(db, "m1", "delete", Actor.API, "2026-04-26T01:00:00+00:00")
    _seed(db, "m2", "create", Actor.API, "2026-04-26T02:00:00+00:00")
    entries = db.list_audit(action="delete")
    assert [e.memory_id for e in entries] == ["m1"]
    entries = db.list_audit(memory_id="m1")
    assert len(entries) == 2


def test_list_audit_filter_by_date_range(db):
    _seed(db, "m1", "create", Actor.API, "2026-04-25T00:00:00+00:00")
    _seed(db, "m2", "create", Actor.API, "2026-04-26T12:00:00+00:00")
    _seed(db, "m3", "create", Actor.API, "2026-04-27T00:00:00+00:00")
    entries = db.list_audit(
        start=datetime(2026, 4, 26, tzinfo=UTC),
        end=datetime(2026, 4, 26, 23, 59, tzinfo=UTC),
    )
    assert [e.memory_id for e in entries] == ["m2"]


def test_list_audit_pagination(db):
    for i in range(10):
        _seed(db, f"m{i}", "create", Actor.API, f"2026-04-26T{i:02d}:00:00+00:00")
    entries = db.list_audit(limit=3, offset=2)
    # Newest first: m9, m8, m7, m6, m5, ... offset 2 -> m7, m6, m5
    assert [e.memory_id for e in entries] == ["m7", "m6", "m5"]
