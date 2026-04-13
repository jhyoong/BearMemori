from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryRecord


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _make_record(record_id: str, importance: int = 5) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        created_at=datetime.now(UTC),
        importance=importance,
    )


def test_record_archived_defaults_false(db):
    r = _make_record("mem_001")
    db.create(r)
    fetched = db.get("mem_001")
    assert fetched.archived is False


def test_archive_record_hides_from_list_all(db):
    r = _make_record("mem_002")
    db.create(r)
    r.archived = True
    db.update(r)
    records = db.list_all()
    assert not any(rec.id == "mem_002" for rec in records)


def test_list_archived_returns_archived(db):
    r = _make_record("mem_003")
    db.create(r)
    r.archived = True
    db.update(r)
    archived = db.list_archived()
    assert any(rec.id == "mem_003" for rec in archived)


def test_archived_record_hidden_from_list_by_category(db):
    r = _make_record("mem_004")
    db.create(r)
    r.archived = True
    db.update(r)
    records = db.list_by_category(MemoryCategory.GENERAL)
    assert not any(rec.id == "mem_004" for rec in records)


def test_count_all_excludes_archived(db):
    r1 = _make_record("mem_005")
    r2 = _make_record("mem_006")
    db.create(r1)
    db.create(r2)
    r2.archived = True
    db.update(r2)
    assert db.count_all() == 1
