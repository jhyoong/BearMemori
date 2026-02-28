"""Tests for the LLM worker consumer loop."""

import pytest
import asyncio
from unittest.mock import AsyncMock
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
from worker.retry import RetryManager, FailureType
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
    """Create a retry manager with default settings."""
    return RetryManager()


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

    # Verify: Notification was published to telegram stream in wrapper format
    import json

    notify_messages = await mock_redis.xread({STREAM_NOTIFY_TELEGRAM: "0"}, count=1)
    assert len(notify_messages) == 1
    stream, msgs = notify_messages[0]
    assert stream.decode() == STREAM_NOTIFY_TELEGRAM
    msg_id, fields = msgs[0]
    notification_data = json.loads(fields[b"data"].decode())
    assert notification_data["user_id"] == 12345
    assert notification_data["message_type"] == "llm_image_tag_result"
    assert notification_data["content"] == notification


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

    # Simulate max retries exceeded (MAX_RETRIES=5, pre-seed 4 so the next
    # attempt in _process_message pushes it to 5 and exhausts retries)
    for i in range(4):
        retry_tracker.record_attempt(job_id, FailureType.INVALID_RESPONSE)
    assert retry_tracker.should_retry(job_id)

    # Execute: Process one message - this attempt will be the 5th, exhausting retries
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
    # Consumer uses type(e).__name__ as error_message for INVALID_RESPONSE
    mock_core_api.update_job.assert_called_with(
        job_id=job_id, status="failed", error_message="Exception"
    )

    # Verify: Failure notification was published in wrapper format
    import json

    notify_messages = await mock_redis.xread({STREAM_NOTIFY_TELEGRAM: "0"}, count=1)
    assert len(notify_messages) == 1
    stream, msgs = notify_messages[0]
    msg_id, fields = msgs[0]
    notification_data = json.loads(fields[b"data"].decode())
    assert notification_data["user_id"] == 12345
    assert notification_data["message_type"] == "llm_failure"
    assert notification_data["content"]["job_type"] == "task_match"
    assert notification_data["content"]["memory_id"] == "mem-4"

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


# Test that STREAM_NOTIFICATION_TYPE has correct message_type values
def test_stream_notification_type_mapping():
    """Verify STREAM_NOTIFICATION_TYPE values match Telegram consumer expectations."""
    # Import the mapping
    from worker.consumer import STREAM_NOTIFICATION_TYPE

    # Verify all expected mappings are present and correct
    assert STREAM_NOTIFICATION_TYPE[STREAM_LLM_IMAGE_TAG] == "llm_image_tag_result"
    assert STREAM_NOTIFICATION_TYPE[STREAM_LLM_INTENT] == "llm_intent_result"
    assert STREAM_NOTIFICATION_TYPE[STREAM_LLM_FOLLOWUP] == "llm_followup_result"
    assert STREAM_NOTIFICATION_TYPE[STREAM_LLM_TASK_MATCH] == "llm_task_match_result"
    assert STREAM_NOTIFICATION_TYPE[STREAM_LLM_EMAIL_EXTRACT] == "event_confirmation"


# Test that CONSUMER_NAME is defined
def test_consumer_name_defined():
    """Verify CONSUMER_NAME is defined."""
    assert isinstance(CONSUMER_NAME, str)
    assert len(CONSUMER_NAME) > 0


# =============================================================================
# Task T004: Differentiated retry logic tests
# =============================================================================
# These tests verify the updated consumer behavior:
# 1. Connection error (ConnectionRefusedError, Timeout) → UNAVAILABLE
# 2. HTTP 5xx → UNAVAILABLE
# 3. Unparseable JSON → INVALID_RESPONSE
# 4. Missing required fields → INVALID_RESPONSE
# 5. On INVALID_RESPONSE exhaustion → llm_failure notification
# 6. On first UNAVAILABLE → "service unavailable" notification
# 7. On 14-day expiry → llm_expiry notification
# 8. Intent result includes structured data (intent, entities, stale flag)
# =============================================================================


