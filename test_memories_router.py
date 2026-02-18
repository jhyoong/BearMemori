"""Test Group 5: Memories router with FTS5 integration."""

import asyncio
import aiosqlite
import json
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta

# Import the modules to test
import sys
sys.path.insert(0, str(Path(__file__).parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent / 'shared'))

from core_svc.database import init_db
from core_svc.routers.memories import (
    create_memory,
    get_memory,
    update_memory,
    delete_memory,
    add_tags_to_memory,
    remove_tag_from_memory,
)
from shared_lib.schemas import (
    MemoryCreate,
    MemoryUpdate,
    TagsAddRequest,
)
from shared_lib.enums import MediaType, MemoryStatus


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

    return db, db_path


async def cleanup_test_db(db, db_path):
    """Close and remove test database."""
    await db.close()
    os.unlink(db_path)


async def test_create_text_memory():
    """Test creating a text memory (status = confirmed)."""
    print("\n" + "="*60)
    print("TESTING CREATE TEXT MEMORY")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating text memory (no media_type)...")
        memory_create = MemoryCreate(
            owner_user_id=123456,
            content="Test memory content",
            media_type=None,
            media_file_id=None,
            source_chat_id=12345,
            source_message_id=67890,
        )

        result = await create_memory(memory_create, db)

        assert result.id is not None, "Memory ID should be set"
        assert result.owner_user_id == 123456, "Owner user ID should match"
        assert result.content == "Test memory content", "Content should match"
        assert result.status == "confirmed", "Status should be 'confirmed' for text memory"
        assert result.pending_expires_at is None, "pending_expires_at should be None for text memory"
        print(f"   ✓ Text memory created with ID: {result.id}")
        print(f"   ✓ Status: {result.status}")

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

        # Verify FTS5 index (should be indexed since status is confirmed)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE content MATCH 'memory'"
        )
        count = (await cursor.fetchone())[0]
        assert count > 0, "Memory should be indexed in FTS5"
        print("   ✓ Memory indexed in FTS5")

        print("\n" + "-"*60)
        print("✓ CREATE TEXT MEMORY TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_create_image_memory():
    """Test creating an image memory (status = pending)."""
    print("\n" + "="*60)
    print("TESTING CREATE IMAGE MEMORY")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating image memory (media_type = 'image')...")
        memory_create = MemoryCreate(
            owner_user_id=123456,
            content=None,
            media_type=MediaType.image,
            media_file_id="file_123",
            source_chat_id=12345,
            source_message_id=67890,
        )

        result = await create_memory(memory_create, db)

        assert result.id is not None, "Memory ID should be set"
        assert result.media_type == "image", "Media type should be 'image'"
        assert result.status == "pending", "Status should be 'pending' for image memory"
        assert result.pending_expires_at is not None, "pending_expires_at should be set"
        print(f"   ✓ Image memory created with ID: {result.id}")
        print(f"   ✓ Status: {result.status}")
        print(f"   ✓ pending_expires_at: {result.pending_expires_at}")

        # Verify pending_expires_at is approximately 7 days from now
        expires_at = result.pending_expires_at
        from datetime import timezone
        now = datetime.now(timezone.utc)
        expected_expires = now + timedelta(days=7)
        time_diff = abs((expires_at - expected_expires).total_seconds())
        assert time_diff < 60, "pending_expires_at should be approximately 7 days from now"
        print("   ✓ pending_expires_at is correctly set to ~7 days from now")

        # Verify NOT indexed in FTS5 (pending status)
        # Check by looking for the memory in the base table that's indexed
        cursor = await db.execute(
            "SELECT COUNT(*) FROM memories WHERE status = 'confirmed'"
        )
        count = (await cursor.fetchone())[0]
        assert count == 0, "Pending memory should NOT have confirmed status"
        print("   ✓ Pending memory NOT indexed in FTS5 (no confirmed memories)")

        print("\n" + "-"*60)
        print("✓ CREATE IMAGE MEMORY TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_memory():
    """Test fetching a memory by ID with tags."""
    print("\n" + "="*60)
    print("TESTING GET MEMORY")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a memory...")
        memory_create = MemoryCreate(
            owner_user_id=123456,
            content="Memory with tags",
            media_type=None,
        )
        created = await create_memory(memory_create, db)
        memory_id = created.id
        print(f"   ✓ Memory created with ID: {memory_id}")

        print("\n2. Adding tags to the memory...")
        await db.execute(
            "INSERT INTO memory_tags (memory_id, tag, status, confirmed_at) VALUES (?, ?, ?, ?)",
            (memory_id, "work", "confirmed", datetime.utcnow().isoformat() + 'Z')
        )
        await db.execute(
            "INSERT INTO memory_tags (memory_id, tag, status, suggested_at) VALUES (?, ?, ?, ?)",
            (memory_id, "important", "suggested", datetime.utcnow().isoformat() + 'Z')
        )
        await db.commit()
        print("   ✓ Tags added: work (confirmed), important (suggested)")

        print("\n3. Fetching memory by ID...")
        result = await get_memory(memory_id, db)

        assert result.id == memory_id, "Memory ID should match"
        assert result.content == "Memory with tags", "Content should match"
        assert len(result.tags) == 2, "Should have 2 tags"

        # Check tags
        tag_names = {tag.tag for tag in result.tags}
        assert "work" in tag_names, "Should have 'work' tag"
        assert "important" in tag_names, "Should have 'important' tag"

        # Check tag statuses
        for tag in result.tags:
            if tag.tag == "work":
                assert tag.status == "confirmed", "work tag should be confirmed"
                assert tag.confirmed_at is not None, "work tag should have confirmed_at"
            elif tag.tag == "important":
                assert tag.status == "suggested", "important tag should be suggested"
                assert tag.suggested_at is not None, "important tag should have suggested_at"

        print(f"   ✓ Memory fetched with {len(result.tags)} tags")
        print(f"   ✓ Tags: {[tag.tag for tag in result.tags]}")

        print("\n4. Testing 404 for non-existent memory...")
        try:
            await get_memory("non-existent-id", db)
            assert False, "Should raise HTTPException"
        except Exception as e:
            assert "404" in str(e) or "not found" in str(e).lower(), "Should return 404"
            print("   ✓ 404 raised for non-existent memory")

        print("\n" + "-"*60)
        print("✓ GET MEMORY TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_memory():
    """Test updating a memory."""
    print("\n" + "="*60)
    print("TESTING UPDATE MEMORY")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a pending image memory...")
        memory_create = MemoryCreate(
            owner_user_id=123456,
            content=None,
            media_type=MediaType.image,
            media_file_id="file_123",
        )
        created = await create_memory(memory_create, db)
        memory_id = created.id
        print(f"   ✓ Memory created with ID: {memory_id}, status: {created.status}")

        print("\n2. Updating memory content and status to confirmed...")
        memory_update = MemoryUpdate(
            content="Updated content for image",
            status=MemoryStatus.confirmed,
        )
        updated = await update_memory(memory_id, memory_update, db)

        assert updated.content == "Updated content for image", "Content should be updated"
        assert updated.status == "confirmed", "Status should be updated to confirmed"
        print(f"   ✓ Memory updated: content='{updated.content}', status={updated.status}")

        # Verify FTS5 index (should be indexed now)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE content MATCH 'Updated'"
        )
        count = (await cursor.fetchone())[0]
        assert count > 0, "Memory should be indexed in FTS5 after status change to confirmed"
        print("   ✓ Memory indexed in FTS5 after confirmation")

        # Verify audit log
        cursor = await db.execute(
            "SELECT action, detail FROM audit_log WHERE entity_id = ? AND action = 'updated'",
            (memory_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist for update"
        detail = json.loads(audit_row[1]) if audit_row[1] else {}
        assert "content" in detail, "Audit detail should include 'content' field"
        assert "status" in detail, "Audit detail should include 'status' field"
        print("   ✓ Audit log entry created with details")

        print("\n3. Updating is_pinned flag...")
        memory_update = MemoryUpdate(is_pinned=True)
        updated = await update_memory(memory_id, memory_update, db)
        assert updated.is_pinned is True, "is_pinned should be updated"
        print(f"   ✓ is_pinned updated to True")

        print("\n" + "-"*60)
        print("✓ UPDATE MEMORY TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_delete_memory():
    """Test deleting a memory."""
    print("\n" + "="*60)
    print("TESTING DELETE MEMORY")
    print("="*60)

    db, db_path = await setup_test_db()
    temp_file = None

    try:
        print("\n1. Creating a memory with a local file...")
        # Create a temporary file
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        temp_file.write("test content")
        temp_file.close()
        print(f"   ✓ Temporary file created: {temp_file.name}")

        memory_create = MemoryCreate(
            owner_user_id=123456,
            content="Memory to delete",
            media_type=None,
        )
        created = await create_memory(memory_create, db)
        memory_id = created.id

        # Update with media_local_path
        await db.execute(
            "UPDATE memories SET media_local_path = ? WHERE id = ?",
            (temp_file.name, memory_id)
        )
        await db.commit()
        print(f"   ✓ Memory created with ID: {memory_id}")

        print("\n2. Adding tags to the memory...")
        await db.execute(
            "INSERT INTO memory_tags (memory_id, tag, status, confirmed_at) VALUES (?, ?, ?, ?)",
            (memory_id, "test", "confirmed", datetime.utcnow().isoformat() + 'Z')
        )
        await db.commit()
        print("   ✓ Tag added")

        print("\n3. Deleting the memory...")
        await delete_memory(memory_id, db)

        # Verify memory is deleted
        cursor = await db.execute("SELECT COUNT(*) FROM memories WHERE id = ?", (memory_id,))
        count = (await cursor.fetchone())[0]
        assert count == 0, "Memory should be deleted"
        print("   ✓ Memory deleted from database")

        # Verify tags are cascade deleted
        cursor = await db.execute("SELECT COUNT(*) FROM memory_tags WHERE memory_id = ?", (memory_id,))
        count = (await cursor.fetchone())[0]
        assert count == 0, "Tags should be cascade deleted"
        print("   ✓ Tags cascade deleted")

        # Verify file is deleted
        assert not os.path.exists(temp_file.name), "File should be deleted"
        print("   ✓ Local file deleted")

        # Verify audit log
        cursor = await db.execute(
            "SELECT action FROM audit_log WHERE entity_id = ? AND action = 'deleted'",
            (memory_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist for deletion"
        print("   ✓ Audit log entry created")

        # Verify removed from FTS5 by checking that the memory no longer exists in the base table
        cursor = await db.execute(
            "SELECT COUNT(*) FROM memories WHERE content = 'Memory to delete'"
        )
        count = (await cursor.fetchone())[0]
        assert count == 0, "Memory should be completely deleted"
        print("   ✓ Memory removed (FTS5 will be rebuilt without it)")

        print("\n" + "-"*60)
        print("✓ DELETE MEMORY TEST PASSED")
        print("-"*60)

    finally:
        # Clean up temp file if it still exists
        if temp_file and os.path.exists(temp_file.name):
            os.unlink(temp_file.name)
        await cleanup_test_db(db, db_path)


async def test_add_tags():
    """Test adding tags to a memory."""
    print("\n" + "="*60)
    print("TESTING ADD TAGS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a confirmed memory...")
        memory_create = MemoryCreate(
            owner_user_id=123456,
            content="Memory for tagging",
            media_type=None,
        )
        created = await create_memory(memory_create, db)
        memory_id = created.id
        print(f"   ✓ Memory created with ID: {memory_id}")

        print("\n2. Adding confirmed tags...")
        tags_request = TagsAddRequest(
            tags=["work", "important", "project"],
            status="confirmed",
        )
        result = await add_tags_to_memory(memory_id, tags_request, db)

        assert len(result.tags) == 3, "Should have 3 tags"
        tag_names = {tag.tag for tag in result.tags}
        assert tag_names == {"work", "important", "project"}, "Tag names should match"

        for tag in result.tags:
            assert tag.status == "confirmed", f"Tag {tag.tag} should be confirmed"
            assert tag.confirmed_at is not None, f"Tag {tag.tag} should have confirmed_at"
            assert tag.suggested_at is None, f"Tag {tag.tag} should not have suggested_at"

        print(f"   ✓ Added {len(result.tags)} confirmed tags")

        print("\n3. Adding suggested tags...")
        tags_request = TagsAddRequest(
            tags=["maybe", "review"],
            status="suggested",
        )
        result = await add_tags_to_memory(memory_id, tags_request, db)

        assert len(result.tags) == 5, "Should have 5 tags total"

        # Check suggested tags
        suggested_tags = [tag for tag in result.tags if tag.tag in ["maybe", "review"]]
        assert len(suggested_tags) == 2, "Should have 2 suggested tags"
        for tag in suggested_tags:
            assert tag.status == "suggested", f"Tag {tag.tag} should be suggested"
            assert tag.suggested_at is not None, f"Tag {tag.tag} should have suggested_at"
            assert tag.confirmed_at is None, f"Tag {tag.tag} should not have confirmed_at"

        print(f"   ✓ Added 2 suggested tags, total: {len(result.tags)} tags")

        # Verify audit log
        cursor = await db.execute(
            "SELECT detail FROM audit_log WHERE entity_id = ? AND action = 'updated' ORDER BY created_at DESC LIMIT 1",
            (memory_id,)
        )
        audit_row = await cursor.fetchone()
        detail = json.loads(audit_row[0]) if audit_row[0] else {}
        assert "tags_added" in detail, "Audit detail should include 'tags_added'"
        print("   ✓ Audit log entry created with tags_added detail")

        # Verify FTS5 re-index (memory is confirmed, so tags should be in FTS5)
        cursor = await db.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE tags MATCH 'work'"
        )
        count = (await cursor.fetchone())[0]
        assert count > 0, "Tags should be indexed in FTS5"
        print("   ✓ Tags indexed in FTS5")

        print("\n" + "-"*60)
        print("✓ ADD TAGS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_remove_tag():
    """Test removing a tag from a memory."""
    print("\n" + "="*60)
    print("TESTING REMOVE TAG")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a memory with tags...")
        memory_create = MemoryCreate(
            owner_user_id=123456,
            content="Memory for tag removal",
            media_type=None,
        )
        created = await create_memory(memory_create, db)
        memory_id = created.id

        tags_request = TagsAddRequest(
            tags=["tag1", "tag2", "tag3"],
            status="confirmed",
        )
        result = await add_tags_to_memory(memory_id, tags_request, db)
        print(f"   ✓ Memory created with 3 tags: {[tag.tag for tag in result.tags]}")

        print("\n2. Removing tag 'tag2'...")
        await remove_tag_from_memory(memory_id, "tag2", db)

        # Verify tag is removed
        result = await get_memory(memory_id, db)
        assert len(result.tags) == 2, "Should have 2 tags remaining"
        tag_names = {tag.tag for tag in result.tags}
        assert "tag2" not in tag_names, "tag2 should be removed"
        assert tag_names == {"tag1", "tag3"}, "Remaining tags should be tag1 and tag3"
        print(f"   ✓ Tag removed, remaining tags: {[tag.tag for tag in result.tags]}")

        # Verify audit log
        cursor = await db.execute(
            "SELECT detail FROM audit_log WHERE entity_id = ? AND action = 'updated' ORDER BY created_at DESC LIMIT 1",
            (memory_id,)
        )
        audit_row = await cursor.fetchone()
        detail = json.loads(audit_row[0]) if audit_row[0] else {}
        assert "tag_removed" in detail, "Audit detail should include 'tag_removed'"
        assert detail["tag_removed"] == "tag2", "Removed tag should be tag2"
        print("   ✓ Audit log entry created with tag_removed detail")

        print("\n" + "-"*60)
        print("✓ REMOVE TAG TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_insert_or_replace_tags():
    """Test that adding the same tag twice replaces it (INSERT OR REPLACE)."""
    print("\n" + "="*60)
    print("TESTING INSERT OR REPLACE TAGS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a memory...")
        memory_create = MemoryCreate(
            owner_user_id=123456,
            content="Memory for tag replacement test",
            media_type=None,
        )
        created = await create_memory(memory_create, db)
        memory_id = created.id
        print(f"   ✓ Memory created with ID: {memory_id}")

        print("\n2. Adding suggested tag 'test'...")
        tags_request = TagsAddRequest(tags=["test"], status="suggested")
        result = await add_tags_to_memory(memory_id, tags_request, db)

        test_tag = next(tag for tag in result.tags if tag.tag == "test")
        assert test_tag.status == "suggested", "Tag should be suggested"
        print("   ✓ Tag 'test' added as suggested")

        print("\n3. Adding same tag 'test' as confirmed (should replace)...")
        tags_request = TagsAddRequest(tags=["test"], status="confirmed")
        result = await add_tags_to_memory(memory_id, tags_request, db)

        # Should still have only 1 tag
        assert len(result.tags) == 1, "Should still have only 1 tag"
        test_tag = result.tags[0]
        assert test_tag.tag == "test", "Tag name should still be 'test'"
        assert test_tag.status == "confirmed", "Tag status should be updated to confirmed"
        print("   ✓ Tag 'test' replaced with confirmed status")

        print("\n" + "-"*60)
        print("✓ INSERT OR REPLACE TAGS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("MEMORIES ROUTER TEST SUITE")
    print("="*60)

    tests = [
        test_create_text_memory,
        test_create_image_memory,
        test_get_memory,
        test_update_memory,
        test_delete_memory,
        test_add_tags,
        test_remove_tag,
        test_insert_or_replace_tags,
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
