"""LLM Worker consumer - processes jobs from Redis streams."""

import asyncio
import logging
from typing import Any

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
from worker.retry import RetryTracker
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

# Notification types
NOTIFICATION_TYPE_IMAGE_TAG = "image_tag_result"
NOTIFICATION_TYPE_INTENT = "intent_result"
NOTIFICATION_TYPE_FOLLOWUP = "followup_result"
NOTIFICATION_TYPE_TASK_MATCH = "task_match_result"
NOTIFICATION_TYPE_CONFIRMATION = "event_confirmation"
NOTIFICATION_TYPE_FAILURE = "job_failed"

# Stream to notification type mapping
STREAM_TO_NOTIFICATION_TYPE = {
    STREAM_LLM_IMAGE_TAG: NOTIFICATION_TYPE_IMAGE_TAG,
    STREAM_LLM_INTENT: NOTIFICATION_TYPE_INTENT,
    STREAM_LLM_FOLLOWUP: NOTIFICATION_TYPE_FOLLOWUP,
    STREAM_LLM_TASK_MATCH: NOTIFICATION_TYPE_TASK_MATCH,
    STREAM_LLM_EMAIL_EXTRACT: NOTIFICATION_TYPE_CONFIRMATION,
}


async def _process_message(
    redis_client,
    stream_name: str,
    message_id: str,
    data: dict[str, Any],
    handlers: dict[str, BaseHandler],
    core_api: CoreAPIClient,
    retry_tracker: RetryTracker,
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
        retry_tracker: Retry tracker for managing retry logic
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

    # Check if we should retry (pre-check for retry case)
    current_attempt = retry_tracker.record_attempt(job_id)
    should_retry = retry_tracker.should_retry(job_id)

    # Note: We call "processing" only when handler fails (in except block)
    # For success, we directly call "completed"

    try:
        # Call the handler
        result = await handler.handle(job_id, payload, user_id)

        if result is not None:
            # Job completed successfully with a result - update status and publish notification
            await core_api.update_job(job_id=job_id, status="completed", result=result)
            retry_tracker.clear(job_id)

            # Publish notification
            notification_data = {
                "type": STREAM_TO_NOTIFICATION_TYPE.get(
                    stream_name, "event_confirmation"
                ),
                "job_id": job_id,
                "memory_id": payload.get("memory_id"),
                **result,
            }
            await publish(redis_client, STREAM_NOTIFY_TELEGRAM, notification_data)
        else:
            # Job completed but no notification needed
            await core_api.update_job(job_id=job_id, status="completed", result=None)
            retry_tracker.clear(job_id)

        # Ack the message after successful processing
        await ack(redis_client, stream_name, GROUP_LLM_WORKER, message_id)

    except Exception as e:
        error_message = str(e)
        logger.exception(f"Error processing job {job_id}: {error_message}")

        if should_retry:
            # Should retry - update status to processing, don't ack
            await core_api.update_job(
                job_id=job_id, status="processing", error_message=None
            )
            logger.info(f"Job {job_id} failed (attempt {current_attempt}), will retry")
            # Add a small delay before returning to allow for backoff
            await asyncio.sleep(retry_tracker.backoff_seconds(job_id))
        else:
            # Max retries exceeded - mark as failed
            logger.error(f"Job {job_id} failed after {current_attempt} attempts")
            await core_api.update_job(
                job_id=job_id, status="failed", error_message=error_message
            )

            # Publish failure notification
            failure_notification = {
                "type": NOTIFICATION_TYPE_FAILURE,
                "job_id": job_id,
                "job_type": job_type,
                "memory_id": payload.get("memory_id"),
                "error_message": error_message,
            }
            await publish(redis_client, STREAM_NOTIFY_TELEGRAM, failure_notification)

            # Clear retry tracker and ack the message
            retry_tracker.clear(job_id)
            await ack(redis_client, stream_name, GROUP_LLM_WORKER, message_id)


async def run_consumer(
    redis_client,
    handlers: dict[str, BaseHandler],
    core_api: CoreAPIClient,
    retry_tracker: RetryTracker,
    config: LLMWorkerSettings,
) -> None:
    """Run the LLM worker consumer loop.

    Creates consumer groups for all streams and processes messages in round-robin
    across all streams.

    Args:
        redis_client: Async Redis client instance
        handlers: Dict mapping handler keys to handler instances
        core_api: Core API client
        retry_tracker: Retry tracker for managing retry logic
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