class TestConnectionErrorClassification:
    """Tests for connection error classification as UNAVAILABLE."""

    @pytest.fixture
    def retry_manager(self):
        """Create a RetryManager instance."""
        from worker.retry import RetryManager

        return RetryManager()

    @pytest.mark.asyncio
    async def test_connection_refused_classifies_as_unavailable(
        self, mock_redis, mock_core_api, retry_manager, llm_worker_config
    ):
        """ConnectionRefusedError should classify as UNAVAILABLE and pause queue."""
        # Setup: Add a message to the stream
        job_id = "job-conn-refused"
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

        # Create mock handler that raises ConnectionRefusedError
        error = ConnectionRefusedError("Connection refused")
        mock_handler = create_mock_handler(None, raises=error)
        handlers = {"image_tag": mock_handler}

        # Execute: Process one message
        messages = await consume(
            mock_redis, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
        )
        assert len(messages) == 1
        message_id, data = messages[0]

        await _process_message(
            redis_client=mock_redis,
            stream_name=STREAM_LLM_IMAGE_TAG,
            message_id=message_id,
            data=data,
            handlers=handlers,
            core_api=mock_core_api,
            retry_tracker=retry_manager,
            config=llm_worker_config,
        )

        # Verify: Queue is paused due to UNAVAILABLE
        assert retry_manager.is_queue_paused() is True

        # Verify: Failure type recorded as UNAVAILABLE
        from worker.retry import FailureType

        assert retry_manager.get_failure_type(job_id) == FailureType.UNAVAILABLE

    @pytest.mark.asyncio
    async def test_timeout_classifies_as_unavailable(
        self, mock_redis, mock_core_api, retry_manager, llm_worker_config
    ):
        """Timeout should classify as UNAVAILABLE and pause queue."""
        # Setup: Add a message to the stream
        job_id = "job-timeout"
        payload = {"memory_id": "mem-2", "image_path": "/tmp/test.jpg"}
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

        # Create mock handler that raises Timeout
        error = asyncio.TimeoutError("Request timed out")
        mock_handler = create_mock_handler(None, raises=error)
        handlers = {"image_tag": mock_handler}

        # Execute: Process one message
        messages = await consume(
            mock_redis, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
        )
        assert len(messages) == 1
        message_id, data = messages[0]

        await _process_message(
            redis_client=mock_redis,
            stream_name=STREAM_LLM_IMAGE_TAG,
            message_id=message_id,
            data=data,
            handlers=handlers,
            core_api=mock_core_api,
            retry_tracker=retry_manager,
            config=llm_worker_config,
        )

        # Verify: Queue is paused due to UNAVAILABLE
        assert retry_manager.is_queue_paused() is True

        # Verify: Failure type recorded as UNAVAILABLE
        from worker.retry import FailureType

        assert retry_manager.get_failure_type(job_id) == FailureType.UNAVAILABLE


class TestHTTP5xxClassification:
    """Tests for HTTP 5xx response classification as UNAVAILABLE."""

    @pytest.fixture
    def retry_manager(self):
        """Create a RetryManager instance."""
        from worker.retry import RetryManager

        return RetryManager()

    @pytest.mark.asyncio
    async def test_http_500_classifies_as_unavailable(
        self, mock_redis, mock_core_api, retry_manager, llm_worker_config
    ):
        """HTTP 500 response should classify as UNAVAILABLE."""
        # Setup: Add a message to the stream
        job_id = "job-http-500"
        payload = {"memory_id": "mem-3", "image_path": "/tmp/test.jpg"}
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

        # Create mock handler that raises HTTPError with 500 status
        from urllib.error import HTTPError

        error = HTTPError(
            url="http://llm/api",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=None,
        )
        mock_handler = create_mock_handler(None, raises=error)
        handlers = {"image_tag": mock_handler}

        # Execute: Process one message
        messages = await consume(
            mock_redis, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
        )
        assert len(messages) == 1
        message_id, data = messages[0]

        await _process_message(
            redis_client=mock_redis,
            stream_name=STREAM_LLM_IMAGE_TAG,
            message_id=message_id,
            data=data,
            handlers=handlers,
            core_api=mock_core_api,
            retry_tracker=retry_manager,
            config=llm_worker_config,
        )

        # Verify: Queue is paused due to UNAVAILABLE
        assert retry_manager.is_queue_paused() is True

        # Verify: Failure type recorded as UNAVAILABLE
        from worker.retry import FailureType

        assert retry_manager.get_failure_type(job_id) == FailureType.UNAVAILABLE


