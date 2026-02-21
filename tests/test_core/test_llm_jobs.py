"""Tests for the LLM jobs endpoints."""

import json
import pytest


async def test_create_llm_job_with_user(test_app, test_user):
    """POST /llm_jobs with user_id returns 201 with correct fields."""
    resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "image_tag",
            "payload": {
                "memory_id": "mem-123",
                "image_url": "https://example.com/img.jpg",
            },
            "user_id": test_user,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] is not None
    assert data["job_type"] == "image_tag"
    assert data["payload"] == {
        "memory_id": "mem-123",
        "image_url": "https://example.com/img.jpg",
    }
    assert data["user_id"] == test_user
    assert data["status"] == "queued"
    assert data["result"] is None
    assert data["error_message"] is None
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


async def test_create_llm_job_without_user(test_app, test_user):
    """POST /llm_jobs with user_id=null creates a system job."""
    resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "intent_classify",
            "payload": {"message": "Hello, how are you?"},
            "user_id": None,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] is not None
    assert data["job_type"] == "intent_classify"
    assert data["user_id"] is None
    assert data["status"] == "queued"


async def test_get_llm_job(test_app, test_user):
    """Create a job then GET by ID; all fields match."""
    create_resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "task_match",
            "payload": {"task_description": "Buy groceries"},
            "user_id": test_user,
        },
    )
    job_id = create_resp.json()["id"]

    get_resp = await test_app.get(f"/llm_jobs/{job_id}")
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert data["id"] == job_id
    assert data["job_type"] == "task_match"
    assert data["payload"] == {"task_description": "Buy groceries"}
    assert data["user_id"] == test_user
    assert data["status"] == "queued"


async def test_get_llm_job_404(test_app, test_user):
    """GET /llm_jobs/nonexistent returns 404."""
    resp = await test_app.get("/llm_jobs/nonexistent-id-99999")
    assert resp.status_code == 404


async def test_update_llm_job_status(test_app, test_user):
    """PATCH status from queued to processing then completed."""
    create_resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "followup",
            "payload": {"context": "Previous conversation"},
            "user_id": test_user,
        },
    )
    job_id = create_resp.json()["id"]
    original_updated_at = create_resp.json()["updated_at"]

    patch_resp = await test_app.patch(
        f"/llm_jobs/{job_id}",
        json={
            "status": "processing",
        },
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "processing"

    patch_resp2 = await test_app.patch(
        f"/llm_jobs/{job_id}",
        json={
            "status": "completed",
        },
    )
    assert patch_resp2.status_code == 200
    assert patch_resp2.json()["status"] == "completed"
    assert patch_resp2.json()["updated_at"] >= original_updated_at


async def test_update_llm_job_result(test_app, test_user):
    """PATCH with status=completed and a result dict."""
    create_resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "email_extract",
            "payload": {"email_body": "Meeting at 3pm tomorrow"},
            "user_id": test_user,
        },
    )
    job_id = create_resp.json()["id"]

    result_data = {
        "event_time": "2024-01-15T15:00:00Z",
        "description": "Meeting",
        "confidence": 0.95,
    }
    patch_resp = await test_app.patch(
        f"/llm_jobs/{job_id}",
        json={
            "status": "completed",
            "result": result_data,
        },
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["status"] == "completed"
    assert data["result"] == result_data
    assert data["error_message"] is None


async def test_update_llm_job_error(test_app, test_user):
    """PATCH with status=failed and error_message."""
    create_resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "image_tag",
            "payload": {"memory_id": "mem-456"},
            "user_id": test_user,
        },
    )
    job_id = create_resp.json()["id"]

    patch_resp = await test_app.patch(
        f"/llm_jobs/{job_id}",
        json={
            "status": "failed",
            "error_message": "API rate limit exceeded",
        },
    )
    assert patch_resp.status_code == 200
    data = patch_resp.json()
    assert data["status"] == "failed"
    assert data["error_message"] == "API rate limit exceeded"
    assert data["result"] is None


async def test_update_llm_job_404(test_app, test_user):
    """PATCH /llm_jobs/nonexistent returns 404."""
    resp = await test_app.patch(
        "/llm_jobs/nonexistent-id-99999",
        json={
            "status": "completed",
        },
    )
    assert resp.status_code == 404


