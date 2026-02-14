"""Test Tasks router with recurrence logic."""

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
from core.routers.tasks import (
    create_task,
    get_tasks,
    update_task,
    delete_task,
)
from shared.schemas import (
    TaskCreate,
    TaskUpdate,
)
from shared.enums import TaskState


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


async def test_create_task():
    """Test creating a basic task."""
    print("\n" + "="*60)
    print("TESTING CREATE TASK")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a basic task...")
        task_create = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="Complete project documentation",
            due_at=None,
            recurrence_minutes=None,
        )

        result = await create_task(task_create, db)

        assert result.id is not None, "Task ID should be set"
        assert result.memory_id == "memory-001", "Memory ID should match"
        assert result.owner_user_id == 123456, "Owner user ID should match"
        assert result.description == "Complete project documentation", "Description should match"
        assert result.state == "NOT_DONE", "State should default to NOT_DONE"
        assert result.due_at is None, "due_at should be None"
        assert result.recurrence_minutes is None, "recurrence_minutes should be None"
        assert result.completed_at is None, "completed_at should be None"
        print(f"   ✓ Task created with ID: {result.id}")
        print(f"   ✓ State: {result.state}")

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
        print("✓ CREATE TASK TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_create_task_with_due_date():
    """Test creating a task with a due date."""
    print("\n" + "="*60)
    print("TESTING CREATE TASK WITH DUE DATE")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a task with due_at...")
        due_at = datetime.now(timezone.utc) + timedelta(days=3)
        task_create = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="Task with deadline",
            due_at=due_at,
            recurrence_minutes=None,
        )

        result = await create_task(task_create, db)

        assert result.due_at is not None, "due_at should be set"
        # Compare timestamps (allow small difference for processing time)
        time_diff = abs((result.due_at - due_at).total_seconds())
        assert time_diff < 2, "due_at should match the input"
        print(f"   ✓ Task created with due_at: {result.due_at}")

        print("\n" + "-"*60)
        print("✓ CREATE TASK WITH DUE DATE TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_tasks_no_filter():
    """Test getting tasks without filters."""
    print("\n" + "="*60)
    print("TESTING GET TASKS (NO FILTER)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating multiple tasks...")
        task1 = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="Task 1",
        )
        task2 = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="Task 2",
        )
        task3 = TaskCreate(
            memory_id="memory-002",
            owner_user_id=999999,
            description="Task 3",
        )

        await create_task(task1, db)
        await create_task(task2, db)
        await create_task(task3, db)
        print("   ✓ Created 3 tasks")

        print("\n2. Fetching all tasks...")
        results = await get_tasks(db=db)

        assert len(results) == 3, "Should return all 3 tasks"
        print(f"   ✓ Retrieved {len(results)} tasks")

        # Verify tasks are ordered by created_at DESC (newest first)
        descriptions = [task.description for task in results]
        assert descriptions == ["Task 3", "Task 2", "Task 1"], "Tasks should be ordered by created_at DESC"
        print("   ✓ Tasks ordered by created_at DESC")

        print("\n" + "-"*60)
        print("✓ GET TASKS (NO FILTER) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_tasks_with_filters():
    """Test getting tasks with various filters."""
    print("\n" + "="*60)
    print("TESTING GET TASKS WITH FILTERS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating tasks with different properties...")
        now = datetime.now(timezone.utc)

        task1 = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="User 1 task - due soon",
            due_at=now + timedelta(days=1),
        )
        task2 = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="User 1 task - due later",
            due_at=now + timedelta(days=5),
        )
        task3 = TaskCreate(
            memory_id="memory-002",
            owner_user_id=999999,
            description="User 2 task",
            due_at=now + timedelta(days=3),
        )

        created_task1 = await create_task(task1, db)
        await create_task(task2, db)
        await create_task(task3, db)

        # Mark task1 as done
        await db.execute(
            "UPDATE tasks SET state = 'DONE', completed_at = ? WHERE id = ?",
            (now.isoformat() + 'Z', created_task1.id)
        )
        await db.commit()
        print("   ✓ Created 3 tasks (1 DONE, 2 NOT_DONE)")

        print("\n2. Filtering by owner_user_id...")
        results = await get_tasks(owner_user_id=123456, db=db)
        assert len(results) == 2, "Should return 2 tasks for user 123456"
        for task in results:
            assert task.owner_user_id == 123456, "All tasks should belong to user 123456"
        print(f"   ✓ Retrieved {len(results)} tasks for user 123456")

        print("\n3. Filtering by state...")
        results = await get_tasks(state="DONE", db=db)
        assert len(results) == 1, "Should return 1 DONE task"
        assert results[0].state == "DONE", "Task should be DONE"
        print(f"   ✓ Retrieved {len(results)} DONE task")

        print("\n4. Filtering by due_before...")
        due_before = now + timedelta(days=2)
        results = await get_tasks(due_before=due_before, db=db)
        assert len(results) == 1, "Should return 1 task due before 2 days from now"
        print(f"   ✓ Retrieved {len(results)} task due within 2 days")

        print("\n5. Filtering by due_after...")
        due_after = now + timedelta(days=2)
        results = await get_tasks(due_after=due_after, db=db)
        assert len(results) == 2, "Should return 2 tasks due after 2 days from now"
        print(f"   ✓ Retrieved {len(results)} tasks due after 2 days")

        print("\n6. Testing limit and offset...")
        results = await get_tasks(limit=2, offset=0, db=db)
        assert len(results) == 2, "Should return 2 tasks with limit=2"
        print(f"   ✓ Limit works: retrieved {len(results)} tasks")

        results = await get_tasks(limit=2, offset=2, db=db)
        assert len(results) == 1, "Should return 1 task with offset=2"
        print(f"   ✓ Offset works: retrieved {len(results)} task")

        print("\n" + "-"*60)
        print("✓ GET TASKS WITH FILTERS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_task_basic():
    """Test updating task description and due_at."""
    print("\n" + "="*60)
    print("TESTING UPDATE TASK (BASIC)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a task...")
        task_create = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="Original description",
            due_at=None,
        )
        created = await create_task(task_create, db)
        task_id = created.id
        print(f"   ✓ Task created with ID: {task_id}")

        print("\n2. Updating description and due_at...")
        new_due_at = datetime.now(timezone.utc) + timedelta(days=7)
        task_update = TaskUpdate(
            description="Updated description",
            due_at=new_due_at,
        )
        result = await update_task(task_id, task_update, db)

        assert result.task.description == "Updated description", "Description should be updated"
        assert result.task.due_at is not None, "due_at should be set"
        assert result.recurring_task_id is None, "No recurring task should be created"
        print("   ✓ Task updated successfully")

        # Verify audit log
        cursor = await db.execute(
            "SELECT action, detail FROM audit_log WHERE entity_id = ? AND action = 'updated'",
            (task_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist"
        detail = json.loads(audit_row[1]) if audit_row[1] else {}
        assert "description" in detail, "Audit detail should include 'description'"
        print("   ✓ Audit log entry created")

        print("\n" + "-"*60)
        print("✓ UPDATE TASK (BASIC) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_task_to_done_no_recurrence():
    """Test marking a task as DONE (no recurrence)."""
    print("\n" + "="*60)
    print("TESTING UPDATE TASK TO DONE (NO RECURRENCE)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a task without recurrence...")
        task_create = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="One-time task",
            recurrence_minutes=None,
        )
        created = await create_task(task_create, db)
        task_id = created.id
        print(f"   ✓ Task created with ID: {task_id}")

        print("\n2. Marking task as DONE...")
        task_update = TaskUpdate(state=TaskState.DONE)
        result = await update_task(task_id, task_update, db)

        assert result.task.state == "DONE", "State should be DONE"
        assert result.task.completed_at is not None, "completed_at should be set"
        assert result.recurring_task_id is None, "No recurring task should be created"
        print("   ✓ Task marked as DONE")
        print(f"   ✓ completed_at: {result.task.completed_at}")

        # Verify no new task was created
        cursor = await db.execute("SELECT COUNT(*) FROM tasks")
        count = (await cursor.fetchone())[0]
        assert count == 1, "Should still have only 1 task"
        print("   ✓ No recurring task created")

        print("\n" + "-"*60)
        print("✓ UPDATE TASK TO DONE (NO RECURRENCE) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_task_to_done_with_recurrence_and_due_at():
    """Test marking a recurring task as DONE (with due_at)."""
    print("\n" + "="*60)
    print("TESTING UPDATE TASK TO DONE (WITH RECURRENCE AND DUE_AT)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a recurring task with due_at...")
        original_due_at = datetime.now(timezone.utc) + timedelta(days=1)
        task_create = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="Daily standup",
            due_at=original_due_at,
            recurrence_minutes=1440,  # 24 hours = 1 day
        )
        created = await create_task(task_create, db)
        task_id = created.id
        print(f"   ✓ Task created with ID: {task_id}")
        print(f"   ✓ Original due_at: {created.due_at}")
        print(f"   ✓ Recurrence: {created.recurrence_minutes} minutes")

        print("\n2. Marking task as DONE...")
        task_update = TaskUpdate(state=TaskState.DONE)
        result = await update_task(task_id, task_update, db)

        assert result.task.state == "DONE", "Original task state should be DONE"
        assert result.task.completed_at is not None, "completed_at should be set"
        assert result.recurring_task_id is not None, "Recurring task should be created"
        print("   ✓ Original task marked as DONE")
        print(f"   ✓ Recurring task ID: {result.recurring_task_id}")

        # Verify new recurring task
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (result.recurring_task_id,)
        )
        new_task = await cursor.fetchone()
        assert new_task is not None, "New recurring task should exist"
        assert new_task["state"] == "NOT_DONE", "New task state should be NOT_DONE"
        assert new_task["description"] == "Daily standup", "Description should match original"
        assert new_task["recurrence_minutes"] == 1440, "recurrence_minutes should match original"
        assert new_task["memory_id"] == "memory-001", "memory_id should match original"
        assert new_task["owner_user_id"] == 123456, "owner_user_id should match original"
        assert new_task["completed_at"] is None, "New task should not be completed"

        # Verify new due_at is original due_at + recurrence_minutes
        new_due_at = datetime.fromisoformat(new_task["due_at"].replace('Z', '+00:00'))
        expected_due_at = original_due_at + timedelta(minutes=1440)
        time_diff = abs((new_due_at - expected_due_at).total_seconds())
        assert time_diff < 2, "New due_at should be original due_at + recurrence_minutes"
        print(f"   ✓ New task due_at: {new_due_at}")
        print(f"   ✓ Expected due_at: {expected_due_at}")

        # Verify audit log for new task
        cursor = await db.execute(
            "SELECT action, actor, detail FROM audit_log WHERE entity_id = ?",
            (result.recurring_task_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist for new task"
        assert audit_row[0] == "created", "Audit action should be 'created'"
        detail = json.loads(audit_row[2]) if audit_row[2] else {}
        assert detail.get("reason") == "recurring_task", "Audit detail should indicate recurring_task"
        assert detail.get("parent_task_id") == task_id, "Audit detail should reference parent task"
        print("   ✓ Audit log entry created for recurring task")

        print("\n" + "-"*60)
        print("✓ UPDATE TASK TO DONE (WITH RECURRENCE AND DUE_AT) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_task_to_done_with_recurrence_no_due_at():
    """Test marking a recurring task as DONE (without due_at)."""
    print("\n" + "="*60)
    print("TESTING UPDATE TASK TO DONE (WITH RECURRENCE, NO DUE_AT)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a recurring task without due_at...")
        task_create = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="Weekly review",
            due_at=None,
            recurrence_minutes=10080,  # 7 days
        )
        created = await create_task(task_create, db)
        task_id = created.id
        print(f"   ✓ Task created with ID: {task_id}")
        print(f"   ✓ Recurrence: {created.recurrence_minutes} minutes")

        print("\n2. Marking task as DONE...")
        before_update = datetime.now(timezone.utc)
        task_update = TaskUpdate(state=TaskState.DONE)
        result = await update_task(task_id, task_update, db)

        assert result.recurring_task_id is not None, "Recurring task should be created"
        print(f"   ✓ Recurring task ID: {result.recurring_task_id}")

        # Verify new recurring task
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE id = ?",
            (result.recurring_task_id,)
        )
        new_task = await cursor.fetchone()
        assert new_task is not None, "New recurring task should exist"

        # Verify new due_at is approximately now + recurrence_minutes
        new_due_at = datetime.fromisoformat(new_task["due_at"].replace('Z', '+00:00'))
        expected_due_at = before_update + timedelta(minutes=10080)
        time_diff = abs((new_due_at - expected_due_at).total_seconds())
        assert time_diff < 5, "New due_at should be approximately now + recurrence_minutes"
        print(f"   ✓ New task due_at: {new_due_at}")
        print(f"   ✓ Due_at set to ~7 days from completion")

        print("\n" + "-"*60)
        print("✓ UPDATE TASK TO DONE (WITH RECURRENCE, NO DUE_AT) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_task_already_done():
    """Test updating a task that's already DONE (should not create duplicate recurring tasks)."""
    print("\n" + "="*60)
    print("TESTING UPDATE TASK ALREADY DONE")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a recurring task...")
        task_create = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="Recurring task",
            recurrence_minutes=60,
        )
        created = await create_task(task_create, db)
        task_id = created.id
        print(f"   ✓ Task created with ID: {task_id}")

        print("\n2. Marking task as DONE (first time)...")
        task_update = TaskUpdate(state=TaskState.DONE)
        result1 = await update_task(task_id, task_update, db)
        assert result1.recurring_task_id is not None, "Recurring task should be created"
        print(f"   ✓ First recurring task created: {result1.recurring_task_id}")

        print("\n3. Updating task description while already DONE...")
        task_update = TaskUpdate(description="Updated description")
        result2 = await update_task(task_id, task_update, db)
        assert result2.recurring_task_id is None, "No new recurring task should be created"
        print("   ✓ No duplicate recurring task created")

        # Verify total task count
        cursor = await db.execute("SELECT COUNT(*) FROM tasks")
        count = (await cursor.fetchone())[0]
        assert count == 2, "Should have exactly 2 tasks (original + 1 recurring)"
        print("   ✓ Task count is correct (2 tasks)")

        print("\n" + "-"*60)
        print("✓ UPDATE TASK ALREADY DONE TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_delete_task():
    """Test deleting a task."""
    print("\n" + "="*60)
    print("TESTING DELETE TASK")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a task...")
        task_create = TaskCreate(
            memory_id="memory-001",
            owner_user_id=123456,
            description="Task to delete",
        )
        created = await create_task(task_create, db)
        task_id = created.id
        print(f"   ✓ Task created with ID: {task_id}")

        print("\n2. Deleting the task...")
        await delete_task(task_id, db)

        # Verify task is deleted
        cursor = await db.execute("SELECT COUNT(*) FROM tasks WHERE id = ?", (task_id,))
        count = (await cursor.fetchone())[0]
        assert count == 0, "Task should be deleted"
        print("   ✓ Task deleted from database")

        # Verify audit log
        cursor = await db.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? AND action = 'deleted'",
            (task_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist for deletion"
        print("   ✓ Audit log entry created")

        print("\n3. Testing 404 for non-existent task...")
        try:
            await delete_task("non-existent-id", db)
            assert False, "Should raise HTTPException"
        except Exception as e:
            assert "404" in str(e) or "not found" in str(e).lower(), "Should return 404"
            print("   ✓ 404 raised for non-existent task")

        print("\n" + "-"*60)
        print("✓ DELETE TASK TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_404_on_update_nonexistent_task():
    """Test 404 error when updating non-existent task."""
    print("\n" + "="*60)
    print("TESTING 404 ON UPDATE NON-EXISTENT TASK")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Attempting to update non-existent task...")
        task_update = TaskUpdate(description="Updated")
        try:
            await update_task("non-existent-id", task_update, db)
            assert False, "Should raise HTTPException"
        except Exception as e:
            assert "404" in str(e) or "not found" in str(e).lower(), "Should return 404"
            print("   ✓ 404 raised for non-existent task")

        print("\n" + "-"*60)
        print("✓ 404 ON UPDATE NON-EXISTENT TASK TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("TASKS ROUTER TEST SUITE")
    print("="*60)

    tests = [
        test_create_task,
        test_create_task_with_due_date,
        test_get_tasks_no_filter,
        test_get_tasks_with_filters,
        test_update_task_basic,
        test_update_task_to_done_no_recurrence,
        test_update_task_to_done_with_recurrence_and_due_at,
        test_update_task_to_done_with_recurrence_no_due_at,
        test_update_task_already_done,
        test_delete_task,
        test_404_on_update_nonexistent_task,
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