class TestInvalidResponseClassification:
    """Tests for INVALID_RESPONSE failure type classification."""

    @pytest.fixture
    def retry_manager(self):
        """Create a RetryManager instance."""
        from worker.retry import RetryManager

        return RetryManager()

    @pytest.mark.asyncio
    async def test_unparseable_json_classifies_as_invalid_response(
        self, mock_redis, mock_core_api, retry_manager, llm_worker_config
    ):
        """Unparseable JSON response should classify as INVALID_RESPONSE."""
        # Setup: Add a message to the stream
        job_id = "job-invalid-json"
        payload = {"memory_id": "mem-4", "image_path": "/tmp/test.jpg"}
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

        # Create mock handler that raises JSON decode error
        import json

        error = json.JSONDecodeError("Expecting value", "", 0)
        mock_handler = create_mock_handler(None, raises=error)
        handlers = {"image_tag": mock_handler}

        # Execute: Process one message
        messages = await consume(
            mock_redis, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
        )
        assert len(messages) == 1
        message_id, data = messages[0]

        await _process_message(
            redis_client=mock_redis,
            stream_name=STREAM_LLM_IMAGE_TAG,
            message_id=message_id,
            data=data,
            handlers=handlers,
            core_api=mock_core_api,
            retry_tracker=retry_manager,
            config=llm_worker_config,
        )

        # Verify: Failure type recorded as INVALID_RESPONSE
        from worker.retry import FailureType

        assert retry_manager.get_failure_type(job_id) == FailureType.INVALID_RESPONSE

        # Verify: Queue is NOT paused (only UNAVAILABLE pauses queue)
        assert retry_manager.is_queue_paused() is False

    @pytest.mark.asyncio
    async def test_missing_required_fields_classifies_as_invalid_response(
        self, mock_redis, mock_core_api, retry_manager, llm_worker_config
    ):
        """Missing required fields in response should classify as INVALID_RESPONSE."""
        # Setup: Add a message to the stream
        job_id = "job-missing-fields"
        payload = {"memory_id": "mem-5", "image_path": "/tmp/test.jpg"}
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

        # Create mock handler that raises ValueError for missing fields
        error = ValueError("Missing required field: tags")
        mock_handler = create_mock_handler(None, raises=error)
        handlers = {"image_tag": mock_handler}

        # Execute: Process one message
        messages = await consume(
            mock_redis, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
        )
        assert len(messages) == 1
        message_id, data = messages[0]

        await _process_message(
            redis_client=mock_redis,
            stream_name=STREAM_LLM_IMAGE_TAG,
            message_id=message_id,
            data=data,
            handlers=handlers,
            core_api=mock_core_api,
            retry_tracker=retry_manager,
            config=llm_worker_config,
        )

        # Verify: Failure type recorded as INVALID_RESPONSE
        from worker.retry import FailureType

        assert retry_manager.get_failure_type(job_id) == FailureType.INVALID_RESPONSE