async def test_update_llm_job_audit_log(test_app, test_user, test_db):
    """Updating a job creates an audit log entry with action=updated."""
    create_resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "intent_classify",
            "payload": {"message": "Test message"},
            "user_id": test_user,
        },
    )
    job_id = create_resp.json()["id"]

    await test_app.patch(
        f"/llm_jobs/{job_id}",
        json={
            "status": "completed",
        },
    )

    cursor = await test_db.execute(
        "SELECT action, actor FROM audit_log WHERE entity_id = ? AND action = 'updated'",
        (job_id,),
    )
    audit_row = await cursor.fetchone()
    assert audit_row is not None
    assert audit_row[0] == "updated"
    assert audit_row[1] == "system:llm_worker"


async def test_list_llm_jobs_no_filter(test_app, test_user):
    """Create 3 jobs then GET /llm_jobs returns all of them."""
    for payload in [
        {
            "job_type": "image_tag",
            "payload": {"memory_id": "mem-1"},
            "user_id": test_user,
        },
        {
            "job_type": "intent_classify",
            "payload": {"message": "Hello"},
            "user_id": test_user,
        },
        {
            "job_type": "followup",
            "payload": {"context": "Previous chat"},
            "user_id": test_user,
        },
    ]:
        await test_app.post("/llm_jobs", json=payload)

    resp = await test_app.get("/llm_jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3


async def test_list_llm_jobs_filter_status(test_app, test_user):
    """Create jobs with different statuses and filter by status."""
    ids = []
    for jt in ["image_tag", "intent_classify", "followup"]:
        r = await test_app.post(
            "/llm_jobs",
            json={
                "job_type": jt,
                "payload": {"key": jt},
                "user_id": test_user,
            },
        )
        ids.append(r.json()["id"])

    await test_app.patch(f"/llm_jobs/{ids[0]}", json={"status": "completed"})
    await test_app.patch(f"/llm_jobs/{ids[1]}", json={"status": "failed"})

    resp = await test_app.get("/llm_jobs", params={"status": "queued"})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "queued"

    resp = await test_app.get("/llm_jobs", params={"status": "completed"})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "completed"

    resp = await test_app.get("/llm_jobs", params={"status": "failed"})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["status"] == "failed"


async def test_list_llm_jobs_filter_job_type(test_app, test_user):
    """Create jobs with different types and filter by job_type."""
    await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "image_tag",
            "payload": {"m": "1"},
            "user_id": test_user,
        },
    )
    await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "image_tag",
            "payload": {"m": "2"},
            "user_id": test_user,
        },
    )
    await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "intent_classify",
            "payload": {"m": "3"},
            "user_id": test_user,
        },
    )

    resp = await test_app.get("/llm_jobs", params={"job_type": "image_tag"})
    data = resp.json()
    assert len(data) == 2
    for job in data:
        assert job["job_type"] == "image_tag"

    resp = await test_app.get("/llm_jobs", params={"job_type": "intent_classify"})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["job_type"] == "intent_classify"


async def test_list_llm_jobs_filter_user_id(test_app, test_user, test_db):
    """Create jobs for different users and filter by user_id."""
    other_user_id = 99999
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (other_user_id, "Other User", 1),
    )
    await test_db.commit()

    await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "image_tag",
            "payload": {"m": "1"},
            "user_id": test_user,
        },
    )
    await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "intent_classify",
            "payload": {"m": "2"},
            "user_id": test_user,
        },
    )
    await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "followup",
            "payload": {"m": "3"},
            "user_id": other_user_id,
        },
    )

    resp = await test_app.get("/llm_jobs", params={"user_id": test_user})
    data = resp.json()
    assert len(data) == 2
    for job in data:
        assert job["user_id"] == test_user

    resp = await test_app.get("/llm_jobs", params={"user_id": other_user_id})
    data = resp.json()
    assert len(data) == 1
    assert data[0]["user_id"] == other_user_id


async def test_list_llm_jobs_combined_filters(test_app, test_user, test_db):
    """Filter by user_id + job_type + status combined."""
    other_user_id = 99999
    await test_db.execute(
        "INSERT INTO users (telegram_user_id, display_name, is_allowed) VALUES (?, ?, ?)",
        (other_user_id, "Other User", 1),
    )
    await test_db.commit()

    r1 = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "image_tag",
            "payload": {"m": "1"},
            "user_id": test_user,
        },
    )
    await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "image_tag",
            "payload": {"m": "2"},
            "user_id": test_user,
        },
    )
    await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "intent_classify",
            "payload": {"m": "3"},
            "user_id": test_user,
        },
    )
    await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "image_tag",
            "payload": {"m": "4"},
            "user_id": other_user_id,
        },
    )

    # Complete the first job so only the second image_tag for test_user stays queued
    await test_app.patch(f"/llm_jobs/{r1.json()['id']}", json={"status": "completed"})

    resp = await test_app.get(
        "/llm_jobs",
        params={
            "user_id": test_user,
            "job_type": "image_tag",
            "status": "queued",
        },
    )
    data = resp.json()
    assert len(data) == 1
    assert data[0]["user_id"] == test_user
    assert data[0]["job_type"] == "image_tag"
    assert data[0]["status"] == "queued"


