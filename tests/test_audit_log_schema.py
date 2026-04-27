import sqlite3

from bearmemori.storage.database import MemoryDatabase


def test_audit_log_table_created(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
    assert cols == {
        "id",
        "memory_id",
        "action",
        "actor",
        "timestamp",
        "title_snapshot",
        "category_snapshot",
    }
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(audit_log)")}
    assert "idx_audit_log_timestamp" in indexes
    assert "idx_audit_log_memory_id" in indexes
    assert "idx_audit_log_actor" in indexes


def test_audit_log_migration_on_existing_db(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            raw_input TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            source TEXT,
            event_datetime TEXT,
            event_status TEXT,
            event_recurrence TEXT,
            metadata TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    legacy.commit()
    legacy.close()

    db = MemoryDatabase(db_path)
    db.initialize()

    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
    assert "memory_id" in cols
