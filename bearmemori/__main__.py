import asyncio
import logging
from typing import cast

import uvicorn

from bearmemori.app import Application, create_application
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


async def run_server(
    port: int | None = None,
    host: str = "0.0.0.0",
    no_telegram: bool = False,
) -> None:
    settings = Settings()
    actual_port = port if port is not None else settings.api_port
    api = create_application(settings)
    application = cast(Application, api.state.application)

    asyncio.create_task(processing_loop(application))
    asyncio.create_task(application.cleanup_task.run())

    # Skip reminder scheduler in API-only mode (NanoClaw handles scheduling)
    if not settings.api_only_mode:
        asyncio.create_task(application.scheduler.run())

    config = uvicorn.Config(api, host=host, port=actual_port, log_level="info")
    server = uvicorn.Server(config)

    # Skip Telegram bot in API-only mode or when explicitly disabled
    if no_telegram or settings.api_only_mode:
        mode = "API-only" if settings.api_only_mode else "Telegram disabled"
        logger.info("BearMemori is running on %s:%d (%s)", host, actual_port, mode)
        await server.serve()
    else:
        assert application.telegram is not None
        telegram_app = application.telegram.build()
        async with telegram_app:
            if telegram_app.post_init:
                await telegram_app.post_init(telegram_app)
            await telegram_app.start()
            await telegram_app.updater.start_polling()
            logger.info("BearMemori is running on %s:%d", host, actual_port)

            try:
                await server.serve()
            finally:
                await telegram_app.updater.stop()
                await telegram_app.stop()


async def main() -> None:
    await run_server()


if __name__ == "__main__":
    asyncio.run(main())
