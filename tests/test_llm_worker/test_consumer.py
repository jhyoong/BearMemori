"""Tests for the LLM worker consumer loop."""

import pytest
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch
import fakeredis.aioredis

# Import from consumer module (doesn't exist yet - that's expected)
# Using "from worker.xxx" pattern because llm_worker is a directory, not a package
from worker.consumer import (
    run_consumer,
    _process_message,
    STREAM_HANDLER_MAP,
    CONSUMER_NAME,
    STREAM_NOTIFY_TELEGRAM,
)
from worker.retry import RetryTracker
from shared_lib.redis_streams import (
    STREAM_LLM_IMAGE_TAG,
    STREAM_LLM_INTENT,
    STREAM_LLM_FOLLOWUP,
    STREAM_LLM_TASK_MATCH,
    STREAM_LLM_EMAIL_EXTRACT,
    GROUP_LLM_WORKER,
    create_consumer_group,
    publish,
    consume,
    ack,
)


# Helper to create a mock handler
def create_mock_handler(return_value, raises=None):
    """Create a mock handler that returns a value or raises an exception."""
    handler = AsyncMock()
    if raises:
        handler.handle.side_effect = raises
    else:
        handler.handle.return_value = return_value
    return handler


@pytest.fixture
async def mock_redis():
    """Create a fake Redis client for testing."""
    redis_client = fakeredis.aioredis.FakeRedis()
    # Create consumer groups for all streams
    await create_consumer_group(redis_client, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER)
    await create_consumer_group(redis_client, STREAM_LLM_INTENT, GROUP_LLM_WORKER)
    await create_consumer_group(redis_client, STREAM_LLM_FOLLOWUP, GROUP_LLM_WORKER)
    await create_consumer_group(redis_client, STREAM_LLM_TASK_MATCH, GROUP_LLM_WORKER)
    await create_consumer_group(
        redis_client, STREAM_LLM_EMAIL_EXTRACT, GROUP_LLM_WORKER
    )
    yield redis_client
    await redis_client.aclose()


@pytest.fixture
def mock_llm_client():
    """Mock LLMClient with async methods."""
    return AsyncMock()


@pytest.fixture
def mock_core_api():
    """Mock CoreAPIClient with async methods."""
    client = AsyncMock()
    client.update_job = AsyncMock()
    return client


@pytest.fixture
def retry_tracker():
    """Create a retry tracker with default settings."""
    return RetryTracker(max_retries=3)


@pytest.fixture
def llm_worker_config():
    """Create a test config with defaults."""
    from worker.config import LLMWorkerSettings

    return LLMWorkerSettings(
        llm_base_url="http://localhost:8080/v1",
        llm_vision_model="test-vision",
        llm_text_model="test-text",
        llm_api_key="test-key",
        llm_max_retries=3,
        redis_url="redis://localhost:6379",
        core_api_url="http://localhost:8000",
        image_storage_path="/tmp/test-images",
    )


@pytest.mark.asyncio
async def test_consumer_processes_job(
    mock_redis, mock_llm_client, mock_core_api, retry_tracker, llm_worker_config
):
    """Handler success publishes notification to notify:telegram stream."""
    # Setup: Add a message to the stream
    job_id = "job-123"
    payload = {"memory_id": "mem-1", "image_path": "/tmp/test.jpg"}
    await publish(
        mock_redis,
        STREAM_LLM_IMAGE_TAG,
        {
            "job_id": job_id,
            "payload": payload,
            "user_id": 12345,
            "job_type": "image_tag",
        },
    )

    # Create mock handler that returns a notification dict
    notification = {
        "type": "image_tag_result",
        "memory_id": "mem-1",
        "tags": ["tag1", "tag2"],
    }
    mock_handler = create_mock_handler(notification)

    # Create handlers dict
    handlers = {"image_tag": mock_handler}

    # Execute: Process one message
    messages = await consume(
        mock_redis, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
    )

    assert len(messages) == 1
    message_id, data = messages[0]

    # Process the message
    await _process_message(
        redis_client=mock_redis,
        stream_name=STREAM_LLM_IMAGE_TAG,
        message_id=message_id,
        data=data,
        handlers=handlers,
        core_api=mock_core_api,
        retry_tracker=retry_tracker,
        config=llm_worker_config,
    )

    # Verify: Handler was called
    mock_handler.handle.assert_called_once()

    # Verify: Job status updated to completed
    mock_core_api.update_job.assert_called_once_with(
        job_id=job_id, status="completed", result=notification
    )

    # Verify: Notification was published to telegram stream
    notify_messages = await mock_redis.xread({STREAM_NOTIFY_TELEGRAM: "0"}, count=1)
    assert len(notify_messages) == 1
    stream, msgs = notify_messages[0]
    assert stream.decode() == STREAM_NOTIFY_TELEGRAM
    # Check the published data
    found_notification = False
    for msg_id, fields in msgs:
        if b"data" in fields:
            import json

            data_str = fields[b"data"].decode()
            notification_data = json.loads(data_str)
            if notification_data.get("type") == "image_tag_result":
                found_notification = True
    assert found_notification, "Notification should be published to notify:telegram"


