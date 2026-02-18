"""Tests for the database initialization and migration system."""

import aiosqlite
import pytest

from core.database import init_db


async def test_init_db_creates_tables(tmp_path):
    """init_db() creates all expected tables in a fresh database."""
    db_path = str(tmp_path / "test.db")
    db = await init_db(db_path)

    try:
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        rows = await cursor.fetchall()
        table_names = {row[0] for row in rows}
    finally:
        await db.close()

    expected_tables = {
        "audit_log",
        "backup_jobs",
        "backup_metadata",
        "events",
        "llm_jobs",
        "memories",
        "memory_tags",
        "reminders",
        "tasks",
        "users",
        "user_settings",
    }
    assert expected_tables.issubset(table_names)


async def test_init_db_sets_user_version(tmp_path):
    """After init_db(), PRAGMA user_version returns 7 (latest migration)."""
    db_path = str(tmp_path / "test.db")
    db = await init_db(db_path)

    try:
        async with db.execute("PRAGMA user_version") as cursor:
            row = await cursor.fetchone()
            version = row[0]
    finally:
        await db.close()

    assert version == 7


async def test_init_db_idempotent(tmp_path):
    """Calling init_db() twice on the same path does not fail; version remains 7."""
    db_path = str(tmp_path / "test.db")

    db1 = await init_db(db_path)
    await db1.close()

    db2 = await init_db(db_path)
    try:
        async with db2.execute("PRAGMA user_version") as cursor:
            row = await cursor.fetchone()
            version = row[0]
    finally:
        await db2.close()

    assert version == 7


async def test_wal_mode_enabled(tmp_path):
    """After init_db(), journal_mode is WAL."""
    db_path = str(tmp_path / "test.db")
    db = await init_db(db_path)

    try:
        async with db.execute("PRAGMA journal_mode") as cursor:
            row = await cursor.fetchone()
            journal_mode = row[0]
    finally:
        await db.close()

    assert journal_mode == "wal"


async def test_foreign_keys_enabled(tmp_path):
    """After init_db(), PRAGMA foreign_keys returns 1 (enabled)."""
    db_path = str(tmp_path / "test.db")
    db = await init_db(db_path)

    try:
        async with db.execute("PRAGMA foreign_keys") as cursor:
            row = await cursor.fetchone()
            fk_enabled = row[0]
    finally:
        await db.close()

    assert fk_enabled == 1


async def test_foreign_key_constraint(tmp_path):
    """Inserting a memory with a non-existent owner_user_id raises IntegrityError."""
    import uuid

    db_path = str(tmp_path / "test.db")
    db = await init_db(db_path)

    try:
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                """
                INSERT INTO memories (id, owner_user_id, content, status)
                VALUES (?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), 99999, "test content", "confirmed"),
            )
            await db.commit()
    finally:
        await db.close()
