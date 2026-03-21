import asyncio
import logging

import uvicorn

from bearmemori.api.routes import create_app as create_api
from bearmemori.app import create_application
from bearmemori.config import Settings
from bearmemori.events.domain import InputReceived

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def processing_loop(application) -> None:
    logger.info("Processing loop started")
    while True:
        item = await application.queue_manager.get_next()
        try:
            followup_event = InputReceived(
                input_type=item.input_type,
                content=item.content,
                source_chat_id=item.source_chat_id,
            )
            followup_input = application.followup_manager.check_followup(followup_event)
            if followup_input:
                item.context = followup_input.context

            await application.processor.process_item(item)
        except Exception:
            logger.exception("Error processing item from %s", item.source_chat_id)


async def main() -> None:
    settings = Settings()
    application = create_application(settings)

    api = create_api(application.db)

    telegram_app = application.telegram.build()

    # Start processing loop
    asyncio.create_task(processing_loop(application))
    asyncio.create_task(application.scheduler.run())

    # Start API server
    config = uvicorn.Config(api, host="0.0.0.0", port=8000, log_level="info")
    server = uvicorn.Server(config)

    # Run telegram and API concurrently
    async with telegram_app:
        await telegram_app.start()
        await telegram_app.updater.start_polling()
        logger.info("BearMemori is running")

        await server.serve()

        await telegram_app.updater.stop()
        await telegram_app.stop()


if __name__ == "__main__":
    asyncio.run(main())