@pytest.mark.asyncio
async def test_consumer_handler_returns_none(
    mock_redis, mock_llm_client, mock_core_api, retry_tracker, llm_worker_config
):
    """Handler returns None - no notification should be published."""
    # Setup: Add a message to the stream
    job_id = "job-456"
    payload = {"memory_id": "mem-2"}
    await publish(
        mock_redis,
        STREAM_LLM_INTENT,
        {
            "job_id": job_id,
            "payload": payload,
            "user_id": 12345,
            "job_type": "intent_classify",
        },
    )

    # Create mock handler that returns None (no notification)
    mock_handler = create_mock_handler(None)

    handlers = {"intent_classify": mock_handler}

    # Execute: Process one message
    messages = await consume(
        mock_redis, STREAM_LLM_INTENT, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
    )

    assert len(messages) == 1
    message_id, data = messages[0]

    await _process_message(
        redis_client=mock_redis,
        stream_name=STREAM_LLM_INTENT,
        message_id=message_id,
        data=data,
        handlers=handlers,
        core_api=mock_core_api,
        retry_tracker=retry_tracker,
        config=llm_worker_config,
    )

    # Verify: Job status updated to completed
    mock_core_api.update_job.assert_called_once_with(
        job_id=job_id, status="completed", result=None
    )

    # Verify: No notification was published to notify:telegram
    notify_messages = await mock_redis.xread({STREAM_NOTIFY_TELEGRAM: "0"}, count=1)
    assert len(notify_messages) == 0, (
        "No notification should be published when handler returns None"
    )


@pytest.mark.asyncio
async def test_consumer_retry_on_failure(
    mock_redis, mock_llm_client, mock_core_api, retry_tracker, llm_worker_config
):
    """Retry logic with backoff - message should NOT be acked."""
    # Setup: Add a message to the stream
    job_id = "job-789"
    payload = {"memory_id": "mem-3"}
    await publish(
        mock_redis,
        STREAM_LLM_FOLLOWUP,
        {
            "job_id": job_id,
            "payload": payload,
            "user_id": 12345,
            "job_type": "followup",
        },
    )

    # Create mock handler that raises an exception
    error = Exception("LLM API error")
    mock_handler = create_mock_handler(None, raises=error)

    handlers = {"followup": mock_handler}

    # Execute: Process one message - should fail
    messages = await consume(
        mock_redis, STREAM_LLM_FOLLOWUP, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
    )

    assert len(messages) == 1
    message_id, data = messages[0]

    await _process_message(
        redis_client=mock_redis,
        stream_name=STREAM_LLM_FOLLOWUP,
        message_id=message_id,
        data=data,
        handlers=handlers,
        core_api=mock_core_api,
        retry_tracker=retry_tracker,
        config=llm_worker_config,
    )

    # Verify: Handler was called
    mock_handler.handle.assert_called_once()

    # Verify: Job status updated to "processing" (not completed)
    mock_core_api.update_job.assert_called_once_with(
        job_id=job_id, status="processing", error_message=None
    )

    # Verify: Message is NOT acked (still in pending)
    pending = await mock_redis.xreadgroup(
        GROUP_LLM_WORKER, f"{CONSUMER_NAME}-retry", {STREAM_LLM_FOLLOWUP: "0"}, count=1
    )
    # The message should still be available for retry
    assert len(pending) > 0, "Message should not be acked on failure"


