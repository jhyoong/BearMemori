"""Test Audit router."""

import asyncio
import aiosqlite
import json
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone

# Import the modules to test
import sys
sys.path.insert(0, str(Path(__file__).parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent / 'shared'))

from core_svc.database import init_db
from core_svc.routers.audit import (
    get_audit_logs,
    parse_actor_to_user_id,
)
from shared_lib.enums import EntityType, AuditAction


async def setup_test_db():
    """Create a temporary test database with schema."""
    db_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.db')
    db_path = db_file.name
    db_file.close()

    # Initialize database with schema
    db = await init_db(db_path)

    # Create test users
    await db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (123456, "testuser", 1)
    )
    await db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (999999, "otheruser", 1)
    )
    await db.commit()

    # Create test audit log entries
    test_entries = [
        # Memory entries
        ("memory", "mem-001", "created", "user:123456", json.dumps({"content": "test memory"})),
        ("memory", "mem-001", "updated", "user:123456", json.dumps({"status": "confirmed"})),
        ("memory", "mem-002", "created", "user:999999", None),
        ("memory", "mem-001", "deleted", "user:123456", None),

        # Task entries
        ("task", "task-001", "created", "user:123456", json.dumps({"description": "test task"})),
        ("task", "task-001", "updated", "user:123456", json.dumps({"state": "DONE"})),
        ("task", "task-002", "created", "user:999999", None),

        # Reminder entries
        ("reminder", "rem-001", "created", "user:123456", None),
        ("reminder", "rem-001", "fired", "system:scheduler", json.dumps({"fire_at": "2024-01-01T10:00:00Z"})),

        # Event entries
        ("event", "evt-001", "created", "user:123456", None),
        ("event", "evt-001", "confirmed", "user:123456", None),

        # LLM job entries
        ("llm_job", "job-001", "created", "system:llm_worker", None),
        ("llm_job", "job-001", "updated", "system:llm_worker", json.dumps({"status": "completed"})),
    ]

    for entity_type, entity_id, action, actor, detail in test_entries:
        await db.execute(
            "INSERT INTO audit_log (entity_type, entity_id, action, actor, detail) VALUES (?, ?, ?, ?, ?)",
            (entity_type, entity_id, action, actor, detail)
        )

    await db.commit()

    return db, db_path


async def cleanup_test_db(db, db_path):
    """Close and remove test database."""
    await db.close()
    os.unlink(db_path)


