# Sub-phase 3.3: Consumer Loop and Main Entrypoint

## Context

This sub-phase wires the handlers (from 3.2) into a Redis consumer loop and replaces the stub `main.py` with a real entrypoint. After this sub-phase, the LLM worker is a complete service that consumes jobs from Redis, processes them, and publishes notifications.

**Prerequisites from sub-phase 3.1 (already built):**
- `llm_worker/worker/config.py` -- `LLMWorkerSettings`, `load_llm_worker_settings()`
- `llm_worker/worker/llm_client.py` -- `LLMClient` with `complete()`, `complete_with_image()`, `close()`
- `llm_worker/worker/core_api_client.py` -- `CoreAPIClient` with `update_job()`, `add_tags()`, `create_event()`, `get_open_tasks()`
- `llm_worker/worker/retry.py` -- `RetryTracker` with `record_attempt()`, `should_retry()`, `clear()`, `backoff_seconds()`
- `llm_worker/worker/utils.py` -- `extract_json()`

**Prerequisites from sub-phase 3.2 (already built):**
- `llm_worker/worker/handlers/image_tag.py` -- `ImageTagHandler`
- `llm_worker/worker/handlers/intent.py` -- `IntentHandler`
- `llm_worker/worker/handlers/followup.py` -- `FollowupHandler`
- `llm_worker/worker/handlers/task_match.py` -- `TaskMatchHandler`
- `llm_worker/worker/handlers/email_extract.py` -- `EmailExtractHandler`
- All handlers follow `BaseHandler` interface: `async handle(job_id, payload, user_id) -> dict | None`

**Shared library functions used (do not modify):**
- `shared_lib.redis_streams.consume(redis, stream, group, consumer, count, block_ms)` -- reads from one stream at a time, returns `list[tuple[msg_id, data_dict]]`
- `shared_lib.redis_streams.ack(redis, stream, group, msg_id)` -- acknowledges a message
- `shared_lib.redis_streams.create_consumer_group(redis, stream, group)` -- creates consumer group, ignores if exists
- `shared_lib.redis_streams.publish(redis, stream, data)` -- publishes to a stream

**Stream and group constants (from `shared_lib.redis_streams`):**
- `STREAM_LLM_IMAGE_TAG = "llm:image_tag"`
- `STREAM_LLM_INTENT = "llm:intent"`
- `STREAM_LLM_FOLLOWUP = "llm:followup"`
- `STREAM_LLM_TASK_MATCH = "llm:task_match"`
- `STREAM_LLM_EMAIL_EXTRACT = "llm:email_extract"`
- `STREAM_NOTIFY_TELEGRAM = "notify:telegram"`
- `GROUP_LLM_WORKER = "llm-worker-group"`

**Notification wrapper format (published to `notify:telegram`):**
```python
{
    "user_id": int,        # Telegram user ID
    "message_type": str,   # e.g. "llm_image_tag_result"
    "content": dict        # handler's return value
}
```

**Failure notification format:**
```python
{
    "user_id": int,
    "message_type": "llm_failure",
    "content": {"job_type": str, "memory_id": str}
}
```

---

## Files to Create

### 1. `llm_worker/worker/consumer.py`

The main consumer loop that processes jobs from all 5 LLM Redis streams.

