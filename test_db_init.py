#!/usr/bin/env python3
"""Test script to verify database initialization."""

import asyncio
import os
import sys
import tempfile

# Add the core directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'core'))

from core.database import init_db


async def test_database_initialization():
    """Test database initialization and migration system."""

    # Create a temporary database file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.db') as f:
        db_path = f.name

    try:
        print(f"Testing database initialization with: {db_path}")
        print("-" * 60)

        # Test 1: Fresh database initialization
        print("\n1. Testing fresh database creation...")
        conn = await init_db(db_path)

        # Check WAL mode
        cursor = await conn.execute("PRAGMA journal_mode")
        mode = await cursor.fetchone()
        wal_mode = mode[0]
        print(f"   ✓ Journal mode: {wal_mode}")
        assert wal_mode.lower() == 'wal', f"Expected WAL mode, got {wal_mode}"

        # Check foreign keys are enabled
        cursor = await conn.execute("PRAGMA foreign_keys")
        fk_status = await cursor.fetchone()
        fk_enabled = fk_status[0]
        print(f"   ✓ Foreign keys enabled: {bool(fk_enabled)}")
        assert fk_enabled == 1, "Foreign keys should be enabled"

        # Check schema version
        cursor = await conn.execute("PRAGMA user_version")
        version = await cursor.fetchone()
        schema_version = version[0]
        print(f"   ✓ Schema version: {schema_version}")
        assert schema_version == 1, f"Expected version 1, got {schema_version}"

        # Test 2: Check all tables exist
        print("\n2. Checking all tables exist...")
        expected_tables = [
            'users', 'user_settings', 'memories', 'memory_tags',
            'tasks', 'reminders', 'events', 'audit_log',
            'llm_jobs', 'backup_metadata', 'memories_fts'
        ]

        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cursor.fetchall()]

        for table in expected_tables:
            if table in tables:
                print(f"   ✓ Table '{table}' exists")
            else:
                print(f"   ✗ Table '{table}' MISSING")
                assert False, f"Table '{table}' not found"

        # Test 3: Check indexes exist
        print("\n3. Checking indexes exist...")
        expected_indexes = [
            'idx_memories_owner',
            'idx_memories_status',
            'idx_memories_pending_expires',
            'idx_tasks_state',
            'idx_tasks_owner',
            'idx_reminders_fire',
            'idx_events_status',
            'idx_audit_entity'
        ]

        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        indexes = [row[0] for row in await cursor.fetchall()]

        for index in expected_indexes:
            if index in indexes:
                print(f"   ✓ Index '{index}' exists")
            else:
                print(f"   ✗ Index '{index}' MISSING")
                assert False, f"Index '{index}' not found"

        # Test 4: Check FTS5 virtual table
        print("\n4. Checking FTS5 virtual table...")
        cursor = await conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memories_fts'"
        )
        fts_sql = await cursor.fetchone()
        if fts_sql:
            print(f"   ✓ FTS5 table 'memories_fts' exists")
            print(f"   SQL: {fts_sql[0]}")
        else:
            print(f"   ✗ FTS5 table MISSING")
            assert False, "FTS5 table not found"

        # Test 5: Test foreign key constraints
        print("\n5. Testing foreign key constraints...")
        try:
            # Try to insert a memory with non-existent user (should fail)
            await conn.execute(
                "INSERT INTO memories (id, owner_user_id, content) VALUES ('test-1', 99999, 'test')"
            )
            await conn.commit()
            print("   ✗ Foreign key constraint NOT enforced")
            assert False, "Foreign key constraint should have failed"
        except Exception as e:
            print(f"   ✓ Foreign key constraint enforced (error: {str(e)[:50]}...)")

        # Test 6: Idempotent re-initialization
        print("\n6. Testing idempotent re-initialization...")
        await conn.close()

        conn2 = await init_db(db_path)
        cursor = await conn2.execute("PRAGMA user_version")
        version2 = await cursor.fetchone()
        schema_version2 = version2[0]
        print(f"   ✓ Schema version after re-init: {schema_version2}")
        assert schema_version2 == 1, "Version should still be 1"

        await conn2.close()

        print("\n" + "=" * 60)
        print("ALL TESTS PASSED!")
        print("=" * 60)

    finally:
        # Clean up
        if os.path.exists(db_path):
            os.unlink(db_path)
        # Also clean up WAL files
        for suffix in ['-wal', '-shm']:
            wal_file = db_path + suffix
            if os.path.exists(wal_file):
                os.unlink(wal_file)


if __name__ == '__main__':
    asyncio.run(test_database_initialization())