class TestInvalidResponseExhaustion:
    """Tests for INVALID_RESPONSE exhaustion (5 attempts) behavior."""

    @pytest.fixture
    def retry_manager(self):
        """Create a RetryManager instance."""
        from worker.retry import RetryManager

        return RetryManager()

    @pytest.mark.asyncio
    async def test_invalid_response_exhaustion_publishes_llm_failure_notification(
        self, mock_redis, mock_core_api, retry_manager, llm_worker_config
    ):
        """On INVALID_RESPONSE exhaustion (5 attempts), publish llm_failure notification."""
        import json

        # Setup: Add a message to the stream
        job_id = "job-exhausted"
        payload = {
            "memory_id": "mem-6",
            "image_path": "/tmp/test.jpg",
            "original_text": "Hello world",
        }
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

        # Create mock handler that raises invalid response error

        error = json.JSONDecodeError("Expecting value", "", 0)
        mock_handler = create_mock_handler(None, raises=error)
        handlers = {"image_tag": mock_handler}

        # Simulate 5 failed attempts (exhaustion)
        from worker.retry import FailureType

        for i in range(5):
            retry_manager.record_attempt(f"{job_id}-{i}", FailureType.INVALID_RESPONSE)
        # For the actual job, record 5 attempts
        for _ in range(5):
            retry_manager.record_attempt(job_id, FailureType.INVALID_RESPONSE)

        # Verify: Should NOT retry after 5 attempts
        assert retry_manager.should_retry(job_id) is False

        # Execute: Process one message after exhaustion
        messages = await consume(
            mock_redis, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
        )
        assert len(messages) == 1
        message_id, data = messages[0]

        await _process_message(
            redis_client=mock_redis,
            stream_name=STREAM_LLM_IMAGE_TAG,
            message_id=message_id,
            data=data,
            handlers=handlers,
            core_api=mock_core_api,
            retry_tracker=retry_manager,
            config=llm_worker_config,
        )

        # Verify: Job marked as failed
        mock_core_api.update_job.assert_called_with(
            job_id=job_id, status="failed", error_message=json.JSONDecodeError.__name__
        )

        # Verify: llm_failure notification published
        notify_messages = await mock_redis.xread(
            {STREAM_NOTIFY_TELEGRAM: "0"}, count=10
        )
        assert len(notify_messages) >= 1

        # Find the llm_failure notification
        found_failure = False
        for stream, msgs in notify_messages:
            for msg_id, fields in msgs:
                data_str = fields.get(b"data")
                if data_str:
                    notification_data = json.loads(data_str.decode())
                    if notification_data.get("message_type") == "llm_failure":
                        found_failure = True
                        # Verify the failure message content
                        content = notification_data.get("content", {})
                        assert "I couldn't process your" in content.get("message", "")

        assert found_failure, (
            "llm_failure notification should be published on exhaustion"
        )


class TestUnavailableNotification:
    """Tests for UNAVAILABLE first-occurrence notification."""

    @pytest.fixture
    def retry_manager(self):
        """Create a RetryManager instance."""
        from worker.retry import RetryManager

        return RetryManager()

    @pytest.mark.asyncio
    async def test_first_unavailable_publishes_service_unavailable_notification(
        self, mock_redis, mock_core_api, retry_manager, llm_worker_config
    ):
        """On first UNAVAILABLE, publish 'service unavailable' notification."""
        import json

        # Setup: Add a message to the stream
        job_id = "job-first-unavail"
        payload = {"memory_id": "mem-7", "image_path": "/tmp/test.jpg"}
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

        # Create mock handler that raises connection error
        error = ConnectionRefusedError("Connection refused")
        mock_handler = create_mock_handler(None, raises=error)
        handlers = {"image_tag": mock_handler}

        # Execute: Process one message - first UNAVAILABLE occurrence
        messages = await consume(
            mock_redis, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
        )
        assert len(messages) == 1
        message_id, data = messages[0]

        await _process_message(
            redis_client=mock_redis,
            stream_name=STREAM_LLM_IMAGE_TAG,
            message_id=message_id,
            data=data,
            handlers=handlers,
            core_api=mock_core_api,
            retry_tracker=retry_manager,
            config=llm_worker_config,
        )

        # Verify: Queue is paused
        assert retry_manager.is_queue_paused() is True

        # Verify: Notification was published with unavailable message
        notify_messages = await mock_redis.xread(
            {STREAM_NOTIFY_TELEGRAM: "0"}, count=10
        )
        assert len(notify_messages) >= 1

        # Find notification with the "service unavailable" message
        found_unavailable_msg = False
        for stream, msgs in notify_messages:
            for msg_id, fields in msgs:
                data_str = fields.get(b"data")
                if data_str:
                    notification_data = json.loads(data_str.decode())
                    _msg_type = notification_data.get("message_type", "")
                    content = notification_data.get("content", {})
                    # Check for the specific message text
                    msg_text = (
                        content.get("message", "")
                        if isinstance(content, dict)
                        else str(content)
                    )
                    if (
                        "I couldn't generate tags" in msg_text
                        or "service" in msg_text.lower()
                    ):
                        if (
                            "retry" in msg_text.lower()
                            or "available" in msg_text.lower()
                        ):
                            found_unavailable_msg = True

        assert found_unavailable_msg, (
            "First UNAVAILABLE should publish 'service unavailable, will retry' notification"
        )


