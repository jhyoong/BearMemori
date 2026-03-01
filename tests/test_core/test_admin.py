"""Tests for the admin endpoints."""

import json
from datetime import datetime, timezone

from core_svc.routers.admin import LLM_HEALTH_KEY
from shared_lib.redis_streams import (
    GROUP_LLM_WORKER,
    STREAM_LLM_EMAIL_EXTRACT,
    STREAM_LLM_FOLLOWUP,
    STREAM_LLM_IMAGE_TAG,
    STREAM_LLM_INTENT,
    STREAM_LLM_TASK_MATCH,
)



async def test_queue_stats_empty_database(test_app, test_user):
    """GET /admin/queue-stats returns zeros when no jobs exist."""
    resp = await test_app.get("/admin/queue-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_pending"] == 0
    assert data["by_status"]["queued"] == 0
    assert data["by_status"]["processing"] == 0
    assert data["by_status"]["confirmed"] == 0
    assert data["by_status"]["failed"] == 0
    assert data["by_status"]["cancelled"] == 0
    assert data["by_type"] == {}
    assert data["oldest_queued_age_seconds"] is None


async def test_queue_stats_with_jobs(test_app, test_user, test_db):
    """GET /admin/queue-stats returns correct counts for multiple jobs."""
    # Create jobs with different statuses and types
    # Queued jobs
    for i in range(3):
        await test_db.execute(
            """
            INSERT INTO llm_jobs (id, job_type, payload, user_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"job-queued-{i}",
                "image_tag",
                '{"memory_id": "mem-1"}',
                test_user,
                "queued",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ),
        )
    # Processing jobs
    for i in range(2):
        await test_db.execute(
            """
            INSERT INTO llm_jobs (id, job_type, payload, user_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"job-processing-{i}",
                "intent_classify",
                '{"message": "test"}',
                test_user,
                "processing",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ),
        )
    # Confirmed jobs
    await test_db.execute(
        """
        INSERT INTO llm_jobs (id, job_type, payload, user_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "job-confirmed-1",
            "followup",
            '{"context": "test"}',
            test_user,
            "confirmed",
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        ),
    )
    # Failed jobs
    await test_db.execute(
        """
        INSERT INTO llm_jobs (id, job_type, payload, user_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "job-failed-1",
            "task_match",
            '{"task_id": "task-1"}',
            test_user,
            "failed",
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        ),
    )
    # Cancelled jobs
    await test_db.execute(
        """
        INSERT INTO llm_jobs (id, job_type, payload, user_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "job-cancelled-1",
            "email_extract",
            '{"email": "test@example.com"}',
            test_user,
            "cancelled",
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        ),
    )
    await test_db.commit()

    resp = await test_app.get("/admin/queue-stats")
    assert resp.status_code == 200
    data = resp.json()

    # Verify counts - total_pending counts queued jobs
    assert data["total_pending"] == 3  # 3 queued jobs

    # by_status should have all statuses
    assert data["by_status"]["queued"] == 3
    assert data["by_status"]["processing"] == 2
    assert data["by_status"]["confirmed"] == 1
    assert data["by_status"]["failed"] == 1
    assert data["by_status"]["cancelled"] == 1

    # by_type should have counts per job type
    assert data["by_type"]["image_tag"] == 3
    assert data["by_type"]["intent_classify"] == 2
    assert data["by_type"]["followup"] == 1
    assert data["by_type"]["task_match"] == 1
    assert data["by_type"]["email_extract"] == 1

    # oldest_queued_age_seconds should be a positive number
    assert data["oldest_queued_age_seconds"] is not None
    assert data["oldest_queued_age_seconds"] >= 0


async def test_queue_stats_with_mixed_types(test_app, test_user, test_db):
    """GET /admin/queue-stats correctly counts multiple job types."""
    # Create jobs of different types
    job_types = ["image_tag", "intent_classify", "task_match", "followup", "email_extract"]
    for job_type in job_types:
        await test_db.execute(
            """
            INSERT INTO llm_jobs (id, job_type, payload, user_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"job-{job_type}",
                job_type,
                '{"test": true}',
                test_user,
                "queued",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ),
        )
    await test_db.commit()

    resp = await test_app.get("/admin/queue-stats")
    assert resp.status_code == 200
    data = resp.json()

    # All job types should be in by_type
    for job_type in job_types:
        assert data["by_type"][job_type] == 1


