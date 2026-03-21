import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import InputReceived, ReminderDue, SendMessage

logger = logging.getLogger(__name__)


class TelegramInterface:
    def __init__(self, bus: EventBus, token: str, allowed_user_id: int) -> None:
        self._bus = bus
        self._token = token
        self._allowed_user_id = allowed_user_id
        self._app: Application | None = None

    def _is_authorized(self, update: Update) -> bool:
        return update.effective_user.id == self._allowed_user_id

    def build(self) -> Application:
        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self._app.add_handler(CommandHandler("start", self._handle_start))
        return self._app

    async def _handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            logger.warning("Unauthorized text message from user %s", update.effective_user.id)
            return

        chat_id = str(update.effective_chat.id)
        text = update.message.text
        logger.info("Received text from %s: %s", chat_id, text[:80])

        await self._bus.emit(
            InputReceived(input_type="text", content=text, source_chat_id=chat_id)
        )

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            logger.warning("Unauthorized photo message from user %s", update.effective_user.id)
            return

        chat_id = str(update.effective_chat.id)
        photo = update.message.photo[-1]  # highest resolution
        file = await context.bot.get_file(photo.file_id)
        caption = update.message.caption or ""

        logger.info("Received photo from %s", chat_id)

        await self._bus.emit(
            InputReceived(
                input_type="image",
                content={"file_path": file.file_path, "caption": caption},
                source_chat_id=chat_id,
            )
        )

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            logger.warning("Unauthorized /start command from user %s", update.effective_user.id)
            return

        await update.message.reply_text(
            "Welcome to BearMemori. Send me text or images and I will remember them for you."
        )

    async def handle_send_message(self, event: SendMessage) -> None:
        if self._app:
            await self._app.bot.send_message(chat_id=int(event.chat_id), text=event.text)

    async def handle_reminder_due(self, event: ReminderDue) -> None:
        if self._app:
            await self._app.bot.send_message(
                chat_id=int(event.source_chat_id),
                text=f"Reminder: {event.content}",
            )
