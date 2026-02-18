"""Test Reminders router."""

import asyncio
import aiosqlite
import json
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Import the modules to test
import sys
sys.path.insert(0, str(Path(__file__).parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent / 'shared'))

from core_svc.database import init_db
from core_svc.routers.reminders import (
    create_reminder,
    get_reminders,
    update_reminder,
    delete_reminder,
)
from shared_lib.schemas import (
    ReminderCreate,
    ReminderUpdate,
)


class MockRequest:
    """Mock FastAPI request with db in app.state."""
    def __init__(self, db):
        self.app = type('obj', (object,), {'state': type('obj', (object,), {'db': db})()})()


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

    # Create test memories
    await db.execute(
        "INSERT INTO memories (id, owner_user_id, content, status) VALUES (?, ?, ?, ?)",
        ("memory-001", 123456, "Test memory 1", "confirmed")
    )
    await db.execute(
        "INSERT INTO memories (id, owner_user_id, content, status) VALUES (?, ?, ?, ?)",
        ("memory-002", 999999, "Test memory 2", "confirmed")
    )
    await db.commit()

    return db, db_path


async def cleanup_test_db(db, db_path):
    """Close and remove test database."""
    await db.close()
    os.unlink(db_path)


async def test_create_reminder():
    """Test creating a basic reminder."""
    print("\n" + "="*60)
    print("TESTING CREATE REMINDER")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a basic reminder...")
        fire_at = datetime.now(timezone.utc) + timedelta(hours=2)
        reminder_create = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Remember to buy groceries",
            fire_at=fire_at,
            recurrence_minutes=None,
        )

        result = await create_reminder(reminder_create, db)

        assert result.id is not None, "Reminder ID should be set"
        assert result.memory_id == "memory-001", "Memory ID should match"
        assert result.owner_user_id == 123456, "Owner user ID should match"
        assert result.text == "Remember to buy groceries", "Text should match"
        assert result.fired is False, "fired should default to False"
        assert result.recurrence_minutes is None, "recurrence_minutes should be None"
        print(f"   ✓ Reminder created with ID: {result.id}")
        print(f"   ✓ Fired status: {result.fired}")

        # Verify fire_at is correct
        time_diff = abs((result.fire_at - fire_at).total_seconds())
        assert time_diff < 2, "fire_at should match the input"
        print(f"   ✓ fire_at: {result.fire_at}")

        # Verify audit log
        cursor = await db.execute(
            "SELECT action, actor FROM audit_log WHERE entity_id = ?",
            (result.id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist"
        assert audit_row[0] == "created", "Audit action should be 'created'"
        assert audit_row[1] == "user:123456", "Audit actor should be user:123456"
        print("   ✓ Audit log entry created")

        print("\n" + "-"*60)
        print("✓ CREATE REMINDER TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_create_reminder_with_recurrence():
    """Test creating a recurring reminder."""
    print("\n" + "="*60)
    print("TESTING CREATE REMINDER WITH RECURRENCE")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a recurring reminder...")
        fire_at = datetime.now(timezone.utc) + timedelta(days=1)
        reminder_create = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Daily standup reminder",
            fire_at=fire_at,
            recurrence_minutes=1440,  # 24 hours
        )

        result = await create_reminder(reminder_create, db)

        assert result.recurrence_minutes == 1440, "recurrence_minutes should match"
        print(f"   ✓ Reminder created with recurrence: {result.recurrence_minutes} minutes")

        print("\n" + "-"*60)
        print("✓ CREATE REMINDER WITH RECURRENCE TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_reminders_no_filter():
    """Test getting reminders without filters."""
    print("\n" + "="*60)
    print("TESTING GET REMINDERS (NO FILTER)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating multiple reminders...")
        now = datetime.now(timezone.utc)

        reminder1 = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Reminder 1",
            fire_at=now + timedelta(hours=1),
        )
        reminder2 = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Reminder 2",
            fire_at=now + timedelta(hours=3),
        )
        reminder3 = ReminderCreate(
            memory_id="memory-002",
            owner_user_id=999999,
            text="Reminder 3",
            fire_at=now + timedelta(hours=2),
        )

        await create_reminder(reminder1, db)
        await create_reminder(reminder2, db)
        await create_reminder(reminder3, db)
        print("   ✓ Created 3 reminders")

        print("\n2. Fetching all reminders...")
        results = await get_reminders(db=db)

        assert len(results) == 3, "Should return all 3 reminders"
        print(f"   ✓ Retrieved {len(results)} reminders")

        # Verify reminders are ordered by fire_at ASC (earliest first)
        texts = [reminder.text for reminder in results]
        assert texts == ["Reminder 1", "Reminder 3", "Reminder 2"], "Reminders should be ordered by fire_at ASC"
        print("   ✓ Reminders ordered by fire_at ASC")

        print("\n" + "-"*60)
        print("✓ GET REMINDERS (NO FILTER) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_reminders_with_filters():
    """Test getting reminders with various filters."""
    print("\n" + "="*60)
    print("TESTING GET REMINDERS WITH FILTERS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating reminders with different properties...")
        now = datetime.now(timezone.utc)

        reminder1 = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="User 1 reminder - future",
            fire_at=now + timedelta(hours=1),
        )
        reminder2 = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="User 1 reminder - past",
            fire_at=now - timedelta(hours=1),
        )
        reminder3 = ReminderCreate(
            memory_id="memory-002",
            owner_user_id=999999,
            text="User 2 reminder",
            fire_at=now + timedelta(hours=2),
        )

        created_reminder1 = await create_reminder(reminder1, db)
        created_reminder2 = await create_reminder(reminder2, db)
        await create_reminder(reminder3, db)

        # Mark reminder2 as fired
        await db.execute(
            "UPDATE reminders SET fired = 1 WHERE id = ?",
            (created_reminder2.id,)
        )
        await db.commit()
        print("   ✓ Created 3 reminders (1 fired, 2 unfired)")

        print("\n2. Filtering by owner_user_id...")
        results = await get_reminders(owner_user_id=123456, db=db)
        assert len(results) == 2, "Should return 2 reminders for user 123456"
        for reminder in results:
            assert reminder.owner_user_id == 123456, "All reminders should belong to user 123456"
        print(f"   ✓ Retrieved {len(results)} reminders for user 123456")

        print("\n3. Filtering by fired=False...")
        results = await get_reminders(fired=False, db=db)
        assert len(results) == 2, "Should return 2 unfired reminders"
        for reminder in results:
            assert reminder.fired is False, "All reminders should be unfired"
        print(f"   ✓ Retrieved {len(results)} unfired reminders")

        print("\n4. Filtering by fired=True...")
        results = await get_reminders(fired=True, db=db)
        assert len(results) == 1, "Should return 1 fired reminder"
        assert results[0].fired is True, "Reminder should be fired"
        print(f"   ✓ Retrieved {len(results)} fired reminder")

        print("\n5. Filtering by upcoming_only...")
        results = await get_reminders(upcoming_only=True, db=db)
        # upcoming_only means fire_at > now AND fired = 0
        # Should return reminder1 and reminder3 (both unfired and in the future)
        assert len(results) == 2, "Should return 2 upcoming reminders"
        for reminder in results:
            assert reminder.fired is False, "All upcoming reminders should be unfired"
            assert reminder.fire_at > now, "All upcoming reminders should be in the future"
        print(f"   ✓ Retrieved {len(results)} upcoming reminders")

        print("\n6. Testing limit and offset...")
        results = await get_reminders(limit=2, offset=0, db=db)
        assert len(results) == 2, "Should return 2 reminders with limit=2"
        print(f"   ✓ Limit works: retrieved {len(results)} reminders")

        results = await get_reminders(limit=2, offset=2, db=db)
        assert len(results) == 1, "Should return 1 reminder with offset=2"
        print(f"   ✓ Offset works: retrieved {len(results)} reminder")

        print("\n7. Combining filters (owner_user_id + upcoming_only)...")
        results = await get_reminders(owner_user_id=123456, upcoming_only=True, db=db)
        assert len(results) == 1, "Should return 1 upcoming reminder for user 123456"
        assert results[0].text == "User 1 reminder - future", "Should be the future reminder"
        print(f"   ✓ Retrieved {len(results)} upcoming reminder for user 123456")

        print("\n" + "-"*60)
        print("✓ GET REMINDERS WITH FILTERS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_reminder_text():
    """Test updating reminder text."""
    print("\n" + "="*60)
    print("TESTING UPDATE REMINDER TEXT")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a reminder...")
        fire_at = datetime.now(timezone.utc) + timedelta(hours=2)
        reminder_create = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Original reminder text",
            fire_at=fire_at,
        )
        created = await create_reminder(reminder_create, db)
        reminder_id = created.id
        print(f"   ✓ Reminder created with ID: {reminder_id}")

        print("\n2. Updating text...")
        reminder_update = ReminderUpdate(
            text="Updated reminder text",
        )
        result = await update_reminder(reminder_id, reminder_update, db)

        assert result.text == "Updated reminder text", "Text should be updated"
        assert result.updated_at is not None, "updated_at should be set"
        print("   ✓ Reminder text updated successfully")

        # Verify audit log
        cursor = await db.execute(
            "SELECT action, detail FROM audit_log WHERE entity_id = ? AND action = 'updated'",
            (reminder_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist"
        detail = json.loads(audit_row[1]) if audit_row[1] else {}
        assert "text" in detail, "Audit detail should include 'text'"
        print("   ✓ Audit log entry created")

        print("\n" + "-"*60)
        print("✓ UPDATE REMINDER TEXT TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_reminder_fire_at():
    """Test updating reminder fire_at."""
    print("\n" + "="*60)
    print("TESTING UPDATE REMINDER FIRE_AT")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a reminder...")
        original_fire_at = datetime.now(timezone.utc) + timedelta(hours=2)
        reminder_create = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Reminder to update",
            fire_at=original_fire_at,
        )
        created = await create_reminder(reminder_create, db)
        reminder_id = created.id
        print(f"   ✓ Reminder created with ID: {reminder_id}")
        print(f"   ✓ Original fire_at: {created.fire_at}")

        print("\n2. Updating fire_at...")
        new_fire_at = datetime.now(timezone.utc) + timedelta(days=1)
        reminder_update = ReminderUpdate(
            fire_at=new_fire_at,
        )
        result = await update_reminder(reminder_id, reminder_update, db)

        time_diff = abs((result.fire_at - new_fire_at).total_seconds())
        assert time_diff < 2, "fire_at should match the new value"
        print(f"   ✓ fire_at updated to: {result.fire_at}")

        print("\n" + "-"*60)
        print("✓ UPDATE REMINDER FIRE_AT TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_reminder_recurrence():
    """Test updating reminder recurrence_minutes."""
    print("\n" + "="*60)
    print("TESTING UPDATE REMINDER RECURRENCE")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a reminder without recurrence...")
        fire_at = datetime.now(timezone.utc) + timedelta(hours=2)
        reminder_create = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="One-time reminder",
            fire_at=fire_at,
            recurrence_minutes=None,
        )
        created = await create_reminder(reminder_create, db)
        reminder_id = created.id
        print(f"   ✓ Reminder created with ID: {reminder_id}")

        print("\n2. Adding recurrence...")
        reminder_update = ReminderUpdate(
            recurrence_minutes=1440,  # Daily
        )
        result = await update_reminder(reminder_id, reminder_update, db)

        assert result.recurrence_minutes == 1440, "recurrence_minutes should be updated"
        print(f"   ✓ recurrence_minutes updated to: {result.recurrence_minutes}")

        # Verify audit log
        cursor = await db.execute(
            "SELECT action, detail FROM audit_log WHERE entity_id = ? AND action = 'updated'",
            (reminder_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist"
        detail = json.loads(audit_row[1]) if audit_row[1] else {}
        assert "recurrence_minutes" in detail, "Audit detail should include 'recurrence_minutes'"
        print("   ✓ Audit log entry created")

        print("\n" + "-"*60)
        print("✓ UPDATE REMINDER RECURRENCE TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_reminder_multiple_fields():
    """Test updating multiple reminder fields at once."""
    print("\n" + "="*60)
    print("TESTING UPDATE REMINDER MULTIPLE FIELDS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a reminder...")
        fire_at = datetime.now(timezone.utc) + timedelta(hours=2)
        reminder_create = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Original text",
            fire_at=fire_at,
            recurrence_minutes=None,
        )
        created = await create_reminder(reminder_create, db)
        reminder_id = created.id
        print(f"   ✓ Reminder created with ID: {reminder_id}")

        print("\n2. Updating multiple fields...")
        new_fire_at = datetime.now(timezone.utc) + timedelta(days=1)
        reminder_update = ReminderUpdate(
            text="Updated text",
            fire_at=new_fire_at,
            recurrence_minutes=60,  # Hourly
        )
        result = await update_reminder(reminder_id, reminder_update, db)

        assert result.text == "Updated text", "Text should be updated"
        assert result.recurrence_minutes == 60, "recurrence_minutes should be updated"
        time_diff = abs((result.fire_at - new_fire_at).total_seconds())
        assert time_diff < 2, "fire_at should be updated"
        print("   ✓ All fields updated successfully")

        # Verify audit log includes all changes
        cursor = await db.execute(
            "SELECT detail FROM audit_log WHERE entity_id = ? AND action = 'updated'",
            (reminder_id,)
        )
        audit_row = await cursor.fetchone()
        detail = json.loads(audit_row[0]) if audit_row[0] else {}
        assert "text" in detail, "Audit detail should include 'text'"
        assert "fire_at" in detail, "Audit detail should include 'fire_at'"
        assert "recurrence_minutes" in detail, "Audit detail should include 'recurrence_minutes'"
        print("   ✓ Audit log includes all changed fields")

        print("\n" + "-"*60)
        print("✓ UPDATE REMINDER MULTIPLE FIELDS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_delete_reminder():
    """Test deleting a reminder."""
    print("\n" + "="*60)
    print("TESTING DELETE REMINDER")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a reminder...")
        fire_at = datetime.now(timezone.utc) + timedelta(hours=2)
        reminder_create = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Reminder to delete",
            fire_at=fire_at,
        )
        created = await create_reminder(reminder_create, db)
        reminder_id = created.id
        print(f"   ✓ Reminder created with ID: {reminder_id}")

        print("\n2. Deleting the reminder...")
        await delete_reminder(reminder_id, db)

        # Verify reminder is deleted
        cursor = await db.execute("SELECT COUNT(*) FROM reminders WHERE id = ?", (reminder_id,))
        count = (await cursor.fetchone())[0]
        assert count == 0, "Reminder should be deleted"
        print("   ✓ Reminder deleted from database")

        # Verify audit log
        cursor = await db.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? AND action = 'deleted'",
            (reminder_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist for deletion"
        print("   ✓ Audit log entry created")

        print("\n3. Testing 404 for non-existent reminder...")
        try:
            await delete_reminder("non-existent-id", db)
            assert False, "Should raise HTTPException"
        except Exception as e:
            assert "404" in str(e) or "not found" in str(e).lower(), "Should return 404"
            print("   ✓ 404 raised for non-existent reminder")

        print("\n" + "-"*60)
        print("✓ DELETE REMINDER TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_404_on_update_nonexistent_reminder():
    """Test 404 error when updating non-existent reminder."""
    print("\n" + "="*60)
    print("TESTING 404 ON UPDATE NON-EXISTENT REMINDER")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Attempting to update non-existent reminder...")
        reminder_update = ReminderUpdate(text="Updated")
        try:
            await update_reminder("non-existent-id", reminder_update, db)
            assert False, "Should raise HTTPException"
        except Exception as e:
            assert "404" in str(e) or "not found" in str(e).lower(), "Should return 404"
            print("   ✓ 404 raised for non-existent reminder")

        print("\n" + "-"*60)
        print("✓ 404 ON UPDATE NON-EXISTENT REMINDER TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_upcoming_only_filter_edge_cases():
    """Test upcoming_only filter with various edge cases."""
    print("\n" + "="*60)
    print("TESTING UPCOMING_ONLY FILTER EDGE CASES")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating reminders with various states...")
        now = datetime.now(timezone.utc)

        # Future, unfired
        reminder1 = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Future unfired",
            fire_at=now + timedelta(hours=1),
        )
        # Future, fired
        reminder2 = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Future fired",
            fire_at=now + timedelta(hours=2),
        )
        # Past, unfired
        reminder3 = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Past unfired",
            fire_at=now - timedelta(hours=1),
        )
        # Past, fired
        reminder4 = ReminderCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            text="Past fired",
            fire_at=now - timedelta(hours=2),
        )

        created1 = await create_reminder(reminder1, db)
        created2 = await create_reminder(reminder2, db)
        created3 = await create_reminder(reminder3, db)
        created4 = await create_reminder(reminder4, db)

        # Mark reminder2 and reminder4 as fired
        await db.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (created2.id,))
        await db.execute("UPDATE reminders SET fired = 1 WHERE id = ?", (created4.id,))
        await db.commit()
        print("   ✓ Created 4 reminders with different states")

        print("\n2. Testing upcoming_only filter...")
        results = await get_reminders(upcoming_only=True, db=db)

        # Should only return reminder1 (future and unfired)
        assert len(results) == 1, "Should return only 1 upcoming reminder"
        assert results[0].text == "Future unfired", "Should be the future unfired reminder"
        assert results[0].fired is False, "Should be unfired"
        assert results[0].fire_at > now, "Should be in the future"
        print(f"   ✓ Retrieved {len(results)} upcoming reminder (future + unfired)")

        print("\n" + "-"*60)
        print("✓ UPCOMING_ONLY FILTER EDGE CASES TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("REMINDERS ROUTER TEST SUITE")
    print("="*60)

    tests = [
        test_create_reminder,
        test_create_reminder_with_recurrence,
        test_get_reminders_no_filter,
        test_get_reminders_with_filters,
        test_update_reminder_text,
        test_update_reminder_fire_at,
        test_update_reminder_recurrence,
        test_update_reminder_multiple_fields,
        test_delete_reminder,
        test_404_on_update_nonexistent_reminder,
        test_upcoming_only_filter_edge_cases,
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