async def test_queue_stats_oldest_job_age(test_app, test_user, test_db):
    """GET /admin/queue-stats returns correct age for oldest queued job."""
    # Create an old queued job (created earlier in the day)
    old_time = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    await test_db.execute(
        """
        INSERT INTO llm_jobs (id, job_type, payload, user_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "job-old",
            "image_tag",
            '{"memory_id": "mem-old"}',
            test_user,
            "queued",
            old_time.isoformat().replace("+00:00", "Z"),
            old_time.isoformat().replace("+00:00", "Z"),
        ),
    )
    # Create a recent queued job
    recent_time = datetime.now(timezone.utc)
    await test_db.execute(
        """
        INSERT INTO llm_jobs (id, job_type, payload, user_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "job-recent",
            "image_tag",
            '{"memory_id": "mem-recent"}',
            test_user,
            "queued",
            recent_time.isoformat().replace("+00:00", "Z"),
            recent_time.isoformat().replace("+00:00", "Z"),
        ),
    )
    await test_db.commit()

    resp = await test_app.get("/admin/queue-stats")
    assert resp.status_code == 200
    data = resp.json()

    # oldest_queued_age_seconds should be the age of the oldest queued job
    # The oldest job was created at the start of the day, so it should be > 0
    assert data["oldest_queued_age_seconds"] is not None
    # Should be positive (at least a few seconds since we created it)
    assert data["oldest_queued_age_seconds"] >= 0


async def test_queue_stats_pending_only(test_app, test_user, test_db):
    """Verify that only 'queued' status is counted as pending."""
    # Create queued jobs (pending)
    for i in range(3):
        await test_db.execute(
            """
            INSERT INTO llm_jobs (id, job_type, payload, user_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"job-queued-{i}",
                "image_tag",
                '{"memory_id": "mem-1"}',
                test_user,
                "queued",
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ),
        )
    # Create non-pending jobs (processing, confirmed, failed, cancelled)
    for status in ["processing", "confirmed", "failed", "cancelled"]:
        await test_db.execute(
            """
            INSERT INTO llm_jobs (id, job_type, payload, user_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"job-{status}",
                "intent_classify",
                '{"message": "test"}',
                test_user,
                status,
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            ),
        )
    await test_db.commit()

    resp = await test_app.get("/admin/queue-stats")
    assert resp.status_code == 200
    data = resp.json()

    # total_pending should only count 'queued' jobs
    assert data["total_pending"] == 3

    # by_status should show all statuses
    assert data["by_status"]["queued"] == 3
    assert data["by_status"]["processing"] == 1
    assert data["by_status"]["confirmed"] == 1
    assert data["by_status"]["failed"] == 1
    assert data["by_status"]["cancelled"] == 1