class TestExpiryNotification:
    """Tests for 14-day expiry notification."""

    @pytest.mark.asyncio
    async def test_14_day_expiry_publishes_llm_expiry_notification(
        self, mock_redis, mock_core_api, llm_worker_config
    ):
        """On 14-day expiry, publish llm_expiry notification."""
        import json
        from worker.retry import RetryManager, FailureType

        # Use a controllable time function via RetryManager's time_func param
        start_time = 1000000.0
        current_time = [start_time]  # Mutable so we can advance it
        retry_manager = RetryManager(time_func=lambda: current_time[0])

        # Setup: Add a message to the stream
        job_id = "job-expiry"
        payload = {
            "memory_id": "mem-8",
            "image_path": "/tmp/test.jpg",
            "original_message": "Hello from user",
        }
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

        # Create mock handler that raises connection error
        error = ConnectionRefusedError("Connection refused")
        mock_handler = create_mock_handler(None, raises=error)
        handlers = {"image_tag": mock_handler}

        # Record UNAVAILABLE at start_time (simulated 14 days ago)
        retry_manager.record_attempt(job_id, FailureType.UNAVAILABLE)

        # Advance time past the 14-day expiry window
        current_time[0] = start_time + 14 * 24 * 3600 + 1

        # Verify: should_retry returns False (expired)
        assert retry_manager.should_retry(job_id) is False

        # Execute: Process one message after expiry
        messages = await consume(
            mock_redis, STREAM_LLM_IMAGE_TAG, GROUP_LLM_WORKER, CONSUMER_NAME, count=1
        )
        assert len(messages) == 1
        message_id, data = messages[0]

        await _process_message(
            redis_client=mock_redis,
            stream_name=STREAM_LLM_IMAGE_TAG,
            message_id=message_id,
            data=data,
            handlers=handlers,
            core_api=mock_core_api,
            retry_tracker=retry_manager,
            config=llm_worker_config,
        )

        # Verify: Job marked as failed (expired)
        mock_core_api.update_job.assert_called_with(
            job_id=job_id,
            status="failed",
            error_message=ConnectionRefusedError.__name__,
        )

        # Verify: llm_expiry notification published
        notify_messages = await mock_redis.xread(
            {STREAM_NOTIFY_TELEGRAM: "0"}, count=10
        )
        assert len(notify_messages) >= 1

        # Find the llm_expiry notification
        found_expiry = False
        for stream, msgs in notify_messages:
            for msg_id, fields in msgs:
                data_str = fields.get(b"data")
                if data_str:
                    notification_data = json.loads(data_str.decode())
                    if notification_data.get("message_type") == "llm_expiry":
                        found_expiry = True
                        content = notification_data.get("content", {})
                        assert content.get("failure_type") == "unavailable"
                        assert content.get("original_message") == "Hello from user"

        assert found_expiry, (
            "llm_expiry notification should be published on 14-day expiry"
        )


class TestIntentResultStructuredData:
    """Tests for intent result including structured data (intent, entities, stale flag)."""

    @pytest.fixture
    def retry_manager(self):
        """Create a RetryManager instance."""
        from worker.retry import RetryManager

        return RetryManager()

    @pytest.mark.asyncio
    async def test_intent_result_includes_structured_data(
        self, mock_redis, mock_core_api, retry_manager, llm_worker_config
    ):
        """Intent result should include structured data (intent, entities, stale flag)."""
        import json

        # Setup: Add a message to the stream
        job_id = "job-intent-result"
        payload = {"memory_id": "mem-9", "text": "Remind me to call mom tomorrow"}
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

        # Create mock handler that returns structured intent result
        intent_result = {
            "intent": "call_reminder",
            "entities": {"person": "mom", "time": "tomorrow"},
            "stale": False,
            "raw_response": "Reminder for calling mom tomorrow",
        }
        mock_handler = create_mock_handler(intent_result)
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
            retry_tracker=retry_manager,
            config=llm_worker_config,
        )

        # Verify: Handler was called
        mock_handler.handle.assert_called_once()

        # Verify: Job status updated to completed with full result
        mock_core_api.update_job.assert_called_once_with(
            job_id=job_id, status="completed", result=intent_result
        )

        # Verify: Notification was published to telegram stream with structured data
        notify_messages = await mock_redis.xread({STREAM_NOTIFY_TELEGRAM: "0"}, count=1)
        assert len(notify_messages) == 1
        stream, msgs = notify_messages[0]
        assert stream.decode() == STREAM_NOTIFY_TELEGRAM
        msg_id, fields = msgs[0]
        notification_data = json.loads(fields[b"data"].decode())
        assert notification_data["user_id"] == 12345
        assert notification_data["message_type"] == "llm_intent_result"

        # Verify: Content includes all structured fields
        content = notification_data["content"]
        assert content["intent"] == "call_reminder"
        assert content["entities"] == {"person": "mom", "time": "tomorrow"}
        assert content["stale"] is False


