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

    try:
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
        await llm_client.close()
        await session.close()
        await redis_client.close()
        logger.info("LLM Worker shutdown complete")


if __name__ == "__main__":
    asyncio.run(main())
