"""Test Settings router."""

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

from core.database import init_db
from core.routers.settings import (
    get_user_settings,
    update_user_settings,
)
from shared.schemas import (
    UserSettingsUpdate,
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

    return db, db_path


async def cleanup_test_db(db, db_path):
    """Close and remove test database."""
    await db.close()
    os.unlink(db_path)


async def test_get_settings_defaults():
    """Test getting settings for user without existing settings (should return defaults)."""
    print("\n" + "="*60)
    print("TESTING GET SETTINGS (DEFAULTS)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Fetching settings for user without existing settings...")
        result = await get_user_settings(user_id=123456, db=db)

        assert result.user_id == 123456, "user_id should match"
        assert result.timezone == "UTC", "Default timezone should be UTC"
        assert result.language == "en", "Default language should be en"
        assert result.created_at is not None, "created_at should be set"
        assert result.updated_at is not None, "updated_at should be set"
        print(f"   ✓ Returned defaults: timezone={result.timezone}, language={result.language}")

        # Verify no row was created in database
        cursor = await db.execute("SELECT COUNT(*) FROM user_settings WHERE user_id = ?", (123456,))
        count = (await cursor.fetchone())[0]
        assert count == 0, "No row should be created in database"
        print("   ✓ No row created in database (as expected)")

        print("\n" + "-"*60)
        print("✓ GET SETTINGS (DEFAULTS) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_put_settings_new_user():
    """Test creating settings for a new user."""
    print("\n" + "="*60)
    print("TESTING PUT SETTINGS (NEW USER)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating settings for new user...")
        settings_update = UserSettingsUpdate(
            timezone="America/New_York",
            language="es",
        )
        result = await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        assert result.user_id == 123456, "user_id should match"
        assert result.timezone == "America/New_York", "timezone should match"
        assert result.language == "es", "language should match"
        assert result.created_at is not None, "created_at should be set"
        assert result.updated_at is not None, "updated_at should be set"
        print(f"   ✓ Settings created: timezone={result.timezone}, language={result.language}")

        # Verify row was created in database
        cursor = await db.execute("SELECT * FROM user_settings WHERE user_id = ?", (123456,))
        row = await cursor.fetchone()
        assert row is not None, "Row should be created in database"
        assert row["timezone"] == "America/New_York", "timezone should match in database"
        assert row["language"] == "es", "language should match in database"
        print("   ✓ Row created in database")

        # Verify audit log
        cursor = await db.execute(
            "SELECT action, actor FROM audit_log WHERE entity_id = ?",
            ("123456",)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist"
        assert audit_row[0] == "updated", "Audit action should be 'updated'"
        assert audit_row[1] == "user:123456", "Audit actor should be user:123456"
        print("   ✓ Audit log entry created")

        print("\n" + "-"*60)
        print("✓ PUT SETTINGS (NEW USER) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_put_settings_with_defaults():
    """Test creating settings with partial update (should use defaults for missing fields)."""
    print("\n" + "="*60)
    print("TESTING PUT SETTINGS (WITH DEFAULTS)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating settings with only timezone...")
        settings_update = UserSettingsUpdate(
            timezone="Europe/London",
        )
        result = await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        assert result.timezone == "Europe/London", "timezone should match"
        assert result.language == "en", "language should default to 'en'"
        print(f"   ✓ Settings created: timezone={result.timezone}, language={result.language}")

        print("\n2. Creating settings with only language for different user...")
        settings_update = UserSettingsUpdate(
            language="fr",
        )
        result = await update_user_settings(user_id=999999, settings_update=settings_update, db=db)

        assert result.timezone == "UTC", "timezone should default to 'UTC'"
        assert result.language == "fr", "language should match"
        print(f"   ✓ Settings created: timezone={result.timezone}, language={result.language}")

        print("\n" + "-"*60)
        print("✓ PUT SETTINGS (WITH DEFAULTS) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_put_settings_update_existing():
    """Test updating existing settings."""
    print("\n" + "="*60)
    print("TESTING PUT SETTINGS (UPDATE EXISTING)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating initial settings...")
        settings_update = UserSettingsUpdate(
            timezone="Asia/Tokyo",
            language="ja",
        )
        initial_result = await update_user_settings(user_id=123456, settings_update=settings_update, db=db)
        initial_created_at = initial_result.created_at
        initial_updated_at = initial_result.updated_at
        print(f"   ✓ Initial settings: timezone={initial_result.timezone}, language={initial_result.language}")

        # Small delay to ensure updated_at changes
        await asyncio.sleep(0.01)

        print("\n2. Updating timezone only...")
        settings_update = UserSettingsUpdate(
            timezone="Europe/Paris",
        )
        result = await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        assert result.timezone == "Europe/Paris", "timezone should be updated"
        assert result.language == "ja", "language should remain unchanged"
        assert result.created_at == initial_created_at, "created_at should not change"
        assert result.updated_at > initial_updated_at, "updated_at should be updated"
        print(f"   ✓ Settings updated: timezone={result.timezone}, language={result.language}")
        print(f"   ✓ created_at unchanged: {result.created_at == initial_created_at}")
        print(f"   ✓ updated_at changed: {result.updated_at > initial_updated_at}")

        # Small delay to ensure updated_at changes
        await asyncio.sleep(0.01)

        print("\n3. Updating language only...")
        second_updated_at = result.updated_at
        settings_update = UserSettingsUpdate(
            language="ko",
        )
        result = await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        assert result.timezone == "Europe/Paris", "timezone should remain unchanged"
        assert result.language == "ko", "language should be updated"
        assert result.created_at == initial_created_at, "created_at should not change"
        assert result.updated_at > second_updated_at, "updated_at should be updated"
        print(f"   ✓ Settings updated: timezone={result.timezone}, language={result.language}")

        # Small delay to ensure updated_at changes
        await asyncio.sleep(0.01)

        print("\n4. Updating both fields...")
        third_updated_at = result.updated_at
        settings_update = UserSettingsUpdate(
            timezone="America/Los_Angeles",
            language="zh",
        )
        result = await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        assert result.timezone == "America/Los_Angeles", "timezone should be updated"
        assert result.language == "zh", "language should be updated"
        assert result.created_at == initial_created_at, "created_at should not change"
        assert result.updated_at > third_updated_at, "updated_at should be updated"
        print(f"   ✓ Settings updated: timezone={result.timezone}, language={result.language}")

        print("\n" + "-"*60)
        print("✓ PUT SETTINGS (UPDATE EXISTING) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_settings_after_create():
    """Test getting settings after creating them."""
    print("\n" + "="*60)
    print("TESTING GET SETTINGS AFTER CREATE")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating settings...")
        settings_update = UserSettingsUpdate(
            timezone="Australia/Sydney",
            language="en",
        )
        created_result = await update_user_settings(user_id=123456, settings_update=settings_update, db=db)
        print(f"   ✓ Settings created: timezone={created_result.timezone}, language={created_result.language}")

        print("\n2. Fetching settings via GET...")
        result = await get_user_settings(user_id=123456, db=db)

        assert result.user_id == 123456, "user_id should match"
        assert result.timezone == "Australia/Sydney", "timezone should match"
        assert result.language == "en", "language should match"
        assert result.created_at == created_result.created_at, "created_at should match"
        assert result.updated_at == created_result.updated_at, "updated_at should match"
        print(f"   ✓ Retrieved settings: timezone={result.timezone}, language={result.language}")
        print("   ✓ Timestamps match")

        print("\n" + "-"*60)
        print("✓ GET SETTINGS AFTER CREATE TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_upsert_pattern():
    """Test that INSERT OR REPLACE upsert pattern works correctly."""
    print("\n" + "="*60)
    print("TESTING UPSERT PATTERN")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Verifying table is empty...")
        cursor = await db.execute("SELECT COUNT(*) FROM user_settings WHERE user_id = ?", (123456,))
        count = (await cursor.fetchone())[0]
        assert count == 0, "Table should be empty initially"
        print("   ✓ Table is empty")

        print("\n2. First PUT (INSERT)...")
        settings_update = UserSettingsUpdate(
            timezone="UTC",
            language="en",
        )
        await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        cursor = await db.execute("SELECT COUNT(*) FROM user_settings WHERE user_id = ?", (123456,))
        count = (await cursor.fetchone())[0]
        assert count == 1, "Should have 1 row after first PUT"
        print("   ✓ Row inserted")

        print("\n3. Second PUT (REPLACE)...")
        settings_update = UserSettingsUpdate(
            timezone="Asia/Singapore",
            language="zh",
        )
        await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        cursor = await db.execute("SELECT COUNT(*) FROM user_settings WHERE user_id = ?", (123456,))
        count = (await cursor.fetchone())[0]
        assert count == 1, "Should still have 1 row after second PUT"
        print("   ✓ Row replaced (not duplicated)")

        # Verify values
        cursor = await db.execute("SELECT * FROM user_settings WHERE user_id = ?", (123456,))
        row = await cursor.fetchone()
        assert row["timezone"] == "Asia/Singapore", "timezone should be updated"
        assert row["language"] == "zh", "language should be updated"
        print("   ✓ Values updated correctly")

        print("\n" + "-"*60)
        print("✓ UPSERT PATTERN TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_multiple_users():
    """Test settings for multiple users."""
    print("\n" + "="*60)
    print("TESTING MULTIPLE USERS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating settings for user 123456...")
        settings_update = UserSettingsUpdate(
            timezone="America/New_York",
            language="en",
        )
        result1 = await update_user_settings(user_id=123456, settings_update=settings_update, db=db)
        print(f"   ✓ User 123456: timezone={result1.timezone}, language={result1.language}")

        print("\n2. Creating settings for user 999999...")
        settings_update = UserSettingsUpdate(
            timezone="Europe/London",
            language="fr",
        )
        result2 = await update_user_settings(user_id=999999, settings_update=settings_update, db=db)
        print(f"   ✓ User 999999: timezone={result2.timezone}, language={result2.language}")

        print("\n3. Verifying both users have separate settings...")
        fetched1 = await get_user_settings(user_id=123456, db=db)
        fetched2 = await get_user_settings(user_id=999999, db=db)

        assert fetched1.timezone == "America/New_York", "User 123456 timezone should match"
        assert fetched1.language == "en", "User 123456 language should match"
        assert fetched2.timezone == "Europe/London", "User 999999 timezone should match"
        assert fetched2.language == "fr", "User 999999 language should match"
        print("   ✓ Both users have correct, separate settings")

        print("\n4. Verifying row count...")
        cursor = await db.execute("SELECT COUNT(*) FROM user_settings")
        count = (await cursor.fetchone())[0]
        assert count == 2, "Should have 2 rows"
        print(f"   ✓ Table has {count} rows")

        print("\n" + "-"*60)
        print("✓ MULTIPLE USERS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_empty_update():
    """Test updating with empty update object (should keep existing values)."""
    print("\n" + "="*60)
    print("TESTING EMPTY UPDATE")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating initial settings...")
        settings_update = UserSettingsUpdate(
            timezone="Asia/Tokyo",
            language="ja",
        )
        initial = await update_user_settings(user_id=123456, settings_update=settings_update, db=db)
        print(f"   ✓ Initial settings: timezone={initial.timezone}, language={initial.language}")

        await asyncio.sleep(0.01)

        print("\n2. Updating with empty object...")
        settings_update = UserSettingsUpdate()
        result = await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        assert result.timezone == "Asia/Tokyo", "timezone should remain unchanged"
        assert result.language == "ja", "language should remain unchanged"
        assert result.created_at == initial.created_at, "created_at should not change"
        assert result.updated_at > initial.updated_at, "updated_at should still be updated"
        print(f"   ✓ Settings unchanged: timezone={result.timezone}, language={result.language}")
        print(f"   ✓ updated_at still updated (as expected)")

        print("\n" + "-"*60)
        print("✓ EMPTY UPDATE TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_audit_log_tracking():
    """Test that all updates are tracked in audit log."""
    print("\n" + "="*60)
    print("TESTING AUDIT LOG TRACKING")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating initial settings...")
        settings_update = UserSettingsUpdate(
            timezone="UTC",
            language="en",
        )
        await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        # Count audit log entries
        cursor = await db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE entity_type = ? AND entity_id = ?",
            ("user_settings", "123456")
        )
        count1 = (await cursor.fetchone())[0]
        assert count1 == 1, "Should have 1 audit log entry"
        print(f"   ✓ Audit log has {count1} entry")

        print("\n2. Updating settings...")
        settings_update = UserSettingsUpdate(
            timezone="Asia/Tokyo",
        )
        await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        cursor = await db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE entity_type = ? AND entity_id = ?",
            ("user_settings", "123456")
        )
        count2 = (await cursor.fetchone())[0]
        assert count2 == 2, "Should have 2 audit log entries"
        print(f"   ✓ Audit log has {count2} entries")

        print("\n3. Updating settings again...")
        settings_update = UserSettingsUpdate(
            language="ja",
        )
        await update_user_settings(user_id=123456, settings_update=settings_update, db=db)

        cursor = await db.execute(
            "SELECT COUNT(*) FROM audit_log WHERE entity_type = ? AND entity_id = ?",
            ("user_settings", "123456")
        )
        count3 = (await cursor.fetchone())[0]
        assert count3 == 3, "Should have 3 audit log entries"
        print(f"   ✓ Audit log has {count3} entries")

        # Verify all entries have correct action and actor
        cursor = await db.execute(
            "SELECT action, actor FROM audit_log WHERE entity_type = ? AND entity_id = ?",
            ("user_settings", "123456")
        )
        rows = await cursor.fetchall()
        for row in rows:
            assert row["action"] == "updated", "All actions should be 'updated'"
            assert row["actor"] == "user:123456", "All actors should be 'user:123456'"
        print("   ✓ All audit entries have correct action and actor")

        print("\n" + "-"*60)
        print("✓ AUDIT LOG TRACKING TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("SETTINGS ROUTER TEST SUITE")
    print("="*60)

    tests = [
        test_get_settings_defaults,
        test_put_settings_new_user,
        test_put_settings_with_defaults,
        test_put_settings_update_existing,
        test_get_settings_after_create,
        test_upsert_pattern,
        test_multiple_users,
        test_empty_update,
        test_audit_log_tracking,
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
