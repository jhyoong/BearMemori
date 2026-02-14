"""Test Events router."""

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

from core.database import init_db
from core.routers.events import (
    create_event,
    update_event,
    get_events,
)
from shared.schemas import (
    EventCreate,
    EventUpdate,
)


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


async def test_create_event():
    """Test creating a basic event."""
    print("\n" + "="*60)
    print("TESTING CREATE EVENT")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a basic event with memory_id...")
        event_time = datetime.now(timezone.utc) + timedelta(days=7)
        event_create = EventCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            event_time=event_time,
            description="Team meeting next week",
            source_type="manual",
            source_detail="user-entered",
        )

        result = await create_event(event_create, db)

        assert result.id is not None, "Event ID should be set"
        assert result.memory_id == "memory-001", "Memory ID should match"
        assert result.owner_user_id == 123456, "Owner user ID should match"
        assert result.description == "Team meeting next week", "Description should match"
        assert result.status == "pending", "Status should default to 'pending'"
        assert result.source_type == "manual", "Source type should match"
        assert result.source_detail == "user-entered", "Source detail should match"
        assert result.reminder_id is None, "Reminder ID should be None initially"
        print(f"   ✓ Event created with ID: {result.id}")
        print(f"   ✓ Status: {result.status}")
        print(f"   ✓ Event time: {result.event_time}")

        # Verify event_time is correct
        time_diff = abs((result.event_time - event_time).total_seconds())
        assert time_diff < 2, "event_time should match the input"

        # Verify pending_since is set
        cursor = await db.execute(
            "SELECT pending_since FROM events WHERE id = ?",
            (result.id,)
        )
        row = await cursor.fetchone()
        assert row["pending_since"] is not None, "pending_since should be set"
        print("   ✓ pending_since is set")

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
        print("✓ CREATE EVENT TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_create_event_without_memory():
    """Test creating an event without memory_id (e.g., from email)."""
    print("\n" + "="*60)
    print("TESTING CREATE EVENT WITHOUT MEMORY")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating event without memory_id...")
        event_time = datetime.now(timezone.utc) + timedelta(days=3)
        event_create = EventCreate(
            memory_id=None,  # No memory
            owner_user_id=123456,
            event_time=event_time,
            description="Email-sourced event",
            source_type="email",
            source_detail="gmail:message-id-xyz",
        )

        result = await create_event(event_create, db)

        assert result.id is not None, "Event ID should be set"
        assert result.memory_id is None, "Memory ID should be None"
        assert result.status == "pending", "Status should be 'pending'"
        assert result.source_type == "email", "Source type should be 'email'"
        print(f"   ✓ Event created without memory_id")
        print(f"   ✓ Source type: {result.source_type}")

        print("\n" + "-"*60)
        print("✓ CREATE EVENT WITHOUT MEMORY TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_event_basic_fields():
    """Test updating event's basic fields."""
    print("\n" + "="*60)
    print("TESTING UPDATE EVENT BASIC FIELDS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating an event...")
        event_time = datetime.now(timezone.utc) + timedelta(days=7)
        event_create = EventCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            event_time=event_time,
            description="Original description",
            source_type="manual",
        )
        created = await create_event(event_create, db)
        event_id = created.id
        print(f"   ✓ Event created with ID: {event_id}")

        print("\n2. Updating description...")
        event_update = EventUpdate(
            description="Updated description",
        )
        result = await update_event(event_id, event_update, db)

        assert result.description == "Updated description", "Description should be updated"
        assert result.updated_at is not None, "updated_at should be set"
        print("   ✓ Description updated successfully")

        print("\n3. Updating event_time...")
        new_event_time = datetime.now(timezone.utc) + timedelta(days=14)
        event_update = EventUpdate(
            event_time=new_event_time,
        )
        result = await update_event(event_id, event_update, db)

        time_diff = abs((result.event_time - new_event_time).total_seconds())
        assert time_diff < 2, "event_time should match the new value"
        print(f"   ✓ event_time updated to: {result.event_time}")

        print("\n" + "-"*60)
        print("✓ UPDATE EVENT BASIC FIELDS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_confirm_event_creates_reminder():
    """Test that confirming an event auto-creates a reminder."""
    print("\n" + "="*60)
    print("TESTING CONFIRM EVENT CREATES REMINDER")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a pending event with memory_id...")
        event_time = datetime.now(timezone.utc) + timedelta(days=7)
        event_create = EventCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            event_time=event_time,
            description="Important meeting",
            source_type="manual",
        )
        created = await create_event(event_create, db)
        event_id = created.id
        print(f"   ✓ Event created with ID: {event_id}")
        print(f"   ✓ Initial status: {created.status}")
        assert created.reminder_id is None, "Reminder ID should be None initially"

        print("\n2. Confirming the event...")
        event_update = EventUpdate(
            status="confirmed",
        )
        result = await update_event(event_id, event_update, db)

        assert result.status == "confirmed", "Status should be 'confirmed'"
        assert result.reminder_id is not None, "Reminder ID should be set"
        print(f"   ✓ Event confirmed")
        print(f"   ✓ Reminder ID: {result.reminder_id}")

        # Verify reminder was created
        cursor = await db.execute(
            "SELECT * FROM reminders WHERE id = ?",
            (result.reminder_id,)
        )
        reminder_row = await cursor.fetchone()
        assert reminder_row is not None, "Reminder should exist"
        assert reminder_row["memory_id"] == "memory-001", "Reminder should link to same memory"
        assert reminder_row["owner_user_id"] == 123456, "Reminder should have same owner"
        assert reminder_row["text"] == "Important meeting", "Reminder text should match event description"
        assert reminder_row["recurrence_minutes"] is None, "Reminder should be one-time"
        print("   ✓ Reminder created in database")
        print(f"   ✓ Reminder text: {reminder_row['text']}")
        print(f"   ✓ Reminder fire_at: {reminder_row['fire_at']}")

        # Verify confirmed_at is set
        cursor = await db.execute(
            "SELECT confirmed_at FROM events WHERE id = ?",
            (event_id,)
        )
        row = await cursor.fetchone()
        assert row["confirmed_at"] is not None, "confirmed_at should be set"
        print("   ✓ confirmed_at is set")

        # Verify audit logs for both event and reminder
        cursor = await db.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? AND entity_type = 'event'",
            (event_id,)
        )
        event_audits = await cursor.fetchall()
        event_actions = [row[0] for row in event_audits]
        assert "created" in event_actions, "Should have 'created' audit"
        assert "confirmed" in event_actions, "Should have 'confirmed' audit"
        print("   ✓ Event audit logs created")

        cursor = await db.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? AND entity_type = 'reminder'",
            (result.reminder_id,)
        )
        reminder_audits = await cursor.fetchall()
        reminder_actions = [row[0] for row in reminder_audits]
        assert "created" in reminder_actions, "Should have reminder 'created' audit"
        print("   ✓ Reminder audit log created")

        print("\n" + "-"*60)
        print("✓ CONFIRM EVENT CREATES REMINDER TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_confirm_event_without_memory_skips_reminder():
    """Test that confirming an event without memory_id skips reminder creation."""
    print("\n" + "="*60)
    print("TESTING CONFIRM EVENT WITHOUT MEMORY SKIPS REMINDER")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating event without memory_id...")
        event_time = datetime.now(timezone.utc) + timedelta(days=3)
        event_create = EventCreate(
            memory_id=None,
            owner_user_id=123456,
            event_time=event_time,
            description="Email event",
            source_type="email",
        )
        created = await create_event(event_create, db)
        event_id = created.id
        print(f"   ✓ Event created with ID: {event_id}")

        print("\n2. Confirming event without memory_id...")
        event_update = EventUpdate(
            status="confirmed",
        )
        result = await update_event(event_id, event_update, db)

        assert result.status == "confirmed", "Status should be 'confirmed'"
        assert result.reminder_id is None, "Reminder ID should still be None"
        print("   ✓ Event confirmed without creating reminder")

        # Verify no reminder was created
        cursor = await db.execute("SELECT COUNT(*) FROM reminders")
        count = (await cursor.fetchone())[0]
        assert count == 0, "No reminders should exist"
        print("   ✓ No reminder created (as expected)")

        # Verify audit log for confirmation
        cursor = await db.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? AND action = 'confirmed'",
            (event_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist for confirmation"
        print("   ✓ Audit log entry created")

        print("\n" + "-"*60)
        print("✓ CONFIRM EVENT WITHOUT MEMORY SKIPS REMINDER TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_reject_event():
    """Test rejecting an event."""
    print("\n" + "="*60)
    print("TESTING REJECT EVENT")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a pending event...")
        event_time = datetime.now(timezone.utc) + timedelta(days=7)
        event_create = EventCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            event_time=event_time,
            description="Meeting to reject",
            source_type="manual",
        )
        created = await create_event(event_create, db)
        event_id = created.id
        print(f"   ✓ Event created with ID: {event_id}")

        print("\n2. Rejecting the event...")
        event_update = EventUpdate(
            status="rejected",
        )
        result = await update_event(event_id, event_update, db)

        assert result.status == "rejected", "Status should be 'rejected'"
        assert result.reminder_id is None, "Reminder ID should still be None"
        print("   ✓ Event rejected")

        # Verify no reminder was created
        cursor = await db.execute("SELECT COUNT(*) FROM reminders")
        count = (await cursor.fetchone())[0]
        assert count == 0, "No reminders should exist"
        print("   ✓ No reminder created")

        # Verify audit log for rejection
        cursor = await db.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? AND action = 'rejected'",
            (event_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist for rejection"
        print("   ✓ Audit log entry created")

        print("\n" + "-"*60)
        print("✓ REJECT EVENT TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_confirm_event_with_updated_time_and_description():
    """Test that confirming with updated fields uses new values for reminder."""
    print("\n" + "="*60)
    print("TESTING CONFIRM WITH UPDATED FIELDS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a pending event...")
        event_time = datetime.now(timezone.utc) + timedelta(days=7)
        event_create = EventCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            event_time=event_time,
            description="Original description",
            source_type="manual",
        )
        created = await create_event(event_create, db)
        event_id = created.id
        print(f"   ✓ Event created with ID: {event_id}")

        print("\n2. Confirming with updated time and description...")
        new_event_time = datetime.now(timezone.utc) + timedelta(days=14)
        event_update = EventUpdate(
            status="confirmed",
            event_time=new_event_time,
            description="Updated description",
        )
        result = await update_event(event_id, event_update, db)

        assert result.status == "confirmed", "Status should be 'confirmed'"
        assert result.reminder_id is not None, "Reminder ID should be set"
        print(f"   ✓ Event confirmed with updated fields")

        # Verify reminder uses updated values
        cursor = await db.execute(
            "SELECT * FROM reminders WHERE id = ?",
            (result.reminder_id,)
        )
        reminder_row = await cursor.fetchone()
        assert reminder_row is not None, "Reminder should exist"
        assert reminder_row["text"] == "Updated description", "Reminder should use updated description"
        print(f"   ✓ Reminder text: {reminder_row['text']}")

        # Verify reminder fire_at matches updated event_time
        from core.routers.events import parse_db_datetime
        reminder_fire_at = parse_db_datetime(reminder_row["fire_at"])
        time_diff = abs((reminder_fire_at - new_event_time).total_seconds())
        assert time_diff < 2, "Reminder fire_at should match updated event_time"
        print(f"   ✓ Reminder fire_at matches updated event_time")

        print("\n" + "-"*60)
        print("✓ CONFIRM WITH UPDATED FIELDS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_events_no_filter():
    """Test getting events without filters."""
    print("\n" + "="*60)
    print("TESTING GET EVENTS (NO FILTER)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating multiple events...")
        now = datetime.now(timezone.utc)

        event1 = EventCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            event_time=now + timedelta(days=1),
            description="Event 1",
            source_type="manual",
        )
        event2 = EventCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            event_time=now + timedelta(days=3),
            description="Event 2",
            source_type="manual",
        )
        event3 = EventCreate(
            memory_id="memory-002",
            owner_user_id=999999,
            event_time=now + timedelta(days=2),
            description="Event 3",
            source_type="email",
        )

        await create_event(event1, db)
        await create_event(event2, db)
        await create_event(event3, db)
        print("   ✓ Created 3 events")

        print("\n2. Fetching all events...")
        results = await get_events(db=db)

        assert len(results) == 3, "Should return all 3 events"
        print(f"   ✓ Retrieved {len(results)} events")

        # Verify events are ordered by event_time DESC (latest first)
        descriptions = [event.description for event in results]
        assert descriptions == ["Event 2", "Event 3", "Event 1"], "Events should be ordered by event_time DESC"
        print("   ✓ Events ordered by event_time DESC")

        print("\n" + "-"*60)
        print("✓ GET EVENTS (NO FILTER) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_events_with_filters():
    """Test getting events with various filters."""
    print("\n" + "="*60)
    print("TESTING GET EVENTS WITH FILTERS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating events with different properties...")
        now = datetime.now(timezone.utc)

        event1 = EventCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            event_time=now + timedelta(days=1),
            description="User 1 pending event",
            source_type="manual",
        )
        event2 = EventCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            event_time=now + timedelta(days=2),
            description="User 1 confirmed event",
            source_type="manual",
        )
        event3 = EventCreate(
            memory_id="memory-002",
            owner_user_id=999999,
            event_time=now + timedelta(days=3),
            description="User 2 event",
            source_type="email",
        )

        created1 = await create_event(event1, db)
        created2 = await create_event(event2, db)
        await create_event(event3, db)

        # Confirm event2
        await update_event(created2.id, EventUpdate(status="confirmed"), db)
        print("   ✓ Created 3 events (1 confirmed, 2 pending)")

        print("\n2. Filtering by owner_user_id...")
        results = await get_events(owner_user_id=123456, db=db)
        assert len(results) == 2, "Should return 2 events for user 123456"
        for event in results:
            assert event.owner_user_id == 123456, "All events should belong to user 123456"
        print(f"   ✓ Retrieved {len(results)} events for user 123456")

        print("\n3. Filtering by status=pending...")
        results = await get_events(status="pending", db=db)
        assert len(results) == 2, "Should return 2 pending events"
        for event in results:
            assert event.status == "pending", "All events should be pending"
        print(f"   ✓ Retrieved {len(results)} pending events")

        print("\n4. Filtering by status=confirmed...")
        results = await get_events(status="confirmed", db=db)
        assert len(results) == 1, "Should return 1 confirmed event"
        assert results[0].status == "confirmed", "Event should be confirmed"
        print(f"   ✓ Retrieved {len(results)} confirmed event")

        print("\n5. Testing limit and offset...")
        results = await get_events(limit=2, offset=0, db=db)
        assert len(results) == 2, "Should return 2 events with limit=2"
        print(f"   ✓ Limit works: retrieved {len(results)} events")

        results = await get_events(limit=2, offset=2, db=db)
        assert len(results) == 1, "Should return 1 event with offset=2"
        print(f"   ✓ Offset works: retrieved {len(results)} event")

        print("\n6. Combining filters (owner_user_id + status)...")
        results = await get_events(owner_user_id=123456, status="confirmed", db=db)
        assert len(results) == 1, "Should return 1 confirmed event for user 123456"
        assert results[0].description == "User 1 confirmed event", "Should be the confirmed event"
        print(f"   ✓ Retrieved {len(results)} confirmed event for user 123456")

        print("\n" + "-"*60)
        print("✓ GET EVENTS WITH FILTERS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_event_404():
    """Test 404 error when updating non-existent event."""
    print("\n" + "="*60)
    print("TESTING 404 ON UPDATE NON-EXISTENT EVENT")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Attempting to update non-existent event...")
        event_update = EventUpdate(description="Updated")
        try:
            await update_event("non-existent-id", event_update, db)
            assert False, "Should raise HTTPException"
        except Exception as e:
            assert "404" in str(e) or "not found" in str(e).lower(), "Should return 404"
            print("   ✓ 404 raised for non-existent event")

        print("\n" + "-"*60)
        print("✓ 404 ON UPDATE NON-EXISTENT EVENT TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_double_confirm_event():
    """Test that confirming an already confirmed event doesn't create duplicate reminder."""
    print("\n" + "="*60)
    print("TESTING DOUBLE CONFIRM EVENT")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating and confirming an event...")
        event_time = datetime.now(timezone.utc) + timedelta(days=7)
        event_create = EventCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            event_time=event_time,
            description="Meeting",
            source_type="manual",
        )
        created = await create_event(event_create, db)
        event_id = created.id

        # First confirmation
        result1 = await update_event(event_id, EventUpdate(status="confirmed"), db)
        first_reminder_id = result1.reminder_id
        assert first_reminder_id is not None, "First reminder should be created"
        print(f"   ✓ Event confirmed, reminder ID: {first_reminder_id}")

        print("\n2. Confirming again (should not create duplicate reminder)...")
        # Second confirmation
        result2 = await update_event(event_id, EventUpdate(status="confirmed"), db)
        second_reminder_id = result2.reminder_id

        # Should still have the same reminder_id
        assert second_reminder_id == first_reminder_id, "Reminder ID should remain the same"
        print(f"   ✓ Reminder ID unchanged: {second_reminder_id}")

        # Verify only one reminder exists
        cursor = await db.execute("SELECT COUNT(*) FROM reminders")
        count = (await cursor.fetchone())[0]
        assert count == 1, "Should only have 1 reminder"
        print("   ✓ No duplicate reminder created")

        print("\n" + "-"*60)
        print("✓ DOUBLE CONFIRM EVENT TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("EVENTS ROUTER TEST SUITE")
    print("="*60)

    tests = [
        test_create_event,
        test_create_event_without_memory,
        test_update_event_basic_fields,
        test_confirm_event_creates_reminder,
        test_confirm_event_without_memory_skips_reminder,
        test_reject_event,
        test_confirm_event_with_updated_time_and_description,
        test_get_events_no_filter,
        test_get_events_with_filters,
        test_update_event_404,
        test_double_confirm_event,
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
