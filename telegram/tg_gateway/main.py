import logging

import redis.asyncio
from telegram import BotCommand
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    InvalidCallbackData,
    MessageHandler,
    filters,
)

from tg_gateway.config import TelegramConfig
from tg_gateway.core_client import CoreClient
from tg_gateway.filters import AllowedUsersFilter
from tg_gateway.telegram_gateway import TelegramGateway

# Configure logging with INFO level and format string
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Build the PTB Application, register all handlers, and start polling."""
    # Load configuration to get bot token and allowed user IDs
    config = TelegramConfig()
    allowed_ids = config.allowed_ids_set

    # Create the allowed users filter
    allowed_filter = AllowedUsersFilter(allowed_ids)
    # Create the inverse filter for unauthorized users
    unauthorized_filter = ~allowed_filter

    # Build the application
    app = (
        ApplicationBuilder()
        .token(config.telegram_bot_token)
        .arbitrary_callback_data(True)
        .concurrent_updates(False)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # === Handler Registration Order (Priority 1-6) ===

    # Priority 1: Command handlers with allowed_filter
    # Try to import command handlers, handle gracefully if not available
    try:
        from tg_gateway.handlers.command import (
            help_command,
            find_command,
            tasks_command,
            pinned_command,
            cancel_command,
            queue_command,
            status_command,
        )

        command_handlers = [
            CommandHandler("help", help_command, filters=allowed_filter),
            CommandHandler("find", find_command, filters=allowed_filter),
            CommandHandler("tasks", tasks_command, filters=allowed_filter),
            CommandHandler("pinned", pinned_command, filters=allowed_filter),
            CommandHandler("cancel", cancel_command, filters=allowed_filter),
            CommandHandler("queue", queue_command, filters=allowed_filter),
            CommandHandler("status", status_command, filters=allowed_filter),
        ]
        for handler in command_handlers:
            app.add_handler(handler)
        logger.info("Registered command handlers")
    except ImportError:
        logger.warning("Command handlers module not found, skipping command handlers")

    # Priority 2: Text message handler (allowed_filter & filters.TEXT & ~filters.COMMAND)
    try:
        from tg_gateway.handlers.message import text_message_handler

        app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & allowed_filter,
                text_message_handler,
            )
        )
        logger.info("Registered text message handler")
    except ImportError:
        logger.warning(
            "Message handlers module not found, skipping text message handler"
        )

    # Priority 3: Photo message handler (allowed_filter & filters.PHOTO)
    try:
        from tg_gateway.handlers.message import photo_message_handler

        app.add_handler(
            MessageHandler(filters.PHOTO & allowed_filter, photo_message_handler)
        )
        logger.info("Registered photo message handler")
    except ImportError:
        logger.warning(
            "Message handlers module not found, skipping photo message handler"
        )

    # Priority 4: Invalid callback handler (pattern=InvalidCallbackData)
    try:
        from tg_gateway.handlers.callback import invalid_callback_handler

        app.add_handler(
            CallbackQueryHandler(
                invalid_callback_handler,
                pattern=InvalidCallbackData,
            )
        )
        logger.info("Registered invalid callback handler")
    except ImportError:
        logger.warning(
            "Callback handlers module not found, skipping invalid callback handler"
        )

    # Priority 5: General callback handler
    try:
        from tg_gateway.handlers.callback import general_callback_handler

        app.add_handler(CallbackQueryHandler(general_callback_handler))
        logger.info("Registered general callback handler")
    except ImportError:
        logger.warning(
            "Callback handlers module not found, skipping general callback handler"
        )

    # Priority 6: Unauthorized handler (~allowed_filter catch-all)
    # This catches all updates from non-allowed users
    try:
        from tg_gateway.handlers.message import unauthorized_handler

        # Register a MessageHandler for unauthorized users (catches text)
        app.add_handler(MessageHandler(unauthorized_filter, unauthorized_handler))

        # Also register a CallbackQueryHandler for unauthorized callback queries
        # Use a pattern that matches any callback data but filtered by unauthorized_filter
        def unauthorized_callback_pattern(callback_data: object) -> bool:
            """Pattern that matches any callback data for unauthorized users."""
            return True  # We handle the actual filtering in the handler

        app.add_handler(
            CallbackQueryHandler(
                unauthorized_handler,
                pattern=unauthorized_callback_pattern,
            )
        )
        logger.info("Registered unauthorized handler")
    except ImportError:
        logger.warning(
            "Message handlers module not found, skipping unauthorized handler"
        )

    # Start polling with drop_pending_updates=True
    logger.info("Starting Telegram bot polling...")
    app.run_polling(drop_pending_updates=True)


async def post_init(application: Application) -> None:
    """Initialize shared resources after the application starts.

    Args:
        application: The Telegram bot application instance.
    """
    # Load configuration
    config = TelegramConfig()

    # Create shared resources
    core_client = CoreClient(base_url=config.core_api_url)
    redis_client = redis.asyncio.from_url(config.redis_url)
    gateway = TelegramGateway(bot=application.bot)

    # Store in bot_data for access by handlers
    application.bot_data["config"] = config
    application.bot_data["core_client"] = core_client
    application.bot_data["redis"] = redis_client
    application.bot_data["gateway"] = gateway

    # Set up menu commands
    commands = [
        BotCommand("help", "Show this help message"),
        BotCommand("find", "Search memories"),
        BotCommand("tasks", "List your tasks"),
        BotCommand("pinned", "Show pinned memories"),
        BotCommand("cancel", "Cancel current action"),
        BotCommand("queue", "Queue statistics (admin)"),
        BotCommand("status", "Your status and LLM health"),
    ]
    await application.bot.set_my_commands(commands)

    # Start Redis consumer task
    try:
        from tg_gateway.consumer import run_notify_consumer

        application.create_task(run_notify_consumer(application), name="redis_consumer")
    except ImportError:
        logger.warning("Consumer module not found, skipping Redis consumer task")


async def post_shutdown(application: Application) -> None:
    """Clean up shared resources when the application shuts down.

    Args:
        application: The Telegram bot application instance.
    """
    # Get resources from bot_data
    core_client: CoreClient | None = application.bot_data.get("core_client")
    redis_client: redis.asyncio.Redis | None = application.bot_data.get("redis")

    # Close connections
    if core_client is not None:
        await core_client.close()

    if redis_client is not None:
        await redis_client.close()

    logger.info("Telegram Gateway shutdown complete")


if __name__ == "__main__":
    main()