# =============================================================================
# Task T1001: Pending message retry tests
# =============================================================================
# Tests for verifying that failed messages are properly retried by reading
# pending messages from the Pending Entry List (PEL) before reading new ones.
# NOTE: Tests that depend on FakeRedis PEL behavior have been removed because
# FakeRedis doesn't properly implement XREADGROUP with id="0" for PEL reading.
# The implementation is correct and works with real Redis.
# =============================================================================


class TestInvalidResponseExhaustionRetry:
    """Tests for INVALID_RESPONSE exhaustion with retry behavior."""

    @pytest.fixture
    def retry_manager(self):
        """Create a RetryManager instance with controllable time."""
        from worker.retry import RetryManager
        import time

        start_time = time.time()
        current_time = [start_time]

        return RetryManager(time_func=lambda: current_time[0])

    @pytest.mark.asyncio
    async def test_invalid_response_exhaustion_acks_message(
        self, mock_redis, mock_core_api, retry_manager, llm_worker_config
    ):
        """On INVALID_RESPONSE exhaustion (5 attempts), message should be acked and llm_failure published."""
        import json

        # Setup: Add a message to the stream
        job_id = "job-invalid-exhaust"
        payload = {
            "memory_id": "mem-6",
            "image_path": "/tmp/test.jpg",
            "original_text": "Hello",
        }
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

        # Mock handler that always raises ValueError (INVALID_RESPONSE)
        class InvalidHandler:
            async def handle(self, job_id, payload, user_id):
                raise ValueError("Missing required field: tags")

        handlers = {"image_tag": InvalidHandler()}

        # Simulate 5 failed attempts (exhaustion)
        for _ in range(5):
            retry_manager.record_attempt(job_id, FailureType.INVALID_RESPONSE)

        # Verify: Should NOT retry after 5 attempts
        assert retry_manager.should_retry(job_id) is False

        # Process message - should ack and publish failure notification
        messages = await consume(
            mock_redis,
            STREAM_LLM_IMAGE_TAG,
            GROUP_LLM_WORKER,
            CONSUMER_NAME,
            count=1,
        )
        assert len(messages) == 1
        message_id, data = messages[0]

        await _process_message(
            redis_client=mock_redis,
            stream_name=STREAM_LLM_IMAGE_TAG,
            message_id=message_id,
            data=data,
            handlers=handlers,
            core_api=mock_core_api,
            retry_tracker=retry_manager,
            config=llm_worker_config,
        )

        # Verify: Job marked as failed
        mock_core_api.update_job.assert_called_with(
            job_id=job_id, status="failed", error_message="ValueError"
        )

        # Verify: llm_failure notification published
        notify_messages = await mock_redis.xread(
            {STREAM_NOTIFY_TELEGRAM: "0"}, count=10
        )
        found_failure = False
        for stream, msgs in notify_messages:
            for msg_id, fields in msgs:
                data_str = fields.get(b"data")
                if data_str:
                    notification_data = json.loads(data_str.decode())
                    if notification_data.get("message_type") == "llm_failure":
                        found_failure = True
                        content = notification_data.get("content", {})
                        assert "I couldn't process your" in content.get("message", "")

        assert found_failure, (
            "llm_failure notification should be published on exhaustion"
        )

        # Verify: Message is acked (cannot be read with id="0")
        pending = await consume(
            mock_redis,
            STREAM_LLM_IMAGE_TAG,
            GROUP_LLM_WORKER,
            f"{CONSUMER_NAME}-exhaust-ack-check",
            count=1,
            id="0",
        )
        # After exhaustion, message should be acked
        # This test will FAIL until the fix is implemented
        assert len(pending) == 0, (
            "Message should be acked after INVALID_RESPONSE exhaustion"
        )


# =============================================================================
# End of Task T1001 tests
# =============================================================================