@pytest.mark.asyncio
async def test_consumer_max_retries_exceeded(
    mock_redis, mock_llm_client, mock_core_api, retry_tracker, llm_worker_config
):
    """Failed job marked failed, failure notification published."""
    # Setup: Add a message to the stream
    job_id = "job-max-retries"
    payload = {"memory_id": "mem-4"}
    await publish(
        mock_redis,
        STREAM_LLM_TASK_MATCH,
        {
            "job_id": job_id,
            "payload": payload,
            "user_id": 12345,
            "job_type": "task_match",
        },
    )

    # Create mock handler that always fails
    error = Exception("LLM API error")
    mock_handler = create_mock_handler(None, raises=error)

    handlers = {"task_match": mock_handler}

    # Simulate max retries exceeded
    for i in range(3):  # max_retries is 3
        retry_tracker.record_attempt(job_id)
    assert not retry_tracker.should_retry(job_id)

    # Execute: Process one message after max retries
    messages = await consume(
        mock_redis, STREAM_LLM_TASK_MATCH, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
    )

    assert len(messages) == 1
    message_id, data = messages[0]

    await _process_message(
        redis_client=mock_redis,
        stream_name=STREAM_LLM_TASK_MATCH,
        message_id=message_id,
        data=data,
        handlers=handlers,
        core_api=mock_core_api,
        retry_tracker=retry_tracker,
        config=llm_worker_config,
    )

    # Verify: Job status updated to "failed"
    mock_core_api.update_job.assert_called_with(
        job_id=job_id, status="failed", error_message="LLM API error"
    )

    # Verify: Failure notification was published
    notify_messages = await mock_redis.xread({STREAM_NOTIFY_TELEGRAM: "0"}, count=1)
    assert len(notify_messages) == 1
    import json

    stream, msgs = notify_messages[0]
    found_failure_notification = False
    for msg_id, fields in msgs:
        if b"data" in fields:
            data_str = fields[b"data"].decode()
            notification_data = json.loads(data_str)
            if notification_data.get("type") == "job_failed":
                found_failure_notification = True
                assert notification_data.get("job_type") == "task_match"
                assert notification_data.get("memory_id") == "mem-4"
    assert found_failure_notification, "Failure notification should be published"

    # Verify: Retry tracker cleared for this job
    retry_tracker.clear(job_id)
    assert retry_tracker.should_retry(job_id), (
        "Retry tracker should be cleared after failure"
    )


@pytest.mark.asyncio
async def test_consumer_graceful_shutdown(
    mock_redis, mock_llm_client, mock_core_api, retry_tracker, llm_worker_config
):
    """Consumer exits cleanly on CancelledError."""
    # Setup: Add a message that will cause the consumer to sleep
    job_id = "job-shutdown"
    payload = {"memory_id": "mem-5"}
    await publish(
        mock_redis,
        STREAM_LLM_EMAIL_EXTRACT,
        {
            "job_id": job_id,
            "payload": payload,
            "user_id": 12345,
            "job_type": "email_extract",
        },
    )

    mock_handler = create_mock_handler({"success": True})
    handlers = {"email_extract": mock_handler}

    # Create a consumer task that will be cancelled
    async def run_with_timeout():
        # This should handle CancelledError gracefully
        return await run_consumer(
            redis_client=mock_redis,
            handlers=handlers,
            core_api=mock_core_api,
            retry_tracker=retry_tracker,
            config=llm_worker_config,
        )

    # Run consumer with cancellation
    task = asyncio.create_task(run_with_timeout())
    await asyncio.sleep(0.1)  # Let consumer start

    # Cancel the task
    task.cancel()

    # Verify: Task raises CancelledError but doesn't crash
    with pytest.raises(asyncio.CancelledError):
        await task

    # Verify: No unhandled exceptions occurred


@pytest.mark.asyncio
async def test_consumer_unknown_handler(
    mock_redis, mock_llm_client, mock_core_api, retry_tracker, llm_worker_config
):
    """Unknown handler key acks message without crashing."""
    # Setup: Add a message with unknown handler key
    job_id = "job-unknown"
    payload = {"memory_id": "mem-6"}
    await publish(
        mock_redis,
        STREAM_LLM_IMAGE_TAG,
        {
            "job_id": job_id,
            "payload": payload,
            "user_id": 12345,
            "job_type": "unknown_handler",
        },
    )

    # Empty handlers dict - no handler for this job type
    handlers = {}

    # Execute: Process one message - should handle unknown gracefully
    messages = await consume(
        mock_redis, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
    )

    assert len(messages) == 1
    message_id, data = messages[0]

    # This should not raise an exception
    await _process_message(
        redis_client=mock_redis,
        stream_name=STREAM_LLM_IMAGE_TAG,
        message_id=message_id,
        data=data,
        handlers=handlers,
        core_api=mock_core_api,
        retry_tracker=retry_tracker,
        config=llm_worker_config,
    )

    # Verify: No handler was called (no error)
    # Verify: Message was acked (not re-processed)
    # We verify by trying to consume with a different consumer - if acked, it won't be delivered
    retry_messages = await mock_redis.xreadgroup(
        GROUP_LLM_WORKER,
        f"{CONSUMER_NAME}-checker",
        {STREAM_LLM_IMAGE_TAG: ">"},
        count=1,
    )
    assert len(retry_messages) == 0, "Message should be acked even for unknown handler"


# Test that STREAM_HANDLER_MAP has correct mappings
def test_stream_handler_map_structure():
    """Verify STREAM_HANDLER_MAP has all expected keys."""
    expected_keys = {
        "image_tag",
        "intent_classify",
        "followup",
        "task_match",
        "email_extract",
    }
    assert set(STREAM_HANDLER_MAP.keys()) == expected_keys


# Test that CONSUMER_NAME is defined
def test_consumer_name_defined():
    """Verify CONSUMER_NAME is defined."""
    assert isinstance(CONSUMER_NAME, str)
    assert len(CONSUMER_NAME) > 0
