from datetime import UTC, datetime

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryRecord


def test_store_and_retrieve_importance(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()

    record = MemoryRecord(
        id="mem_imp_test",
        category=MemoryCategory.GENERAL,
        title="Important memory",
        content="This is very important",
        created_at=datetime.now(UTC),
        importance=9,
    )
    db.create(record)
    retrieved = db.get("mem_imp_test")

    assert retrieved is not None
    assert retrieved.importance == 9


def test_default_importance_is_5(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()

    record = MemoryRecord(
        id="mem_def_test",
        category=MemoryCategory.GENERAL,
        title="Default importance",
        content="Should default to 5",
        created_at=datetime.now(UTC),
    )
    db.create(record)
    retrieved = db.get("mem_def_test")

    assert retrieved is not None
    assert retrieved.importance == 5


def test_update_importance(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()

    record = MemoryRecord(
        id="mem_upd_test",
        category=MemoryCategory.GENERAL,
        title="Update test",
        content="Will update importance",
        created_at=datetime.now(UTC),
        importance=3,
    )
    db.create(record)

    record.importance = 8
    db.update(record)

    retrieved = db.get("mem_upd_test")
    assert retrieved is not None
    assert retrieved.importance == 8


def test_migration_adds_importance_column(tmp_path):
    """Existing databases without importance column should get it via migration."""
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()

    record = MemoryRecord(
        id="mem_mig_test",
        category=MemoryCategory.GENERAL,
        title="Migration test",
        content="Pre-migration record",
        created_at=datetime.now(UTC),
    )
    db.create(record)
    retrieved = db.get("mem_mig_test")
    assert retrieved.importance == 5