async def test_health_healthy(test_app, test_user):
    """GET /admin/health returns healthy status when DB and Redis work."""
    resp = await test_app.get("/admin/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"


async def test_health_database_failure(test_app, test_user, test_db, monkeypatch):
    """GET /admin/health returns unhealthy when database query fails."""
    # Simulate a database failure by patching the execute method
    original_execute = test_db.execute

    async def failing_execute(*args, **kwargs):
        raise Exception("database connection lost")

    # Temporarily replace the execute method
    import types
    test_db.execute = types.MethodType(failing_execute, test_db)

    try:
        resp = await test_app.get("/admin/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unhealthy"
        assert "error" in data
        assert "database" in data["error"]
    finally:
        # Restore original execute method
        test_db.execute = original_execute


async def test_health_redis_failure(test_app, test_user, mock_redis):
    """GET /admin/health returns unhealthy when Redis ping fails."""
    # Simulate a Redis failure by patching the ping method
    original_ping = mock_redis.ping

    async def failing_ping(*args, **kwargs):
        raise Exception("redis connection lost")

    mock_redis.ping = failing_ping

    try:
        resp = await test_app.get("/admin/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unhealthy"
        assert "error" in data
        assert "redis" in data["error"]
    finally:
        # Restore original ping method
        mock_redis.ping = original_ping


# ── stream-health tests ──────────────────────────────────────────────


EXPECTED_STREAMS = [
    STREAM_LLM_INTENT,
    STREAM_LLM_IMAGE_TAG,
    STREAM_LLM_FOLLOWUP,
    STREAM_LLM_TASK_MATCH,
    STREAM_LLM_EMAIL_EXTRACT,
]


async def test_stream_health_empty(test_app, test_user, mock_redis):
    """GET /admin/stream-health returns expected structure when no streams exist."""
    resp = await test_app.get("/admin/stream-health")
    assert resp.status_code == 200
    data = resp.json()

    # Check top-level keys
    assert "streams" in data
    assert "consumer_group" in data
    assert "consumers_active" in data

    # Check consumer group name
    assert data["consumer_group"] == GROUP_LLM_WORKER

    # All streams should be present with length=0, pending=0
    for stream_name in EXPECTED_STREAMS:
        assert stream_name in data["streams"]
        assert data["streams"][stream_name]["length"] == 0
        assert data["streams"][stream_name]["pending"] == 0

    # No consumers when nothing is set up
    assert data["consumers_active"] == 0


async def test_stream_health_with_messages(test_app, test_user, mock_redis):
    """GET /admin/stream-health reports stream lengths after XADD."""
    # Add messages to a couple of streams
    await mock_redis.xadd(STREAM_LLM_INTENT, {"data": "msg1"})
    await mock_redis.xadd(STREAM_LLM_INTENT, {"data": "msg2"})
    await mock_redis.xadd(STREAM_LLM_IMAGE_TAG, {"data": "msg3"})

    resp = await test_app.get("/admin/stream-health")
    assert resp.status_code == 200
    data = resp.json()

    assert data["streams"][STREAM_LLM_INTENT]["length"] == 2
    assert data["streams"][STREAM_LLM_IMAGE_TAG]["length"] == 1
    # Streams without messages should still be 0
    assert data["streams"][STREAM_LLM_FOLLOWUP]["length"] == 0


async def test_stream_health_graceful_degradation(test_app, test_user, mock_redis):
    """GET /admin/stream-health returns defaults when Redis commands fail."""
    # Patch xlen to always fail, simulating an unsupported or broken command
    original_xlen = mock_redis.xlen

    async def failing_xlen(*args, **kwargs):
        raise Exception("simulated redis failure")

    mock_redis.xlen = failing_xlen

    try:
        resp = await test_app.get("/admin/stream-health")
        assert resp.status_code == 200
        data = resp.json()

        # Should still return the expected structure with zero defaults
        assert data["consumer_group"] == GROUP_LLM_WORKER
        assert data["consumers_active"] == 0
        for stream_name in EXPECTED_STREAMS:
            assert data["streams"][stream_name]["length"] == 0
            assert data["streams"][stream_name]["pending"] == 0
    finally:
        mock_redis.xlen = original_xlen


# ── llm-health tests ────────────────────────────────────────────────


async def test_llm_health_no_data(test_app, test_user, mock_redis):
    """GET /admin/llm-health returns 'unknown' when no health key exists."""
    resp = await test_app.get("/admin/llm-health")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "unknown"
    assert data["last_check"] is None
    assert data["last_success"] is None
    assert data["last_failure"] is None
    assert data["consecutive_failures"] == 0


async def test_llm_health_with_data(test_app, test_user, mock_redis):
    """GET /admin/llm-health returns stored health data when key exists."""
    health_data = {
        "status": "healthy",
        "last_check": "2026-03-01T10:30:00Z",
        "last_success": "2026-03-01T10:30:00Z",
        "last_failure": "2026-03-01T09:15:00Z",
        "consecutive_failures": 0,
    }
    await mock_redis.set(LLM_HEALTH_KEY, json.dumps(health_data))

    resp = await test_app.get("/admin/llm-health")
    assert resp.status_code == 200
    data = resp.json()

    assert data["status"] == "healthy"
    assert data["last_check"] == "2026-03-01T10:30:00Z"
    assert data["last_success"] == "2026-03-01T10:30:00Z"
    assert data["last_failure"] == "2026-03-01T09:15:00Z"
    assert data["consecutive_failures"] == 0


async def test_llm_health_redis_error(test_app, test_user, mock_redis):
    """GET /admin/llm-health returns 'unknown' gracefully when Redis fails."""
    original_get = mock_redis.get

    async def failing_get(*args, **kwargs):
        raise Exception("redis connection lost")

    mock_redis.get = failing_get

    try:
        resp = await test_app.get("/admin/llm-health")
        assert resp.status_code == 200
        data = resp.json()

        assert data["status"] == "unknown"
        assert data["last_check"] is None
        assert data["last_success"] is None
        assert data["last_failure"] is None
        assert data["consecutive_failures"] == 0
    finally:
        mock_redis.get = original_get