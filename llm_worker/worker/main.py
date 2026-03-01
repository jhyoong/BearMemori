"""LLM Worker main entrypoint."""

import asyncio
import logging
import signal

import aiohttp
import redis.asyncio as aioredis

from worker.config import load_llm_worker_settings
from worker.consumer import run_consumer
from worker.core_api_client import CoreAPIClient
from worker.llm_client import LLMClient
from worker.retry import RetryManager

from worker.handlers.image_tag import ImageTagHandler
from worker.handlers.intent import IntentHandler
from worker.handlers.followup import FollowupHandler
from worker.handlers.task_match import TaskMatchHandler
from worker.handlers.email_extract import EmailExtractHandler

from worker.health_check import LLMHealthChecker, run_health_check

from shared_lib.redis_streams import publish, STREAM_NOTIFY_TELEGRAM

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Main entrypoint for the LLM Worker service."""
    # Load configuration
    config = load_llm_worker_settings()
    logger.info(f"Starting LLM Worker with config: {config}")

    # Initialize clients
    redis_client = aioredis.from_url(config.redis_url)
    session = aiohttp.ClientSession()
    llm_client = LLMClient(base_url=config.llm_base_url, api_key=config.llm_api_key)
    core_api = CoreAPIClient(config.core_api_url, session)
    retry_tracker = RetryManager()

    # Create handlers
    handlers = {
        "image_tag": ImageTagHandler(llm_client, core_api, config),
        "intent_classify": IntentHandler(llm_client, core_api, config),
        "followup": FollowupHandler(llm_client, core_api, config),
        "task_match": TaskMatchHandler(llm_client, core_api, config),
        "email_extract": EmailExtractHandler(llm_client, core_api, config),
    }

    # Graceful shutdown handling
    shutdown_event = asyncio.Event()

    def handle_signal(signum):
        logger.info(f"Received signal {signum}, initiating shutdown...")
        shutdown_event.set()

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda s=sig: handle_signal(s))

    async def on_health_status_change(
        new_status: str, previous_status: str
    ) -> None:
        """Publish health status change notification to Telegram stream."""
        logger.info(
            "Publishing health change notification: %s -> %s",
            previous_status,
            new_status,
        )
        await publish(
            redis_client,
            STREAM_NOTIFY_TELEGRAM,
            {
                "user_id": 0,
                "message_type": "llm_health_change",
                "content": {
                    "new_status": new_status,
                    "previous_status": previous_status,
                },
            },
        )

    try:
        # Start the health check background task
        health_checker = LLMHealthChecker(config)
        health_check_task = asyncio.create_task(
            run_health_check(
                redis_client,
                health_checker,
                shutdown_event,
                interval=30,
                on_status_change=on_health_status_change,
            )
        )

        # Run the consumer
        await run_consumer(
            redis_client=redis_client,
            handlers=handlers,
            core_api=core_api,
            retry_tracker=retry_tracker,
            config=config,
        )
    except asyncio.CancelledError:
        logger.info("LLM Worker cancelled")
    finally:
        # Cleanup
        logger.info("Cleaning up LLM Worker resources...")
        # Cancel health check task
        health_check_task.cancel()
        try:
            await health_check_task
        except asyncio.CancelledError:
            pass
        await llm_client.close()
        await session.close()
        await redis_client.close()
        logger.info("LLM Worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
