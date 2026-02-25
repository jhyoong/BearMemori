"""LLM Worker consumer - processes jobs from Redis streams."""

import asyncio
import json
import logging
from typing import Any
from urllib.error import HTTPError

from shared_lib.redis_streams import (
    GROUP_LLM_WORKER,
    STREAM_LLM_EMAIL_EXTRACT,
    STREAM_LLM_FOLLOWUP,
    STREAM_LLM_IMAGE_TAG,
    STREAM_LLM_INTENT,
    STREAM_LLM_TASK_MATCH,
    STREAM_NOTIFY_TELEGRAM,
    ack,
    consume,
    create_consumer_group,
    publish,
)

from worker.core_api_client import CoreAPIClient
from worker.handlers.base import BaseHandler
from worker.retry import RetryManager, FailureType
from worker.config import LLMWorkerSettings

logger = logging.getLogger(__name__)

# Consumer group name for this worker
CONSUMER_NAME = "llm-worker-1"

# Map handler keys to stream names (for consumer loop iteration)
STREAM_HANDLER_MAP = {
    "image_tag": STREAM_LLM_IMAGE_TAG,
    "intent_classify": STREAM_LLM_INTENT,
    "followup": STREAM_LLM_FOLLOWUP,
    "task_match": STREAM_LLM_TASK_MATCH,
    "email_extract": STREAM_LLM_EMAIL_EXTRACT,
}

# Maps each stream to (handler_key, notification message_type)
STREAM_NOTIFICATION_TYPE = {
    STREAM_LLM_IMAGE_TAG: "llm_image_tag_result",
    STREAM_LLM_INTENT: "llm_intent_result",
    STREAM_LLM_FOLLOWUP: "llm_followup_result",
    STREAM_LLM_TASK_MATCH: "llm_task_match_result",
    STREAM_LLM_EMAIL_EXTRACT: "event_confirmation",
}


def _classify_failure_type(exception: Exception) -> FailureType:
    """Classify an exception into a FailureType.

    - Connection errors, timeouts, HTTP 5xx → UNAVAILABLE
    - Unparseable/invalid JSON, missing required fields → INVALID_RESPONSE
    """
    # Connection errors and timeouts → UNAVAILABLE
    if isinstance(exception, (ConnectionRefusedError, ConnectionError, OSError)):
        return FailureType.UNAVAILABLE
    if isinstance(exception, asyncio.TimeoutError):
        return FailureType.UNAVAILABLE

    # HTTP 5xx errors → UNAVAILABLE
    if isinstance(exception, HTTPError):
        if exception.code >= 500:
            return FailureType.UNAVAILABLE

    # JSON decode errors → INVALID_RESPONSE
    if isinstance(exception, json.JSONDecodeError):
        return FailureType.INVALID_RESPONSE

    # Missing required fields → INVALID_RESPONSE
    if isinstance(exception, ValueError):
        error_msg = str(exception).lower()
        if "missing required field" in error_msg or "required field" in error_msg:
            return FailureType.INVALID_RESPONSE

    # Default to INVALID_RESPONSE for other errors
    return FailureType.INVALID_RESPONSE


