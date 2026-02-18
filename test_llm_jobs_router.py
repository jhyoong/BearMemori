"""Test LLM jobs router."""

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
from core_svc.routers.llm_jobs import (
    create_llm_job,
    get_llm_job,
    update_llm_job,
    get_llm_jobs,
)
from shared_lib.schemas import (
    LLMJobCreate,
    LLMJobUpdate,
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


async def test_create_llm_job_with_user():
    """Test creating an LLM job with user_id."""
    print("\n" + "="*60)
    print("TESTING CREATE LLM JOB WITH USER")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating an LLM job with user_id...")
        job_create = LLMJobCreate(
            job_type="image_tag",
            payload={"memory_id": "mem-123", "image_url": "https://example.com/img.jpg"},
            user_id=123456,
        )

        result = await create_llm_job(job_create, db)

        assert result.id is not None, "Job ID should be set"
        assert result.job_type == "image_tag", "Job type should match"
        assert result.payload == {"memory_id": "mem-123", "image_url": "https://example.com/img.jpg"}, "Payload should match"
        assert result.user_id == 123456, "User ID should match"
        assert result.status == "queued", "Status should default to 'queued'"
        assert result.result is None, "Result should be None initially"
        assert result.error_message is None, "Error message should be None initially"
        assert result.created_at is not None, "created_at should be set"
        assert result.updated_at is not None, "updated_at should be set"
        print(f"   ✓ Job created with ID: {result.id}")
        print(f"   ✓ Status: {result.status}")
        print(f"   ✓ Job type: {result.job_type}")

        # Verify audit log
        cursor = await db.execute(
            "SELECT action, actor FROM audit_log WHERE entity_id = ?",
            (result.id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist"
        assert audit_row[0] == "created", "Audit action should be 'created'"
        assert audit_row[1] == "user:123456", "Audit actor should be user:123456"
        print("   ✓ Audit log entry created with user:123456")

        print("\n" + "-"*60)
        print("✓ CREATE LLM JOB WITH USER TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_create_llm_job_without_user():
    """Test creating an LLM job without user_id (system job)."""
    print("\n" + "="*60)
    print("TESTING CREATE LLM JOB WITHOUT USER")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating an LLM job without user_id...")
        job_create = LLMJobCreate(
            job_type="intent_classify",
            payload={"message": "Hello, how are you?"},
            user_id=None,
        )

        result = await create_llm_job(job_create, db)

        assert result.id is not None, "Job ID should be set"
        assert result.job_type == "intent_classify", "Job type should match"
        assert result.user_id is None, "User ID should be None"
        assert result.status == "queued", "Status should default to 'queued'"
        print(f"   ✓ Job created with ID: {result.id}")
        print(f"   ✓ User ID: None (system job)")

        # Verify audit log uses system:api actor
        cursor = await db.execute(
            "SELECT action, actor FROM audit_log WHERE entity_id = ?",
            (result.id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist"
        assert audit_row[0] == "created", "Audit action should be 'created'"
        assert audit_row[1] == "system:api", "Audit actor should be system:api"
        print("   ✓ Audit log entry created with system:api")

        print("\n" + "-"*60)
        print("✓ CREATE LLM JOB WITHOUT USER TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_llm_job():
    """Test getting an LLM job by ID."""
    print("\n" + "="*60)
    print("TESTING GET LLM JOB")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating an LLM job...")
        job_create = LLMJobCreate(
            job_type="task_match",
            payload={"task_description": "Buy groceries"},
            user_id=123456,
        )
        created = await create_llm_job(job_create, db)
        job_id = created.id
        print(f"   ✓ Job created with ID: {job_id}")

        print("\n2. Fetching job by ID...")
        result = await get_llm_job(job_id, db)

        assert result.id == job_id, "Job ID should match"
        assert result.job_type == "task_match", "Job type should match"
        assert result.payload == {"task_description": "Buy groceries"}, "Payload should match"
        assert result.user_id == 123456, "User ID should match"
        assert result.status == "queued", "Status should be 'queued'"
        print("   ✓ Job fetched successfully")

        print("\n" + "-"*60)
        print("✓ GET LLM JOB TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_llm_job_404():
    """Test 404 error when getting non-existent job."""
    print("\n" + "="*60)
    print("TESTING GET LLM JOB 404")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Attempting to get non-existent job...")
        try:
            await get_llm_job("non-existent-id", db)
            assert False, "Should raise HTTPException"
        except Exception as e:
            assert "404" in str(e) or "not found" in str(e).lower(), "Should return 404"
            print("   ✓ 404 raised for non-existent job")

        print("\n" + "-"*60)
        print("✓ GET LLM JOB 404 TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_llm_job_status():
    """Test updating LLM job status."""
    print("\n" + "="*60)
    print("TESTING UPDATE LLM JOB STATUS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating an LLM job...")
        job_create = LLMJobCreate(
            job_type="followup",
            payload={"context": "Previous conversation"},
            user_id=123456,
        )
        created = await create_llm_job(job_create, db)
        job_id = created.id
        print(f"   ✓ Job created with ID: {job_id}")
        print(f"   ✓ Initial status: {created.status}")

        print("\n2. Updating status to 'processing'...")
        job_update = LLMJobUpdate(status="processing")
        result = await update_llm_job(job_id, job_update, db)

        assert result.status == "processing", "Status should be 'processing'"
        print("   ✓ Status updated to 'processing'")

        print("\n3. Updating status to 'completed'...")
        job_update = LLMJobUpdate(status="completed")
        result = await update_llm_job(job_id, job_update, db)

        assert result.status == "completed", "Status should be 'completed'"
        print("   ✓ Status updated to 'completed'")

        # Verify updated_at changed
        assert result.updated_at > created.updated_at, "updated_at should be updated"
        print("   ✓ updated_at timestamp updated")

        print("\n" + "-"*60)
        print("✓ UPDATE LLM JOB STATUS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_llm_job_result():
    """Test updating LLM job with result."""
    print("\n" + "="*60)
    print("TESTING UPDATE LLM JOB RESULT")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating an LLM job...")
        job_create = LLMJobCreate(
            job_type="email_extract",
            payload={"email_body": "Meeting at 3pm tomorrow"},
            user_id=123456,
        )
        created = await create_llm_job(job_create, db)
        job_id = created.id
        print(f"   ✓ Job created with ID: {job_id}")

        print("\n2. Updating job with result...")
        result_data = {
            "event_time": "2024-01-15T15:00:00Z",
            "description": "Meeting",
            "confidence": 0.95,
        }
        job_update = LLMJobUpdate(
            status="completed",
            result=result_data,
        )
        result = await update_llm_job(job_id, job_update, db)

        assert result.status == "completed", "Status should be 'completed'"
        assert result.result == result_data, "Result should match"
        assert result.error_message is None, "Error message should still be None"
        print("   ✓ Result updated successfully")
        print(f"   ✓ Result data: {result.result}")

        print("\n" + "-"*60)
        print("✓ UPDATE LLM JOB RESULT TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_llm_job_error():
    """Test updating LLM job with error."""
    print("\n" + "="*60)
    print("TESTING UPDATE LLM JOB ERROR")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating an LLM job...")
        job_create = LLMJobCreate(
            job_type="image_tag",
            payload={"memory_id": "mem-456"},
            user_id=123456,
        )
        created = await create_llm_job(job_create, db)
        job_id = created.id
        print(f"   ✓ Job created with ID: {job_id}")

        print("\n2. Updating job with error...")
        job_update = LLMJobUpdate(
            status="failed",
            error_message="API rate limit exceeded",
        )
        result = await update_llm_job(job_id, job_update, db)

        assert result.status == "failed", "Status should be 'failed'"
        assert result.error_message == "API rate limit exceeded", "Error message should match"
        assert result.result is None, "Result should still be None"
        print("   ✓ Error message updated successfully")
        print(f"   ✓ Error: {result.error_message}")

        print("\n" + "-"*60)
        print("✓ UPDATE LLM JOB ERROR TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_llm_job_404():
    """Test 404 error when updating non-existent job."""
    print("\n" + "="*60)
    print("TESTING UPDATE LLM JOB 404")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Attempting to update non-existent job...")
        job_update = LLMJobUpdate(status="completed")
        try:
            await update_llm_job("non-existent-id", job_update, db)
            assert False, "Should raise HTTPException"
        except Exception as e:
            assert "404" in str(e) or "not found" in str(e).lower(), "Should return 404"
            print("   ✓ 404 raised for non-existent job")

        print("\n" + "-"*60)
        print("✓ UPDATE LLM JOB 404 TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_update_llm_job_audit_log():
    """Test that updating job creates audit log."""
    print("\n" + "="*60)
    print("TESTING UPDATE LLM JOB AUDIT LOG")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating an LLM job...")
        job_create = LLMJobCreate(
            job_type="intent_classify",
            payload={"message": "Test message"},
            user_id=123456,
        )
        created = await create_llm_job(job_create, db)
        job_id = created.id
        print(f"   ✓ Job created with ID: {job_id}")

        print("\n2. Updating job status...")
        job_update = LLMJobUpdate(status="completed")
        await update_llm_job(job_id, job_update, db)

        # Verify audit log
        cursor = await db.execute(
            "SELECT action, actor FROM audit_log WHERE entity_id = ? AND action = 'updated'",
            (job_id,)
        )
        audit_row = await cursor.fetchone()
        assert audit_row is not None, "Audit log entry should exist"
        assert audit_row[0] == "updated", "Audit action should be 'updated'"
        assert audit_row[1] == "system:llm_worker", "Audit actor should be system:llm_worker"
        print("   ✓ Audit log entry created with system:llm_worker")

        print("\n" + "-"*60)
        print("✓ UPDATE LLM JOB AUDIT LOG TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_llm_jobs_no_filter():
    """Test getting all LLM jobs without filters."""
    print("\n" + "="*60)
    print("TESTING GET LLM JOBS (NO FILTER)")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating multiple LLM jobs...")
        job1 = LLMJobCreate(
            job_type="image_tag",
            payload={"memory_id": "mem-1"},
            user_id=123456,
        )
        job2 = LLMJobCreate(
            job_type="intent_classify",
            payload={"message": "Hello"},
            user_id=123456,
        )
        job3 = LLMJobCreate(
            job_type="followup",
            payload={"context": "Previous chat"},
            user_id=999999,
        )

        await create_llm_job(job1, db)
        await create_llm_job(job2, db)
        await create_llm_job(job3, db)
        print("   ✓ Created 3 jobs")

        print("\n2. Fetching all jobs...")
        results = await get_llm_jobs(db=db)

        assert len(results) == 3, "Should return all 3 jobs"
        print(f"   ✓ Retrieved {len(results)} jobs")

        # Verify jobs are ordered by created_at DESC (newest first)
        assert results[0].created_at >= results[1].created_at, "Jobs should be ordered by created_at DESC"
        assert results[1].created_at >= results[2].created_at, "Jobs should be ordered by created_at DESC"
        print("   ✓ Jobs ordered by created_at DESC")

        print("\n" + "-"*60)
        print("✓ GET LLM JOBS (NO FILTER) TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_llm_jobs_filter_by_status():
    """Test filtering jobs by status."""
    print("\n" + "="*60)
    print("TESTING GET LLM JOBS FILTER BY STATUS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating jobs with different statuses...")
        job1 = await create_llm_job(
            LLMJobCreate(job_type="image_tag", payload={"memory_id": "mem-1"}, user_id=123456),
            db
        )
        job2 = await create_llm_job(
            LLMJobCreate(job_type="intent_classify", payload={"message": "Hi"}, user_id=123456),
            db
        )
        job3 = await create_llm_job(
            LLMJobCreate(job_type="followup", payload={"context": "Chat"}, user_id=999999),
            db
        )

        # Update job1 to completed
        await update_llm_job(job1.id, LLMJobUpdate(status="completed"), db)
        # Update job2 to failed
        await update_llm_job(job2.id, LLMJobUpdate(status="failed"), db)
        # job3 remains queued

        print("   ✓ Created 3 jobs (1 completed, 1 failed, 1 queued)")

        print("\n2. Filtering by status='queued'...")
        results = await get_llm_jobs(status="queued", db=db)
        assert len(results) == 1, "Should return 1 queued job"
        assert results[0].status == "queued", "Job should be queued"
        print(f"   ✓ Retrieved {len(results)} queued job")

        print("\n3. Filtering by status='completed'...")
        results = await get_llm_jobs(status="completed", db=db)
        assert len(results) == 1, "Should return 1 completed job"
        assert results[0].status == "completed", "Job should be completed"
        print(f"   ✓ Retrieved {len(results)} completed job")

        print("\n4. Filtering by status='failed'...")
        results = await get_llm_jobs(status="failed", db=db)
        assert len(results) == 1, "Should return 1 failed job"
        assert results[0].status == "failed", "Job should be failed"
        print(f"   ✓ Retrieved {len(results)} failed job")

        print("\n" + "-"*60)
        print("✓ GET LLM JOBS FILTER BY STATUS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_llm_jobs_filter_by_job_type():
    """Test filtering jobs by job_type."""
    print("\n" + "="*60)
    print("TESTING GET LLM JOBS FILTER BY JOB TYPE")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating jobs with different types...")
        await create_llm_job(
            LLMJobCreate(job_type="image_tag", payload={"memory_id": "mem-1"}, user_id=123456),
            db
        )
        await create_llm_job(
            LLMJobCreate(job_type="image_tag", payload={"memory_id": "mem-2"}, user_id=123456),
            db
        )
        await create_llm_job(
            LLMJobCreate(job_type="intent_classify", payload={"message": "Hi"}, user_id=999999),
            db
        )
        print("   ✓ Created 3 jobs (2 image_tag, 1 intent_classify)")

        print("\n2. Filtering by job_type='image_tag'...")
        results = await get_llm_jobs(job_type="image_tag", db=db)
        assert len(results) == 2, "Should return 2 image_tag jobs"
        for job in results:
            assert job.job_type == "image_tag", "All jobs should be image_tag"
        print(f"   ✓ Retrieved {len(results)} image_tag jobs")

        print("\n3. Filtering by job_type='intent_classify'...")
        results = await get_llm_jobs(job_type="intent_classify", db=db)
        assert len(results) == 1, "Should return 1 intent_classify job"
        assert results[0].job_type == "intent_classify", "Job should be intent_classify"
        print(f"   ✓ Retrieved {len(results)} intent_classify job")

        print("\n" + "-"*60)
        print("✓ GET LLM JOBS FILTER BY JOB TYPE TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_llm_jobs_filter_by_user_id():
    """Test filtering jobs by user_id."""
    print("\n" + "="*60)
    print("TESTING GET LLM JOBS FILTER BY USER ID")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating jobs for different users...")
        await create_llm_job(
            LLMJobCreate(job_type="image_tag", payload={"memory_id": "mem-1"}, user_id=123456),
            db
        )
        await create_llm_job(
            LLMJobCreate(job_type="intent_classify", payload={"message": "Hi"}, user_id=123456),
            db
        )
        await create_llm_job(
            LLMJobCreate(job_type="followup", payload={"context": "Chat"}, user_id=999999),
            db
        )
        await create_llm_job(
            LLMJobCreate(job_type="task_match", payload={"task": "Buy milk"}, user_id=None),
            db
        )
        print("   ✓ Created 4 jobs (2 for user 123456, 1 for user 999999, 1 system job)")

        print("\n2. Filtering by user_id=123456...")
        results = await get_llm_jobs(user_id=123456, db=db)
        assert len(results) == 2, "Should return 2 jobs for user 123456"
        for job in results:
            assert job.user_id == 123456, "All jobs should belong to user 123456"
        print(f"   ✓ Retrieved {len(results)} jobs for user 123456")

        print("\n3. Filtering by user_id=999999...")
        results = await get_llm_jobs(user_id=999999, db=db)
        assert len(results) == 1, "Should return 1 job for user 999999"
        assert results[0].user_id == 999999, "Job should belong to user 999999"
        print(f"   ✓ Retrieved {len(results)} job for user 999999")

        print("\n" + "-"*60)
        print("✓ GET LLM JOBS FILTER BY USER ID TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_llm_jobs_combined_filters():
    """Test combining multiple filters."""
    print("\n" + "="*60)
    print("TESTING GET LLM JOBS COMBINED FILTERS")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating various jobs...")
        job1 = await create_llm_job(
            LLMJobCreate(job_type="image_tag", payload={"memory_id": "mem-1"}, user_id=123456),
            db
        )
        job2 = await create_llm_job(
            LLMJobCreate(job_type="image_tag", payload={"memory_id": "mem-2"}, user_id=123456),
            db
        )
        job3 = await create_llm_job(
            LLMJobCreate(job_type="intent_classify", payload={"message": "Hi"}, user_id=123456),
            db
        )
        job4 = await create_llm_job(
            LLMJobCreate(job_type="image_tag", payload={"memory_id": "mem-3"}, user_id=999999),
            db
        )

        # Update job1 to completed
        await update_llm_job(job1.id, LLMJobUpdate(status="completed"), db)
        # job2, job3, job4 remain queued

        print("   ✓ Created 4 jobs with various types, statuses, and users")

        print("\n2. Filtering by user_id=123456 AND job_type='image_tag' AND status='queued'...")
        results = await get_llm_jobs(
            user_id=123456,
            job_type="image_tag",
            status="queued",
            db=db
        )
        assert len(results) == 1, "Should return 1 job matching all filters"
        assert results[0].user_id == 123456, "Job should belong to user 123456"
        assert results[0].job_type == "image_tag", "Job should be image_tag"
        assert results[0].status == "queued", "Job should be queued"
        print(f"   ✓ Retrieved {len(results)} job matching all filters")

        print("\n" + "-"*60)
        print("✓ GET LLM JOBS COMBINED FILTERS TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_get_llm_jobs_limit_offset():
    """Test limit and offset parameters."""
    print("\n" + "="*60)
    print("TESTING GET LLM JOBS LIMIT AND OFFSET")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating 5 jobs...")
        for i in range(5):
            await create_llm_job(
                LLMJobCreate(
                    job_type="intent_classify",
                    payload={"message": f"Message {i}"},
                    user_id=123456
                ),
                db
            )
        print("   ✓ Created 5 jobs")

        print("\n2. Testing limit=2...")
        results = await get_llm_jobs(limit=2, db=db)
        assert len(results) == 2, "Should return 2 jobs"
        print(f"   ✓ Retrieved {len(results)} jobs with limit=2")

        print("\n3. Testing limit=2, offset=2...")
        results = await get_llm_jobs(limit=2, offset=2, db=db)
        assert len(results) == 2, "Should return 2 jobs"
        print(f"   ✓ Retrieved {len(results)} jobs with offset=2")

        print("\n4. Testing limit=2, offset=4...")
        results = await get_llm_jobs(limit=2, offset=4, db=db)
        assert len(results) == 1, "Should return 1 job (5 total - 4 offset)"
        print(f"   ✓ Retrieved {len(results)} job with offset=4")

        print("\n" + "-"*60)
        print("✓ GET LLM JOBS LIMIT AND OFFSET TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def test_llm_job_payload_serialization():
    """Test that complex payloads are properly serialized and deserialized."""
    print("\n" + "="*60)
    print("TESTING LLM JOB PAYLOAD SERIALIZATION")
    print("="*60)

    db, db_path = await setup_test_db()

    try:
        print("\n1. Creating job with complex payload...")
        complex_payload = {
            "memory_id": "mem-123",
            "nested": {
                "key1": "value1",
                "key2": [1, 2, 3],
            },
            "array": ["item1", "item2"],
            "number": 42,
            "boolean": True,
        }
        job_create = LLMJobCreate(
            job_type="email_extract",
            payload=complex_payload,
            user_id=123456,
        )
        created = await create_llm_job(job_create, db)
        print(f"   ✓ Job created with complex payload")

        print("\n2. Fetching job and verifying payload...")
        result = await get_llm_job(created.id, db)
        assert result.payload == complex_payload, "Payload should match exactly"
        print("   ✓ Payload deserialized correctly")

        print("\n3. Updating job with complex result...")
        complex_result = {
            "events": [
                {"time": "2024-01-15T10:00:00Z", "description": "Event 1"},
                {"time": "2024-01-16T15:00:00Z", "description": "Event 2"},
            ],
            "confidence": 0.87,
        }
        job_update = LLMJobUpdate(
            status="completed",
            result=complex_result,
        )
        updated = await update_llm_job(created.id, job_update, db)
        assert updated.result == complex_result, "Result should match exactly"
        print("   ✓ Complex result serialized and deserialized correctly")

        print("\n" + "-"*60)
        print("✓ LLM JOB PAYLOAD SERIALIZATION TEST PASSED")
        print("-"*60)

    finally:
        await cleanup_test_db(db, db_path)


async def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("LLM JOBS ROUTER TEST SUITE")
    print("="*60)

    tests = [
        test_create_llm_job_with_user,
        test_create_llm_job_without_user,
        test_get_llm_job,
        test_get_llm_job_404,
        test_update_llm_job_status,
        test_update_llm_job_result,
        test_update_llm_job_error,
        test_update_llm_job_404,
        test_update_llm_job_audit_log,
        test_get_llm_jobs_no_filter,
        test_get_llm_jobs_filter_by_status,
        test_get_llm_jobs_filter_by_job_type,
        test_get_llm_jobs_filter_by_user_id,
        test_get_llm_jobs_combined_filters,
        test_get_llm_jobs_limit_offset,
        test_llm_job_payload_serialization,
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