```python
"""Redis stream consumer for LLM job processing."""

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

logger = logging.getLogger(__name__)

CONSUMER_NAME = "llm-worker-1"

# Maps each stream to (handler_key, notification_message_type)
STREAM_HANDLER_MAP: dict[str, tuple[str, str]] = {
    STREAM_LLM_IMAGE_TAG: ("image_tag", "llm_image_tag_result"),
    STREAM_LLM_INTENT: ("intent_classify", "llm_intent_result"),
    STREAM_LLM_FOLLOWUP: ("followup", "llm_followup_result"),
    STREAM_LLM_TASK_MATCH: ("task_match", "llm_task_match_result"),
    STREAM_LLM_EMAIL_EXTRACT: ("email_extract", "event_confirmation"),
}


async def run_consumer(
    redis_client,
    handlers: dict[str, BaseHandler],
    core_api: CoreAPIClient,
    retry_tracker: RetryTracker,
) -> None:
    """Main consumer loop.

    Iterates over all LLM streams in round-robin, consuming one
    message at a time per stream with a short block timeout.

    Args:
        redis_client: Async Redis client.
        handlers: Dict mapping handler_key to BaseHandler instances.
        core_api: Core API HTTP client.
        retry_tracker: In-memory retry tracker.
    """
    # Create consumer groups for all streams
    for stream_name in STREAM_HANDLER_MAP:
        await create_consumer_group(
            redis_client, stream_name, GROUP_LLM_WORKER
        )

    logger.info("LLM Worker consumer started, listening on %d streams",
                len(STREAM_HANDLER_MAP))

    while True:
        try:
            for stream_name, (handler_key, msg_type) in STREAM_HANDLER_MAP.items():
                messages = await consume(
                    redis_client,
                    stream_name,
                    GROUP_LLM_WORKER,
                    CONSUMER_NAME,
                    count=1,
                    block_ms=1000,
                )

                for msg_id, data in messages:
                    await _process_message(
                        redis_client=redis_client,
                        stream_name=stream_name,
                        msg_id=msg_id,
                        data=data,
                        handler_key=handler_key,
                        msg_type=msg_type,
                        handlers=handlers,
                        core_api=core_api,
                        retry_tracker=retry_tracker,
                    )

        except asyncio.CancelledError:
            logger.info("LLM Worker consumer shutting down")
            break
        except Exception:
            logger.exception("Unexpected error in consumer loop, backing off")
            await asyncio.sleep(5)


async def _process_message(
    redis_client,
    stream_name: str,
    msg_id: str,
    data: dict[str, Any],
    handler_key: str,
    msg_type: str,
    handlers: dict[str, BaseHandler],
    core_api: CoreAPIClient,
    retry_tracker: RetryTracker,
) -> None:
    """Process a single message from a stream."""
    job_id = data.get("job_id", "unknown")
    payload = data.get("payload", {})
    user_id = data.get("user_id")

    logger.info("Processing job %s (type: %s)", job_id, handler_key)

    handler = handlers.get(handler_key)
    if not handler:
        logger.error("No handler for key: %s", handler_key)
        await ack(redis_client, stream_name, GROUP_LLM_WORKER, msg_id)
        return

    try:
        # Mark job as processing
        await core_api.update_job(job_id, "processing")

        # Run the handler
        result = await handler.handle(job_id, payload, user_id)

        # Mark job as completed
        await core_api.update_job(
            job_id, "completed", result=result
        )

        # Publish notification if handler returned content
        if result is not None and user_id is not None:
            await publish(redis_client, STREAM_NOTIFY_TELEGRAM, {
                "user_id": user_id,
                "message_type": msg_type,
                "content": result,
            })

        # Acknowledge and clean up
        await ack(redis_client, stream_name, GROUP_LLM_WORKER, msg_id)
        retry_tracker.clear(job_id)

        logger.info("Job %s completed successfully", job_id)

    except Exception as e:
        logger.exception("Job %s failed: %s", job_id, e)

        attempt = retry_tracker.record_attempt(job_id)

        if retry_tracker.should_retry(job_id):
            # Do NOT ack -- Redis will redeliver on next consume
            backoff = retry_tracker.backoff_seconds(job_id)
            logger.warning(
                "Job %s will retry (attempt %d), backing off %.1fs",
                job_id, attempt, backoff,
            )
            await asyncio.sleep(backoff)
        else:
            # Max retries exceeded -- mark failed and notify user
            logger.error("Job %s exceeded max retries, marking failed", job_id)
            await core_api.update_job(
                job_id, "failed", error_message=str(e)
            )

            if user_id is not None:
                memory_id = payload.get("memory_id", "")
                await publish(redis_client, STREAM_NOTIFY_TELEGRAM, {
                    "user_id": user_id,
                    "message_type": "llm_failure",
                    "content": {
                        "job_type": handler_key,
                        "memory_id": memory_id,
                    },
                })

            await ack(redis_client, stream_name, GROUP_LLM_WORKER, msg_id)
            retry_tracker.clear(job_id)
```

---

## Files to Modify

### 2. `llm_worker/worker/main.py`

Replace the current stub with the real entrypoint.

**Current content (to be replaced entirely):**
```python
async def main():
    logger.info("LLM Worker -- not yet implemented (Phase 3)")
    while True:
        await asyncio.sleep(3600)
```

