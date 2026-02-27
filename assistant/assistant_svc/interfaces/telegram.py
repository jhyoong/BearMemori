"""Telegram interface for the assistant bot."""

import logging
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

from assistant_svc.interfaces.base import BaseInterface

logger = logging.getLogger(__name__)


class TelegramInterface(BaseInterface):
    """Telegram bot interface using python-telegram-bot."""

    def __init__(self, agent, bot_token: str, allowed_user_ids: set[int]):
        self._agent = agent
        self._bot_token = bot_token
        self._allowed_user_ids = allowed_user_ids
        self._app: Application | None = None

    async def send_message(self, user_id: int, text: str) -> None:
        """Send a message to a Telegram user."""
        if self._app and self._app.bot:
            await self._app.bot.send_message(chat_id=user_id, text=text)

    async def start(self) -> None:
        """Build the Telegram application and start polling."""
        self._app = (
            ApplicationBuilder()
            .token(self._bot_token)
            .build()
        )

        # Register message handler
        self._app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND,
                self._handle_message,
            )
        )

        logger.info("Starting assistant Telegram bot")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        if self._app:
            logger.info("Stopping assistant Telegram bot")
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle an incoming Telegram message."""
        if not update.effective_user or not update.message or not update.message.text:
            return

        user_id = update.effective_user.id
        if user_id not in self._allowed_user_ids:
            logger.warning("Unauthorized user %d attempted to use assistant", user_id)
            return

        text = update.message.text
        logger.info("Received message from user %d", user_id)

        try:
            reply = await self._agent.handle_message(user_id=user_id, text=text)
            await update.message.reply_text(reply)
        except Exception:
            logger.exception("Failed to handle message from user %d", user_id)
            await update.message.reply_text(
                "Sorry, something went wrong. Please try again."
            )