async def test_list_llm_jobs_limit_offset(test_app, test_user):
    """Test pagination with limit and offset."""
    for i in range(5):
        await test_app.post(
            "/llm_jobs",
            json={
                "job_type": "intent_classify",
                "payload": {"message": f"Message {i}"},
                "user_id": test_user,
            },
        )

    resp = await test_app.get("/llm_jobs", params={"limit": 2})
    assert len(resp.json()) == 2

    resp = await test_app.get("/llm_jobs", params={"limit": 2, "offset": 2})
    assert len(resp.json()) == 2

    resp = await test_app.get("/llm_jobs", params={"limit": 2, "offset": 4})
    assert len(resp.json()) == 1


async def test_llm_job_payload_serialization(test_app, test_user):
    """Complex nested payload and result round-trip correctly."""
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
    create_resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "email_extract",
            "payload": complex_payload,
            "user_id": test_user,
        },
    )
    assert create_resp.status_code == 201
    job_id = create_resp.json()["id"]

    get_resp = await test_app.get(f"/llm_jobs/{job_id}")
    assert get_resp.json()["payload"] == complex_payload

    complex_result = {
        "events": [
            {"time": "2024-01-15T10:00:00Z", "description": "Event 1"},
            {"time": "2024-01-16T15:00:00Z", "description": "Event 2"},
        ],
        "confidence": 0.87,
    }
    patch_resp = await test_app.patch(
        f"/llm_jobs/{job_id}",
        json={
            "status": "completed",
            "result": complex_result,
        },
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["result"] == complex_result
    assert patch_resp.json()["payload"] == complex_payload


async def test_create_llm_job_publishes_to_redis(test_app, test_user, mock_redis):
    """POST /llm_jobs publishes job to Redis stream llm:image_tag."""
    resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "image_tag",
            "payload": {"memory_id": "m-1", "image_path": "/data/images/test.jpg"},
            "user_id": test_user,
        },
    )
    assert resp.status_code == 201
    data = resp.json()

    # Verify Redis received the message on stream llm:image_tag
    result = await mock_redis.xread({"llm:image_tag": "0-0"}, count=1)
    assert len(result) == 1
    stream_name, messages = result[0]
    msg_id, fields = messages[0]
    msg_data = json.loads(fields[b"data"])
    assert msg_data["job_id"] == data["id"]
    assert msg_data["job_type"] == "image_tag"
    assert msg_data["user_id"] == test_user
    assert msg_data["payload"] == {
        "memory_id": "m-1",
        "image_path": "/data/images/test.jpg",
    }


async def test_create_llm_job_publishes_intent_stream(test_app, test_user, mock_redis):
    """POST /llm_jobs with job_type=intent_classify publishes to Redis stream llm:intent."""
    resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "intent_classify",
            "payload": {"message": "Hello, how are you?"},
            "user_id": test_user,
        },
    )
    assert resp.status_code == 201
    data = resp.json()

    # Verify Redis received the message on stream llm:intent
    result = await mock_redis.xread({"llm:intent": "0-0"}, count=1)
    assert len(result) == 1
    stream_name, messages = result[0]
    msg_id, fields = messages[0]
    msg_data = json.loads(fields[b"data"])
    assert msg_data["job_id"] == data["id"]
    assert msg_data["job_type"] == "intent_classify"
    assert msg_data["user_id"] == test_user
    assert msg_data["payload"] == {"message": "Hello, how are you?"}


async def test_create_llm_job_no_redis_no_crash(test_app, test_user):
    """POST /llm_jobs should return 201 even when Redis is unavailable."""
    from core_svc.main import app

    # Remove Redis from app state to simulate unavailability
    app.state.redis = None

    resp = await test_app.post(
        "/llm_jobs",
        json={
            "job_type": "image_tag",
            "payload": {"memory_id": "m-1"},
            "user_id": test_user,
        },
    )
    # Should still return 201 - job is saved to DB even without Redis
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] is not None
    assert data["status"] == "queued"