**New content:**
```python
"""LLM Worker service entrypoint."""

import asyncio
import logging
import signal

import aiohttp
import redis.asyncio as aioredis

from worker.config import load_llm_worker_settings
from worker.consumer import run_consumer
from worker.core_api_client import CoreAPIClient
from worker.llm_client import LLMClient
from worker.retry import RetryTracker

from worker.handlers.image_tag import ImageTagHandler
from worker.handlers.intent import IntentHandler
from worker.handlers.followup import FollowupHandler
from worker.handlers.task_match import TaskMatchHandler
from worker.handlers.email_extract import EmailExtractHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Start the LLM Worker consumer."""
    config = load_llm_worker_settings()
    logger.info("LLM Worker starting (base_url=%s)", config.llm_base_url)

    redis_client = aioredis.from_url(config.redis_url)
    session = aiohttp.ClientSession()
    llm_client = LLMClient(
        base_url=config.llm_base_url, api_key=config.llm_api_key
    )
    core_api = CoreAPIClient(config.core_api_url, session)
    retry_tracker = RetryTracker(max_retries=config.llm_max_retries)

    handlers = {
        "image_tag": ImageTagHandler(llm_client, core_api, config),
        "intent_classify": IntentHandler(llm_client, core_api, config),
        "followup": FollowupHandler(llm_client, core_api, config),
        "task_match": TaskMatchHandler(llm_client, core_api, config),
        "email_extract": EmailExtractHandler(llm_client, core_api, config),
    }

    # Graceful shutdown on SIGTERM
    loop = asyncio.get_running_loop()
    consumer_task = asyncio.current_task()

    def _shutdown():
        logger.info("Received shutdown signal")
        if consumer_task:
            consumer_task.cancel()

    loop.add_signal_handler(signal.SIGTERM, _shutdown)
    loop.add_signal_handler(signal.SIGINT, _shutdown)

    try:
        await run_consumer(redis_client, handlers, core_api, retry_tracker)
    except asyncio.CancelledError:
        logger.info("LLM Worker cancelled")
    finally:
        logger.info("LLM Worker shutting down")
        await llm_client.close()
        await session.close()
        await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Test Files to Create

### 3. `tests/test_llm_worker/test_consumer.py`

Integration tests for the consumer loop using `fakeredis`.

**Fixtures needed (from conftest):** `mock_redis`, `mock_llm_client`, `mock_core_api`, `llm_worker_config`

```
Test cases:

- test_consumer_processes_job:
    Setup:
      - Create consumer group on STREAM_LLM_INTENT
      - Publish a message to STREAM_LLM_INTENT: {"job_id": "j-1", "job_type": "intent_classify", "payload": {"query": "test"}, "user_id": 12345}
      - Create handlers dict with a mock IntentHandler that returns {"query": "test", "intent": "memory_search", "results": []}
    Action:
      - Call _process_message() directly (or run one iteration of the consumer)
    Assert:
      - core_api.update_job called with ("j-1", "processing")
      - core_api.update_job called with ("j-1", "completed", result=...)
      - A notification was published to STREAM_NOTIFY_TELEGRAM
      - The notification has user_id=12345, message_type="llm_intent_result"

- test_consumer_handler_returns_none:
    Setup:
      - Mock handler returns None (e.g. TaskMatchHandler found no match)
    Assert:
      - Job still marked completed
      - No notification published to STREAM_NOTIFY_TELEGRAM

- test_consumer_retry_on_failure:
    Setup:
      - Mock handler raises Exception("LLM timeout")
      - RetryTracker with max_retries=3
    Action:
      - Call _process_message()
    Assert:
      - retry_tracker.record_attempt was implicitly called (attempt count = 1)
      - Message was NOT acknowledged (will be redelivered)
      - core_api.update_job was NOT called with "failed"

- test_consumer_max_retries_exceeded:
    Setup:
      - Pre-fill retry_tracker with max_retries worth of attempts for the job
      - Mock handler raises Exception
    Action:
      - Call _process_message()
    Assert:
      - core_api.update_job called with ("j-1", "failed", error_message=...)
      - llm_failure notification published to STREAM_NOTIFY_TELEGRAM
      - Message was acknowledged

- test_consumer_graceful_shutdown:
    Setup:
      - Start run_consumer as an asyncio task
    Action:
      - Cancel the task
    Assert:
      - No exception raised
      - Consumer loop exited cleanly

- test_consumer_unknown_handler:
    Setup:
      - Pass a message with an unknown handler key
    Assert:
      - Message is acknowledged (don't let it block the queue)
      - No crash
```

---

## Checkpoint

After this sub-phase is complete, verify:

1. `pytest tests/test_llm_worker/test_consumer.py` -- all pass
2. `pytest tests/test_llm_worker/` -- all tests from sub-phases 3.1, 3.2, 3.3 pass
3. `pytest tests/test_core/` -- no regressions (core unchanged in this sub-phase)

---

## Code Conventions

- Async throughout: `async def`, `await`
- Type hints on all function signatures
- Max 100 char line length, double quotes, f-strings
- Logger per module: `logger = logging.getLogger(__name__)`
- Imports: stdlib, then third-party, then first-party, alphabetical within groups
