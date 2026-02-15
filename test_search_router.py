"""Test Group 5: Search router with FTS5 full-text search."""

import asyncio
import aiosqlite
import tempfile
import os
from pathlib import Path
from datetime import datetime

# Import the modules to test
import sys
sys.path.insert(0, str(Path(__file__).parent / 'core'))
sys.path.insert(0, str(Path(__file__).parent / 'shared'))

from core.database import init_db
from core.routers.search import search
from core.routers.memories import create_memory, add_tags_to_memory
from shared.schemas import MemoryCreate, TagsAddRequest


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


async def test_search_basic():
    """Test basic search functionality."""
    print("\n" + "="*60)
    print("TESTING BASIC SEARCH")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating test memories...")
        # Create memory 1: text about Python
        memory1 = MemoryCreate(
            owner_user_id=123456,
            content="Python programming tutorial for beginners",
            media_type=None,
        )
        created1 = await create_memory(memory1, db)
        print(f"   ✓ Memory 1 created: {created1.content}")

        # Create memory 2: text about JavaScript
        memory2 = MemoryCreate(
            owner_user_id=123456,
            content="JavaScript tutorial for advanced developers",
            media_type=None,
        )
        created2 = await create_memory(memory2, db)
        print(f"   ✓ Memory 2 created: {created2.content}")

        # Create memory 3: text about Python (different user)
        memory3 = MemoryCreate(
            owner_user_id=999999,
            content="Python data science tutorial",
            media_type=None,
        )
        created3 = await create_memory(memory3, db)
        print(f"   ✓ Memory 3 created: {created3.content} (different user)")

        print("\n2. Searching for 'Python' for user 123456...")
        results = await search(q="Python", owner=123456, pinned=False, db=db)

        assert len(results) == 1, f"Should return 1 result, got {len(results)}"
        assert results[0].memory.id == created1.id, "Should return memory 1"
        assert results[0].memory.content == created1.content, "Content should match"
        assert results[0].score < 0, "FTS5 rank should be negative (lower is better)"
        print(f"   ✓ Found {len(results)} result(s) with score: {results[0].score}")

        print("\n3. Searching for 'JavaScript' for user 123456...")
        results = await search(q="JavaScript", owner=123456, pinned=False, db=db)

        assert len(results) == 1, f"Should return 1 result, got {len(results)}"
        assert results[0].memory.id == created2.id, "Should return memory 2"
        print(f"   ✓ Found {len(results)} result(s)")

        print("\n4. Searching for 'tutorial' (matches both memories)...")
        results = await search(q="tutorial", owner=123456, pinned=False, db=db)

        assert len(results) == 2, f"Should return 2 results, got {len(results)}"
        result_ids = {r.memory.id for r in results}
        assert created1.id in result_ids, "Should include memory 1"
        assert created2.id in result_ids, "Should include memory 2"
        print(f"   ✓ Found {len(results)} result(s)")

        print("\n5. Searching for 'Python' for different user (999999)...")
        results = await search(q="Python", owner=999999, pinned=False, db=db)

        assert len(results) == 1, f"Should return 1 result, got {len(results)}"
        assert results[0].memory.id == created3.id, "Should return memory 3"
        print(f"   ✓ Found {len(results)} result(s) for different user")

        print("\n" + "-"*60)
        print("✓ BASIC SEARCH TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_search_with_tags():
    """Test searching memories with tags."""
    print("\n" + "="*60)
    print("TESTING SEARCH WITH TAGS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a memory with tags...")
        memory = MemoryCreate(
            owner_user_id=123456,
            content="Machine learning project documentation",
            media_type=None,
        )
        created = await create_memory(memory, db)
        print(f"   ✓ Memory created: {created.content}")

        # Add tags
        tags_request = TagsAddRequest(
            tags=["python", "ml", "project"],
            status="confirmed",
        )
        tagged = await add_tags_to_memory(created.id, tags_request, db)
        print(f"   ✓ Tags added: {[tag.tag for tag in tagged.tags]}")

        print("\n2. Searching for content term 'machine'...")
        results = await search(q="machine", owner=123456, pinned=False, db=db)

        assert len(results) == 1, f"Should return 1 result, got {len(results)}"
        assert results[0].memory.id == created.id, "Should return the created memory"
        assert len(results[0].memory.tags) == 3, "Memory should have 3 tags"
        tag_names = {tag.tag for tag in results[0].memory.tags}
        assert tag_names == {"python", "ml", "project"}, "Tags should match"
        print(f"   ✓ Found memory with {len(results[0].memory.tags)} tags")

        print("\n3. Searching for tag term 'python'...")
        results = await search(q="python", owner=123456, pinned=False, db=db)

        assert len(results) == 1, f"Should return 1 result, got {len(results)}"
        assert results[0].memory.id == created.id, "Should find by tag"
        print("   ✓ Found memory by tag search")

        print("\n4. Verifying tag details in results...")
        for tag in results[0].memory.tags:
            assert tag.status == "confirmed", f"Tag {tag.tag} should be confirmed"
            assert tag.confirmed_at is not None, f"Tag {tag.tag} should have confirmed_at"
            assert tag.suggested_at is None, f"Tag {tag.tag} should not have suggested_at"
        print("   ✓ Tag details correctly populated")

        print("\n" + "-"*60)
        print("✓ SEARCH WITH TAGS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_search_pinned():
    """Test searching only pinned memories."""
    print("\n" + "="*60)
    print("TESTING SEARCH PINNED MEMORIES")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating test memories...")
        # Create unpinned memory
        memory1 = MemoryCreate(
            owner_user_id=123456,
            content="Regular Python memory",
            media_type=None,
        )
        created1 = await create_memory(memory1, db)
        print(f"   ✓ Unpinned memory created: {created1.content}")

        # Create pinned memory
        memory2 = MemoryCreate(
            owner_user_id=123456,
            content="Important Python note",
            media_type=None,
        )
        created2 = await create_memory(memory2, db)

        # Pin memory 2
        await db.execute(
            "UPDATE memories SET is_pinned = 1 WHERE id = ?",
            (created2.id,)
        )
        await db.commit()
        print(f"   ✓ Pinned memory created: {created2.content}")

        print("\n2. Searching for 'Python' without pinned filter...")
        results = await search(q="Python", owner=123456, pinned=False, db=db)

        assert len(results) == 2, f"Should return 2 results, got {len(results)}"
        # Pinned should come first
        assert results[0].memory.id == created2.id, "Pinned memory should be first"
        assert results[0].memory.is_pinned is True, "First result should be pinned"
        assert results[1].memory.id == created1.id, "Unpinned memory should be second"
        assert results[1].memory.is_pinned is False, "Second result should not be pinned"
        print(f"   ✓ Found {len(results)} results, pinned first")

        print("\n3. Searching for 'Python' with pinned=True filter...")
        results = await search(q="Python", owner=123456, pinned=True, db=db)

        assert len(results) == 1, f"Should return 1 result, got {len(results)}"
        assert results[0].memory.id == created2.id, "Should return only pinned memory"
        assert results[0].memory.is_pinned is True, "Result should be pinned"
        print(f"   ✓ Found {len(results)} pinned result")

        print("\n" + "-"*60)
        print("✓ SEARCH PINNED TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_search_empty_query():
    """Test that empty or whitespace-only queries return 400."""
    print("\n" + "="*60)
    print("TESTING EMPTY QUERY VALIDATION")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Testing empty string query...")
        try:
            await search(q="", owner=123456, pinned=False, db=db)
            assert False, "Should raise HTTPException for empty query"
        except Exception as e:
            assert "400" in str(e) or "empty" in str(e).lower(), "Should return 400 for empty query"
            print("   ✓ 400 raised for empty query")

        print("\n2. Testing whitespace-only query...")
        try:
            await search(q="   ", owner=123456, pinned=False, db=db)
            assert False, "Should raise HTTPException for whitespace query"
        except Exception as e:
            assert "400" in str(e) or "empty" in str(e).lower() or "whitespace" in str(e).lower(), "Should return 400 for whitespace query"
            print("   ✓ 400 raised for whitespace query")

        print("\n3. Testing tab/newline query...")
        try:
            await search(q="\t\n  \t", owner=123456, pinned=False, db=db)
            assert False, "Should raise HTTPException for whitespace query"
        except Exception as e:
            assert "400" in str(e) or "empty" in str(e).lower() or "whitespace" in str(e).lower(), "Should return 400 for whitespace query"
            print("   ✓ 400 raised for tab/newline query")

        print("\n" + "-"*60)
        print("✓ EMPTY QUERY VALIDATION TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_search_no_results():
    """Test search with no matching results."""
    print("\n" + "="*60)
    print("TESTING SEARCH WITH NO RESULTS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating a test memory...")
        memory = MemoryCreate(
            owner_user_id=123456,
            content="Python programming tutorial",
            media_type=None,
        )
        created = await create_memory(memory, db)
        print(f"   ✓ Memory created: {created.content}")

        print("\n2. Searching for non-existent term 'JavaScript'...")
        results = await search(q="JavaScript", owner=123456, pinned=False, db=db)

        assert len(results) == 0, f"Should return 0 results, got {len(results)}"
        assert isinstance(results, list), "Should return empty list"
        print("   ✓ Empty list returned for no matches")

        print("\n3. Searching for term in different user's memories...")
        # Create memory for different user
        memory2 = MemoryCreate(
            owner_user_id=999999,
            content="Rust programming guide",
            media_type=None,
        )
        await create_memory(memory2, db)

        results = await search(q="Rust", owner=123456, pinned=False, db=db)

        assert len(results) == 0, f"Should return 0 results for different user, got {len(results)}"
        print("   ✓ No results for different user's memories")

        print("\n" + "-"*60)
        print("✓ NO RESULTS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_search_pending_memories():
    """Test that pending memories are not returned in search results."""
    print("\n" + "="*60)
    print("TESTING SEARCH EXCLUDES PENDING MEMORIES")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating confirmed memory...")
        memory1 = MemoryCreate(
            owner_user_id=123456,
            content="Confirmed Python tutorial",
            media_type=None,
        )
        created1 = await create_memory(memory1, db)
        print(f"   ✓ Confirmed memory created: {created1.content}")

        print("\n2. Creating pending memory...")
        from shared.enums import MediaType
        memory2 = MemoryCreate(
            owner_user_id=123456,
            content="Pending Python guide",
            media_type=MediaType.image,
            media_file_id="file_123",
        )
        created2 = await create_memory(memory2, db)
        assert created2.status == "pending", "Memory should be pending"
        print(f"   ✓ Pending memory created: {created2.content} (status: {created2.status})")

        print("\n3. Searching for 'Python'...")
        results = await search(q="Python", owner=123456, pinned=False, db=db)

        assert len(results) == 1, f"Should return only 1 confirmed result, got {len(results)}"
        assert results[0].memory.id == created1.id, "Should return only confirmed memory"
        assert results[0].memory.status == "confirmed", "Result should be confirmed"
        print(f"   ✓ Found {len(results)} result (pending memory excluded)")

        print("\n" + "-"*60)
        print("✓ PENDING MEMORIES EXCLUSION TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_search_multi_word():
    """Test searching with multi-word queries."""
    print("\n" + "="*60)
    print("TESTING MULTI-WORD SEARCH")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating test memories...")
        memory1 = MemoryCreate(
            owner_user_id=123456,
            content="Python web development framework",
            media_type=None,
        )
        created1 = await create_memory(memory1, db)
        print(f"   ✓ Memory 1: {created1.content}")

        memory2 = MemoryCreate(
            owner_user_id=123456,
            content="JavaScript web application",
            media_type=None,
        )
        created2 = await create_memory(memory2, db)
        print(f"   ✓ Memory 2: {created2.content}")

        print("\n2. Searching for 'web development'...")
        results = await search(q="web development", owner=123456, pinned=False, db=db)

        # Both terms should match memory1, but only "web" matches memory2
        assert len(results) >= 1, f"Should return at least 1 result"
        # Memory 1 should be first because it matches both terms
        assert results[0].memory.id == created1.id, "Memory with both terms should rank higher"
        print(f"   ✓ Found {len(results)} result(s), best match first")

        print("\n3. Searching for 'Python framework'...")
        results = await search(q="Python framework", owner=123456, pinned=False, db=db)

        assert len(results) == 1, f"Should return 1 result, got {len(results)}"
        assert results[0].memory.id == created1.id, "Should match memory 1"
        print(f"   ✓ Found {len(results)} result for multi-word query")

        print("\n" + "-"*60)
        print("✓ MULTI-WORD SEARCH TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("SEARCH ROUTER TEST SUITE")
    print("="*60)

    tests = [
        test_search_basic,
        test_search_with_tags,
        test_search_pinned,
        test_search_empty_query,
        test_search_no_results,
        test_search_pending_memories,
        test_search_multi_word,
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
