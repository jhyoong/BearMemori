"""Test Backup router."""

import asyncio
import aiosqlite
import tempfile
import os
from pathlib import Path
from datetime import datetime, timezone

# Import the modules to test
import sys
sys.path.insert(0, str(Path(__file__).parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent / 'shared'))

from core_svc.database import init_db
from core_svc.routers.backup import get_backup_status
from fastapi import HTTPException


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

    return db, db_path


async def cleanup_test_db(db, db_path):
    """Close and remove test database."""
    await db.close()
    os.unlink(db_path)


async def test_get_backup_status_not_found():
    """Test getting backup status for user with no backups (should return 404)."""
    print("\n" + "="*60)
    print("TESTING GET BACKUP STATUS (NOT FOUND)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Attempting to fetch backup status for user without backups...")

        error_raised = False
        try:
            result = await get_backup_status(user_id=123456, db=db)
        except HTTPException as e:
            error_raised = True
            assert e.status_code == 404, "Should raise 404"
            assert "No backup job found" in e.detail, "Should have appropriate message"
            print(f"   ✓ 404 raised with message: {e.detail}")

        assert error_raised, "Should raise HTTPException"

        print("\n" + "-"*60)
        print("✓ GET BACKUP STATUS (NOT FOUND) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_backup_status_success():
    """Test getting backup status for user with completed backup."""
    print("\n" + "="*60)
    print("TESTING GET BACKUP STATUS (SUCCESS)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a completed backup job...")
        started_at = datetime.now(timezone.utc).isoformat()
        completed_at = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-001", 123456, started_at, completed_at, "completed", "/backups/user_123456.zip", None)
        )
        await db.commit()
        print("   ✓ Backup job created")

        print("\n2. Fetching backup status...")
        result = await get_backup_status(user_id=123456, db=db)

        assert result.backup_id == "backup-001", "backup_id should match"
        assert result.user_id == 123456, "user_id should match"
        assert result.status == "completed", "status should be completed"
        assert result.file_path == "/backups/user_123456.zip", "file_path should match"
        assert result.error_message is None, "error_message should be None"
        assert result.started_at is not None, "started_at should be set"
        assert result.completed_at is not None, "completed_at should be set"
        print(f"   ✓ Backup status retrieved: backup_id={result.backup_id}, status={result.status}")

        print("\n" + "-"*60)
        print("✓ GET BACKUP STATUS (SUCCESS) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_backup_status_in_progress():
    """Test getting backup status for user with in-progress backup."""
    print("\n" + "="*60)
    print("TESTING GET BACKUP STATUS (IN PROGRESS)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating an in-progress backup job...")
        started_at = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-002", 123456, started_at, None, "in_progress", None, None)
        )
        await db.commit()
        print("   ✓ In-progress backup job created")

        print("\n2. Fetching backup status...")
        result = await get_backup_status(user_id=123456, db=db)

        assert result.backup_id == "backup-002", "backup_id should match"
        assert result.user_id == 123456, "user_id should match"
        assert result.status == "in_progress", "status should be in_progress"
        assert result.file_path is None, "file_path should be None (not completed yet)"
        assert result.completed_at is None, "completed_at should be None (not completed yet)"
        assert result.error_message is None, "error_message should be None"
        assert result.started_at is not None, "started_at should be set"
        print(f"   ✓ Backup status retrieved: backup_id={result.backup_id}, status={result.status}")

        print("\n" + "-"*60)
        print("✓ GET BACKUP STATUS (IN PROGRESS) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_backup_status_failed():
    """Test getting backup status for user with failed backup."""
    print("\n" + "="*60)
    print("TESTING GET BACKUP STATUS (FAILED)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a failed backup job...")
        started_at = datetime.now(timezone.utc).isoformat()
        completed_at = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-003", 123456, started_at, completed_at, "failed", None, "Disk space full")
        )
        await db.commit()
        print("   ✓ Failed backup job created")

        print("\n2. Fetching backup status...")
        result = await get_backup_status(user_id=123456, db=db)

        assert result.backup_id == "backup-003", "backup_id should match"
        assert result.user_id == 123456, "user_id should match"
        assert result.status == "failed", "status should be failed"
        assert result.file_path is None, "file_path should be None (backup failed)"
        assert result.error_message == "Disk space full", "error_message should match"
        assert result.started_at is not None, "started_at should be set"
        assert result.completed_at is not None, "completed_at should be set"
        print(f"   ✓ Backup status retrieved: backup_id={result.backup_id}, status={result.status}")
        print(f"   ✓ Error message: {result.error_message}")

        print("\n" + "-"*60)
        print("✓ GET BACKUP STATUS (FAILED) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_backup_status_most_recent():
    """Test that the most recent backup is returned when multiple exist."""
    print("\n" + "="*60)
    print("TESTING GET BACKUP STATUS (MOST RECENT)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating multiple backup jobs for the same user...")

        # Older backup
        older_started = "2024-01-01T10:00:00Z"
        older_completed = "2024-01-01T10:30:00Z"
        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-old", 123456, older_started, older_completed, "completed", "/backups/old.zip", None)
        )

        # Middle backup
        middle_started = "2024-06-15T14:00:00Z"
        middle_completed = "2024-06-15T14:30:00Z"
        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-middle", 123456, middle_started, middle_completed, "completed", "/backups/middle.zip", None)
        )

        # Most recent backup
        recent_started = datetime.now(timezone.utc).isoformat()
        recent_completed = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-recent", 123456, recent_started, recent_completed, "completed", "/backups/recent.zip", None)
        )

        await db.commit()
        print("   ✓ Created 3 backup jobs")

        print("\n2. Fetching backup status (should return most recent)...")
        result = await get_backup_status(user_id=123456, db=db)

        assert result.backup_id == "backup-recent", "Should return most recent backup"
        assert result.file_path == "/backups/recent.zip", "file_path should be from recent backup"
        print(f"   ✓ Most recent backup returned: backup_id={result.backup_id}")

        # Verify count in database
        cursor = await db.execute("SELECT COUNT(*) FROM backup_jobs WHERE user_id = ?", (123456,))
        count = (await cursor.fetchone())[0]
        assert count == 3, "Should have 3 backups in database"
        print(f"   ✓ Total backups for user: {count}")

        print("\n" + "-"*60)
        print("✓ GET BACKUP STATUS (MOST RECENT) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_backup_status_multiple_users():
    """Test that backups are correctly isolated per user."""
    print("\n" + "="*60)
    print("TESTING GET BACKUP STATUS (MULTIPLE USERS)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating backup jobs for different users...")

        # User 123456 backup
        started1 = datetime.now(timezone.utc).isoformat()
        completed1 = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-user1", 123456, started1, completed1, "completed", "/backups/user1.zip", None)
        )

        # User 999999 backup
        started2 = datetime.now(timezone.utc).isoformat()
        completed2 = datetime.now(timezone.utc).isoformat()
        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-user2", 999999, started2, completed2, "completed", "/backups/user2.zip", None)
        )

        await db.commit()
        print("   ✓ Created backup jobs for 2 users")

        print("\n2. Fetching backup status for user 123456...")
        result1 = await get_backup_status(user_id=123456, db=db)
        assert result1.backup_id == "backup-user1", "Should return backup for user 123456"
        assert result1.user_id == 123456, "user_id should be 123456"
        assert result1.file_path == "/backups/user1.zip", "file_path should match user 123456"
        print(f"   ✓ User 123456 backup: {result1.backup_id}")

        print("\n3. Fetching backup status for user 999999...")
        result2 = await get_backup_status(user_id=999999, db=db)
        assert result2.backup_id == "backup-user2", "Should return backup for user 999999"
        assert result2.user_id == 999999, "user_id should be 999999"
        assert result2.file_path == "/backups/user2.zip", "file_path should match user 999999"
        print(f"   ✓ User 999999 backup: {result2.backup_id}")

        print("\n4. Verifying user isolation...")
        assert result1.backup_id != result2.backup_id, "Backups should be different"
        assert result1.file_path != result2.file_path, "File paths should be different"
        print("   ✓ Backups are correctly isolated per user")

        print("\n" + "-"*60)
        print("✓ GET BACKUP STATUS (MULTIPLE USERS) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_backup_status_datetime_parsing():
    """Test that datetime fields are parsed correctly from database."""
    print("\n" + "="*60)
    print("TESTING BACKUP STATUS DATETIME PARSING")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating backup job with specific datetime values...")

        # Use specific datetime values with different formats
        started_at = "2024-01-15T10:30:45.123456Z"
        completed_at = "2024-01-15T11:45:30.654321+00:00"

        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-datetime", 123456, started_at, completed_at, "completed", "/backups/test.zip", None)
        )
        await db.commit()
        print("   ✓ Backup job created")

        print("\n2. Fetching and verifying datetime parsing...")
        result = await get_backup_status(user_id=123456, db=db)

        assert isinstance(result.started_at, datetime), "started_at should be datetime object"
        assert isinstance(result.completed_at, datetime), "completed_at should be datetime object"
        print(f"   ✓ started_at parsed: {result.started_at}")
        print(f"   ✓ completed_at parsed: {result.completed_at}")

        # Verify the values are correct
        assert result.started_at.year == 2024, "Year should be 2024"
        assert result.started_at.month == 1, "Month should be 1"
        assert result.started_at.day == 15, "Day should be 15"
        print("   ✓ Datetime values are correct")

        print("\n" + "-"*60)
        print("✓ BACKUP STATUS DATETIME PARSING TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_backup_status_null_completed_at():
    """Test handling of NULL completed_at field."""
    print("\n" + "="*60)
    print("TESTING BACKUP STATUS NULL COMPLETED_AT")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating backup job with NULL completed_at...")
        started_at = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-null", 123456, started_at, None, "in_progress", None, None)
        )
        await db.commit()
        print("   ✓ Backup job created with NULL completed_at")

        print("\n2. Fetching and verifying NULL handling...")
        result = await get_backup_status(user_id=123456, db=db)

        assert result.completed_at is None, "completed_at should be None"
        assert result.started_at is not None, "started_at should not be None"
        print("   ✓ NULL completed_at handled correctly")

        print("\n" + "-"*60)
        print("✓ BACKUP STATUS NULL COMPLETED_AT TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_backup_status_all_optional_fields():
    """Test backup status with all optional fields set."""
    print("\n" + "="*60)
    print("TESTING BACKUP STATUS ALL OPTIONAL FIELDS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating backup job with all fields populated...")
        started_at = datetime.now(timezone.utc).isoformat()
        completed_at = datetime.now(timezone.utc).isoformat()

        await db.execute(
            """
            INSERT INTO backup_jobs
            (backup_id, user_id, started_at, completed_at, status, file_path, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("backup-full", 123456, started_at, completed_at, "failed", "/backups/attempt.zip", "Connection timeout")
        )
        await db.commit()
        print("   ✓ Backup job created with all fields")

        print("\n2. Fetching and verifying all fields...")
        result = await get_backup_status(user_id=123456, db=db)

        assert result.backup_id == "backup-full", "backup_id should match"
        assert result.user_id == 123456, "user_id should match"
        assert result.started_at is not None, "started_at should be set"
        assert result.completed_at is not None, "completed_at should be set"
        assert result.status == "failed", "status should be failed"
        assert result.file_path == "/backups/attempt.zip", "file_path should match"
        assert result.error_message == "Connection timeout", "error_message should match"
        print("   ✓ All fields verified")

        print("\n" + "-"*60)
        print("✓ BACKUP STATUS ALL OPTIONAL FIELDS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("BACKUP ROUTER TEST SUITE")
    print("="*60)

    tests = [
        test_get_backup_status_not_found,
        test_get_backup_status_success,
        test_get_backup_status_in_progress,
        test_get_backup_status_failed,
        test_get_backup_status_most_recent,
        test_get_backup_status_multiple_users,
        test_backup_status_datetime_parsing,
        test_backup_status_null_completed_at,
        test_backup_status_all_optional_fields,
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