async def _process_message(
    redis_client,
    stream_name: str,
    message_id: str,
    data: dict[str, Any],
    handlers: dict[str, BaseHandler],
    core_api: CoreAPIClient,
    retry_tracker: RetryManager,
    config: LLMWorkerSettings,
) -> None:
    """Process a single message from a Redis stream.

    Args:
        redis_client: Async Redis client instance
        stream_name: Name of the stream the message came from
        message_id: Redis message ID
        data: Deserialized message data containing job_id, payload, user_id, job_type
        handlers: Dict mapping handler keys to handler instances
        core_api: Core API client for updating job status
        retry_tracker: Retry manager for managing retry logic
        config: LLM worker configuration
    """
    job_id = data.get("job_id")
    payload = data.get("payload", {})
    user_id = data.get("user_id")
    job_type = data.get("job_type")

    if not job_id:
        logger.warning(f"Message {message_id} missing job_id, acking")
        await ack(redis_client, stream_name, GROUP_LLM_WORKER, message_id)
        return

    if not job_type:
        logger.warning(f"Message {message_id} missing job_type, acking")
        await ack(redis_client, stream_name, GROUP_LLM_WORKER, message_id)
        return

    # Get handler for this job type
    handler: BaseHandler | None = handlers.get(job_type)

    # If no handler found, ack and skip
    if handler is None:
        logger.warning(f"No handler for job_type={job_type}, acking message")
        await ack(redis_client, stream_name, GROUP_LLM_WORKER, message_id)
        return

    try:
        # Call the handler
        result = await handler.handle(job_id, payload, user_id)

        if result is not None:
            # Job completed successfully with a result
            await core_api.update_job(job_id=job_id, status="completed", result=result)
            retry_tracker.clear(job_id)

            # Publish notification in wrapper format for Telegram consumer
            if user_id is not None:
                msg_type = STREAM_NOTIFICATION_TYPE.get(
                    stream_name, "event_confirmation"
                )
                await publish(
                    redis_client,
                    STREAM_NOTIFY_TELEGRAM,
                    {
                        "user_id": user_id,
                        "message_type": msg_type,
                        "content": result,
                    },
                )
        else:
            # Job completed but no notification needed
            await core_api.update_job(job_id=job_id, status="completed", result=None)
            retry_tracker.clear(job_id)

        # Ack the message after successful processing
        await ack(redis_client, stream_name, GROUP_LLM_WORKER, message_id)

    except Exception as e:
        logger.exception(f"Error processing job {job_id}: {str(e)}")

        # Classify the failure type
        failure_type = _classify_failure_type(e)

        # Set error_message based on failure type
        if failure_type == FailureType.INVALID_RESPONSE:
            error_message = type(e).__name__
        else:
            error_message = str(e)

        if failure_type == FailureType.INVALID_RESPONSE:
            # Record the attempt
            current_attempt = retry_tracker.record_attempt(
                job_id, FailureType.INVALID_RESPONSE
            )
            should_retry = retry_tracker.should_retry(job_id)

            if should_retry:
                # Should retry - update status to processing, don't ack
                await core_api.update_job(
                    job_id=job_id, status="processing", error_message=None
                )
                logger.info(
                    f"Job {job_id} failed (attempt {current_attempt}), will retry"
                )
                # Add backoff delay before returning (message not acked, will be retried)
                await asyncio.sleep(retry_tracker.backoff_seconds(job_id))
            else:
                # Max retries exceeded - mark as failed
                logger.error(f"Job {job_id} failed after {current_attempt} attempts")
                await core_api.update_job(
                    job_id=job_id, status="failed", error_message=error_message
                )

                # Publish llm_failure notification
                if user_id is not None:
                    await publish(
                        redis_client,
                        STREAM_NOTIFY_TELEGRAM,
                        {
                            "user_id": user_id,
                            "message_type": "llm_failure",
                            "content": {
                                "job_type": job_type,
                                "memory_id": payload.get("memory_id", ""),
                                "message": f"I couldn't process your request after several attempts. Please try again later.",
                            },
                        },
                    )

                # Clear retry state and ack the message
                retry_tracker.clear(job_id)
                await ack(redis_client, stream_name, GROUP_LLM_WORKER, message_id)

        elif failure_type == FailureType.UNAVAILABLE:
            # Check if this is the first time we see this job as unavailable
            is_first_occurrence = (
                retry_tracker.get_failure_type(job_id) is None
            )

            # Record unavailability (sets _queue_paused, tracks first time)
            retry_tracker.record_attempt(job_id, FailureType.UNAVAILABLE)

            if not retry_tracker.should_retry(job_id):
                # 14-day expiry reached - mark as failed
                logger.error(
                    f"Job {job_id} expired after 14 days of unavailability"
                )
                await core_api.update_job(
                    job_id=job_id, status="failed", error_message=type(e).__name__
                )

                # Publish llm_expiry notification
                if user_id is not None:
                    await publish(
                        redis_client,
                        STREAM_NOTIFY_TELEGRAM,
                        {
                            "user_id": user_id,
                            "message_type": "llm_expiry",
                            "content": {
                                "job_type": job_type,
                                "memory_id": payload.get("memory_id", ""),
                                "original_message": payload.get(
                                    "original_message", payload.get("text", "")
                                ),
                                "failure_type": "unavailable",
                            },
                        },
                    )

                # Clear retry state and ack the message
                retry_tracker.clear(job_id)
                await ack(redis_client, stream_name, GROUP_LLM_WORKER, message_id)
            else:
                # Within 14-day window - update status to processing, don't ack
                await core_api.update_job(
                    job_id=job_id, status="processing", error_message=None
                )
                logger.info(
                    f"Job {job_id} failed due to service unavailability, will retry"
                )

                # On first occurrence, publish service unavailable notification
                if is_first_occurrence and user_id is not None:
                    await publish(
                        redis_client,
                        STREAM_NOTIFY_TELEGRAM,
                        {
                            "user_id": user_id,
                            "message_type": "llm_failure",
                            "content": {
                                "job_type": job_type,
                                "memory_id": payload.get("memory_id", ""),
                                "message": "I couldn't generate tags right now due to a temporary service issue. I'll retry automatically once the service becomes available.",
                            },
                        },
                    )

                # Message not acked - will be retried later


async def run_consumer(
    redis_client,
    handlers: dict[str, BaseHandler],
    core_api: CoreAPIClient,
    retry_tracker: RetryManager,
    config: LLMWorkerSettings,
) -> None:
    """Run the LLM worker consumer loop.

    Creates consumer groups for all streams and processes messages in round-robin
    across all streams.

    Args:
        redis_client: Async Redis client instance
        handlers: Dict mapping handler keys to handler instances
        core_api: Core API client
        retry_tracker: Retry manager for managing retry logic
        config: LLM worker configuration
    """
    # Get stream names from the mapping values
    streams = list(STREAM_HANDLER_MAP.values())

    # Create consumer groups for all streams
    for stream_name in streams:
        await create_consumer_group(redis_client, stream_name, GROUP_LLM_WORKER)
        logger.info(f"Created consumer group for {stream_name}")

    logger.info(f"Starting consumer loop for {len(streams)} streams")

    try:
        while True:
            # Round-robin through all streams
            for stream_name in streams:
                messages = await consume(
                    redis_client,
                    stream_name,
                    GROUP_LLM_WORKER,
                    CONSUMER_NAME,
                    count=1,
                    block_ms=1000,  # Short block for responsiveness
                )

                for message_id, data in messages:
                    logger.info(f"Processing message {message_id} from {stream_name}")
                    await _process_message(
                        redis_client=redis_client,
                        stream_name=stream_name,
                        message_id=message_id,
                        data=data,
                        handlers=handlers,
                        core_api=core_api,
                        retry_tracker=retry_tracker,
                        config=config,
                    )

            # Small delay to prevent tight loop
            await asyncio.sleep(0.1)

    except asyncio.CancelledError:
        logger.info("Consumer cancelled, shutting down gracefully")
        raise