async def test_get_all_audit_logs():
    """Test getting all audit logs without filters."""
    print("\n" + "="*60)
    print("TESTING GET ALL AUDIT LOGS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Fetching all audit logs...")
        result = await get_audit_logs(db=db)

        assert len(result) == 13, f"Should have 13 audit log entries, got {len(result)}"
        print(f"   ✓ Retrieved {len(result)} audit log entries")

        # Verify entries are ordered by created_at DESC (newest first)
        for i in range(len(result) - 1):
            assert result[i].created_at >= result[i+1].created_at, "Entries should be ordered by created_at DESC"
        print("   ✓ Entries are ordered by created_at DESC")

        # Verify first entry (newest)
        first = result[0]
        assert first.entity_type == EntityType.llm_job, "First entry should be llm_job"
        assert first.action == AuditAction.updated, "First entry action should be updated"
        assert first.user_id == 0, "System actions should have user_id = 0"
        print(f"   ✓ First entry: entity_type={first.entity_type}, action={first.action}, user_id={first.user_id}")

        print("\n" + "-"*60)
        print("✓ GET ALL AUDIT LOGS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_filter_by_entity_type():
    """Test filtering audit logs by entity_type."""
    print("\n" + "="*60)
    print("TESTING FILTER BY ENTITY TYPE")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Filtering by entity_type=memory...")
        result = await get_audit_logs(entity_type=EntityType.memory, db=db)

        assert len(result) == 4, f"Should have 4 memory entries, got {len(result)}"
        for entry in result:
            assert entry.entity_type == EntityType.memory, "All entries should be memory type"
        print(f"   ✓ Retrieved {len(result)} memory entries")

        print("\n2. Filtering by entity_type=task...")
        result = await get_audit_logs(entity_type=EntityType.task, db=db)

        assert len(result) == 3, f"Should have 3 task entries, got {len(result)}"
        for entry in result:
            assert entry.entity_type == EntityType.task, "All entries should be task type"
        print(f"   ✓ Retrieved {len(result)} task entries")

        print("\n3. Filtering by entity_type=reminder...")
        result = await get_audit_logs(entity_type=EntityType.reminder, db=db)

        assert len(result) == 2, f"Should have 2 reminder entries, got {len(result)}"
        for entry in result:
            assert entry.entity_type == EntityType.reminder, "All entries should be reminder type"
        print(f"   ✓ Retrieved {len(result)} reminder entries")

        print("\n4. Filtering by entity_type=event...")
        result = await get_audit_logs(entity_type=EntityType.event, db=db)

        assert len(result) == 2, f"Should have 2 event entries, got {len(result)}"
        for entry in result:
            assert entry.entity_type == EntityType.event, "All entries should be event type"
        print(f"   ✓ Retrieved {len(result)} event entries")

        print("\n5. Filtering by entity_type=llm_job...")
        result = await get_audit_logs(entity_type=EntityType.llm_job, db=db)

        assert len(result) == 2, f"Should have 2 llm_job entries, got {len(result)}"
        for entry in result:
            assert entry.entity_type == EntityType.llm_job, "All entries should be llm_job type"
        print(f"   ✓ Retrieved {len(result)} llm_job entries")

        print("\n" + "-"*60)
        print("✓ FILTER BY ENTITY TYPE TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_filter_by_entity_id():
    """Test filtering audit logs by entity_id."""
    print("\n" + "="*60)
    print("TESTING FILTER BY ENTITY ID")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Filtering by entity_id=mem-001...")
        result = await get_audit_logs(entity_id="mem-001", db=db)

        assert len(result) == 3, f"Should have 3 entries for mem-001, got {len(result)}"
        for entry in result:
            assert entry.entity_id == "mem-001", "All entries should be for mem-001"
        print(f"   ✓ Retrieved {len(result)} entries for mem-001")

        # Verify order: deleted, updated, created
        assert result[0].action == AuditAction.deleted, "First should be deleted"
        assert result[1].action == AuditAction.updated, "Second should be updated"
        assert result[2].action == AuditAction.created, "Third should be created"
        print("   ✓ Entries are in correct order (newest first)")

        print("\n2. Filtering by entity_id=task-001...")
        result = await get_audit_logs(entity_id="task-001", db=db)

        assert len(result) == 2, f"Should have 2 entries for task-001, got {len(result)}"
        for entry in result:
            assert entry.entity_id == "task-001", "All entries should be for task-001"
        print(f"   ✓ Retrieved {len(result)} entries for task-001")

        print("\n3. Filtering by entity_id=rem-001...")
        result = await get_audit_logs(entity_id="rem-001", db=db)

        assert len(result) == 2, f"Should have 2 entries for rem-001, got {len(result)}"
        for entry in result:
            assert entry.entity_id == "rem-001", "All entries should be for rem-001"
        print(f"   ✓ Retrieved {len(result)} entries for rem-001")

        print("\n4. Filtering by non-existent entity_id...")
        result = await get_audit_logs(entity_id="non-existent", db=db)

        assert len(result) == 0, "Should have 0 entries for non-existent entity"
        print("   ✓ Returns empty list for non-existent entity")

        print("\n" + "-"*60)
        print("✓ FILTER BY ENTITY ID TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_filter_by_action():
    """Test filtering audit logs by action."""
    print("\n" + "="*60)
    print("TESTING FILTER BY ACTION")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Filtering by action=created...")
        result = await get_audit_logs(action=AuditAction.created, db=db)

        assert len(result) == 7, f"Should have 7 created entries, got {len(result)}"
        for entry in result:
            assert entry.action == AuditAction.created, "All entries should be created"
        print(f"   ✓ Retrieved {len(result)} created entries")

        print("\n2. Filtering by action=updated...")
        result = await get_audit_logs(action=AuditAction.updated, db=db)

        assert len(result) == 3, f"Should have 3 updated entries, got {len(result)}"
        for entry in result:
            assert entry.action == AuditAction.updated, "All entries should be updated"
        print(f"   ✓ Retrieved {len(result)} updated entries")

        print("\n3. Filtering by action=deleted...")
        result = await get_audit_logs(action=AuditAction.deleted, db=db)

        assert len(result) == 1, f"Should have 1 deleted entry, got {len(result)}"
        for entry in result:
            assert entry.action == AuditAction.deleted, "All entries should be deleted"
        print(f"   ✓ Retrieved {len(result)} deleted entries")

        print("\n4. Filtering by action=fired...")
        result = await get_audit_logs(action=AuditAction.fired, db=db)

        assert len(result) == 1, f"Should have 1 fired entry, got {len(result)}"
        for entry in result:
            assert entry.action == AuditAction.fired, "All entries should be fired"
        print(f"   ✓ Retrieved {len(result)} fired entries")

        print("\n5. Filtering by action=confirmed...")
        result = await get_audit_logs(action=AuditAction.confirmed, db=db)

        assert len(result) == 1, f"Should have 1 confirmed entry, got {len(result)}"
        for entry in result:
            assert entry.action == AuditAction.confirmed, "All entries should be confirmed"
        print(f"   ✓ Retrieved {len(result)} confirmed entries")

        print("\n" + "-"*60)
        print("✓ FILTER BY ACTION TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_filter_by_actor():
    """Test filtering audit logs by actor."""
    print("\n" + "="*60)
    print("TESTING FILTER BY ACTOR")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Filtering by actor=user:123456...")
        result = await get_audit_logs(actor="user:123456", db=db)

        assert len(result) == 8, f"Should have 8 entries for user:123456, got {len(result)}"
        for entry in result:
            assert entry.user_id == 123456, "All entries should be for user 123456"
        print(f"   ✓ Retrieved {len(result)} entries for user:123456")

        print("\n2. Filtering by actor=user:999999...")
        result = await get_audit_logs(actor="user:999999", db=db)

        assert len(result) == 2, f"Should have 2 entries for user:999999, got {len(result)}"
        for entry in result:
            assert entry.user_id == 999999, "All entries should be for user 999999"
        print(f"   ✓ Retrieved {len(result)} entries for user:999999")

        print("\n3. Filtering by actor=system:scheduler...")
        result = await get_audit_logs(actor="system:scheduler", db=db)

        assert len(result) == 1, f"Should have 1 entry for system:scheduler, got {len(result)}"
        for entry in result:
            assert entry.user_id == 0, "System entries should have user_id = 0"
        print(f"   ✓ Retrieved {len(result)} entries for system:scheduler")

        print("\n4. Filtering by actor=system:llm_worker...")
        result = await get_audit_logs(actor="system:llm_worker", db=db)

        assert len(result) == 2, f"Should have 2 entries for system:llm_worker, got {len(result)}"
        for entry in result:
            assert entry.user_id == 0, "System entries should have user_id = 0"
        print(f"   ✓ Retrieved {len(result)} entries for system:llm_worker")

        print("\n" + "-"*60)
        print("✓ FILTER BY ACTOR TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_combined_filters():
    """Test combining multiple filters."""
    print("\n" + "="*60)
    print("TESTING COMBINED FILTERS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Filtering by entity_type=memory AND actor=user:123456...")
        result = await get_audit_logs(
            entity_type=EntityType.memory,
            actor="user:123456",
            db=db
        )

        assert len(result) == 3, f"Should have 3 entries, got {len(result)}"
        for entry in result:
            assert entry.entity_type == EntityType.memory, "All entries should be memory type"
            assert entry.user_id == 123456, "All entries should be for user 123456"
        print(f"   ✓ Retrieved {len(result)} memory entries for user:123456")

        print("\n2. Filtering by entity_type=task AND action=created...")
        result = await get_audit_logs(
            entity_type=EntityType.task,
            action=AuditAction.created,
            db=db
        )

        assert len(result) == 2, f"Should have 2 entries, got {len(result)}"
        for entry in result:
            assert entry.entity_type == EntityType.task, "All entries should be task type"
            assert entry.action == AuditAction.created, "All entries should be created"
        print(f"   ✓ Retrieved {len(result)} task created entries")

        print("\n3. Filtering by entity_id=mem-001 AND action=updated...")
        result = await get_audit_logs(
            entity_id="mem-001",
            action=AuditAction.updated,
            db=db
        )

        assert len(result) == 1, f"Should have 1 entry, got {len(result)}"
        assert result[0].entity_id == "mem-001", "Entry should be for mem-001"
        assert result[0].action == AuditAction.updated, "Entry should be updated"
        print(f"   ✓ Retrieved {len(result)} updated entry for mem-001")

        print("\n4. Filtering by all parameters...")
        result = await get_audit_logs(
            entity_type=EntityType.memory,
            entity_id="mem-001",
            action=AuditAction.updated,
            actor="user:123456",
            db=db
        )

        assert len(result) == 1, f"Should have 1 entry, got {len(result)}"
        entry = result[0]
        assert entry.entity_type == EntityType.memory, "Should be memory type"
        assert entry.entity_id == "mem-001", "Should be mem-001"
        assert entry.action == AuditAction.updated, "Should be updated"
        assert entry.user_id == 123456, "Should be user 123456"
        print("   ✓ All filters applied correctly")

        print("\n5. Filtering with no matches...")
        result = await get_audit_logs(
            entity_type=EntityType.memory,
            action=AuditAction.fired,  # memories don't fire
            db=db
        )

        assert len(result) == 0, "Should have 0 entries"
        print("   ✓ Returns empty list when no matches")

        print("\n" + "-"*60)
        print("✓ COMBINED FILTERS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_pagination():
    """Test limit and offset parameters."""
    print("\n" + "="*60)
    print("TESTING PAGINATION")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Testing limit=5...")
        result = await get_audit_logs(limit=5, db=db)

        assert len(result) == 5, f"Should have 5 entries, got {len(result)}"
        print(f"   ✓ Retrieved {len(result)} entries")

        print("\n2. Testing limit=3, offset=0...")
        page1 = await get_audit_logs(limit=3, offset=0, db=db)

        assert len(page1) == 3, f"Should have 3 entries, got {len(page1)}"
        print(f"   ✓ Page 1: {len(page1)} entries")

        print("\n3. Testing limit=3, offset=3...")
        page2 = await get_audit_logs(limit=3, offset=3, db=db)

        assert len(page2) == 3, f"Should have 3 entries, got {len(page2)}"
        print(f"   ✓ Page 2: {len(page2)} entries")

        # Verify no overlap
        page1_ids = {entry.id for entry in page1}
        page2_ids = {entry.id for entry in page2}
        assert len(page1_ids & page2_ids) == 0, "Pages should not overlap"
        print("   ✓ No overlap between pages")

        print("\n4. Testing offset beyond total count...")
        result = await get_audit_logs(limit=10, offset=100, db=db)

        assert len(result) == 0, "Should have 0 entries"
        print("   ✓ Returns empty list when offset exceeds total count")

        print("\n5. Testing large limit...")
        result = await get_audit_logs(limit=1000, db=db)

        assert len(result) == 13, f"Should have all 13 entries, got {len(result)}"
        print(f"   ✓ Retrieved all {len(result)} entries with large limit")

        print("\n" + "-"*60)
        print("✓ PAGINATION TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_detail_parsing():
    """Test parsing of JSON detail field."""
    print("\n" + "="*60)
    print("TESTING DETAIL PARSING")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Fetching entry with detail...")
        result = await get_audit_logs(
            entity_id="mem-001",
            action=AuditAction.created,
            db=db
        )

        assert len(result) == 1, "Should have 1 entry"
        entry = result[0]
        assert entry.detail is not None, "Detail should not be None"
        assert isinstance(entry.detail, dict), "Detail should be a dict"
        assert entry.detail.get("content") == "test memory", "Detail content should match"
        print(f"   ✓ Detail parsed correctly: {entry.detail}")

        print("\n2. Fetching entry without detail...")
        result = await get_audit_logs(
            entity_id="mem-002",
            action=AuditAction.created,
            db=db
        )

        assert len(result) == 1, "Should have 1 entry"
        entry = result[0]
        assert entry.detail is None, "Detail should be None"
        print("   ✓ None detail handled correctly")

        print("\n3. Fetching entry with complex detail...")
        result = await get_audit_logs(
            entity_type=EntityType.reminder,
            action=AuditAction.fired,
            db=db
        )

        assert len(result) == 1, "Should have 1 entry"
        entry = result[0]
        assert entry.detail is not None, "Detail should not be None"
        assert isinstance(entry.detail, dict), "Detail should be a dict"
        assert "fire_at" in entry.detail, "Detail should contain fire_at"
        print(f"   ✓ Complex detail parsed correctly: {entry.detail}")

        print("\n" + "-"*60)
        print("✓ DETAIL PARSING TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_actor_parsing():
    """Test parsing of actor field to user_id."""
    print("\n" + "="*60)
    print("TESTING ACTOR PARSING")
    print("="*60)

    # Test parse_actor_to_user_id function directly
    print("\n1. Testing parse_actor_to_user_id function...")

    assert parse_actor_to_user_id("user:123456") == 123456, "Should parse user:123456"
    print("   ✓ Parsed user:123456 -> 123456")

    assert parse_actor_to_user_id("user:999999") == 999999, "Should parse user:999999"
    print("   ✓ Parsed user:999999 -> 999999")

    assert parse_actor_to_user_id("system:scheduler") == 0, "Should parse system:scheduler to 0"
    print("   ✓ Parsed system:scheduler -> 0")

    assert parse_actor_to_user_id("system:llm_worker") == 0, "Should parse system:llm_worker to 0"
    print("   ✓ Parsed system:llm_worker -> 0")

    assert parse_actor_to_user_id("system") == 0, "Should parse system to 0"
    print("   ✓ Parsed system -> 0")

    assert parse_actor_to_user_id("invalid") == 0, "Should parse invalid format to 0"
    print("   ✓ Parsed invalid -> 0")

    assert parse_actor_to_user_id("user:abc") == 0, "Should parse invalid user id to 0"
    print("   ✓ Parsed user:abc -> 0")

    db, db_path = await setup_test_db()

    try:
        print("\n2. Testing actor parsing in audit logs...")

        # Get user entries
        result = await get_audit_logs(actor="user:123456", db=db)
        for entry in result:
            assert entry.user_id == 123456, "User entries should have correct user_id"
        print(f"   ✓ All user:123456 entries have user_id=123456 ({len(result)} entries)")

        # Get system entries
        result = await get_audit_logs(actor="system:scheduler", db=db)
        for entry in result:
            assert entry.user_id == 0, "System entries should have user_id=0"
        print(f"   ✓ All system:scheduler entries have user_id=0 ({len(result)} entries)")

        print("\n" + "-"*60)
        print("✓ ACTOR PARSING TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_default_limit():
    """Test default limit of 100."""
    print("\n" + "="*60)
    print("TESTING DEFAULT LIMIT")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        # Add more entries to test default limit
        for i in range(100):
            await db.execute(
                "INSERT INTO audit_log (entity_type, entity_id, action, actor) VALUES (?, ?, ?, ?)",
                ("memory", f"mem-{i:03d}", "created", "user:123456")
            )
        await db.commit()

        print("\n1. Fetching without explicit limit (should use default 100)...")
        result = await get_audit_logs(db=db)

        assert len(result) == 100, f"Should have 100 entries (default limit), got {len(result)}"
        print(f"   ✓ Retrieved {len(result)} entries (default limit)")

        print("\n2. Verifying total count in database...")
        cursor = await db.execute("SELECT COUNT(*) FROM audit_log")
        total = (await cursor.fetchone())[0]
        assert total > 100, f"Database should have more than 100 entries, has {total}"
        print(f"   ✓ Database has {total} entries total")

        print("\n" + "-"*60)
        print("✓ DEFAULT LIMIT TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_datetime_parsing():
    """Test datetime parsing from database."""
    print("\n" + "="*60)
    print("TESTING DATETIME PARSING")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Fetching audit logs and checking datetime parsing...")
        result = await get_audit_logs(limit=5, db=db)

        for entry in result:
            assert entry.created_at is not None, "created_at should not be None"
            assert isinstance(entry.created_at, datetime), "created_at should be datetime"
            print(f"   ✓ Entry {entry.id}: created_at={entry.created_at}")

        print("\n" + "-"*60)
        print("✓ DATETIME PARSING TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("AUDIT ROUTER TEST SUITE")
    print("="*60)

    tests = [
        test_get_all_audit_logs,
        test_filter_by_entity_type,
        test_filter_by_entity_id,
        test_filter_by_action,
        test_filter_by_actor,
        test_combined_filters,
        test_pagination,
        test_detail_parsing,
        test_actor_parsing,
        test_default_limit,
        test_datetime_parsing,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            await test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"\n✗ TEST FAILED: {test.__name__}")
            print(f"  Error: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Total tests: {len(tests)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print("="*60)

    if failed == 0:
        print("✓ ALL TESTS PASSED")
    else:
        print(f"✗ {failed} TEST(S) FAILED")

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
