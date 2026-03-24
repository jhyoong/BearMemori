import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import (
    InputReceived,
    MemoryConfirmed,
    MemoryDiscarded,
    MemoryPending,
    ReminderDue,
    SendMessage,
)

logger = logging.getLogger(__name__)


class TelegramInterface:
    def __init__(self, bus: EventBus, token: str, allowed_user_id: int) -> None:
        self._bus = bus
        self._token = token
        self._allowed_user_id = allowed_user_id
        self._app: Application | None = None
        self._pending_chat_ids: dict[str, str] = {}  # pending_id -> chat_id
        self._edit_pending: dict[str, str] = {}  # chat_id -> pending_id

    def _is_authorized(self, update: Update) -> bool:
        return update.effective_user.id == self._allowed_user_id

    def build(self) -> Application:
        self._app = Application.builder().token(self._token).build()
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))
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

        # Check if this is an edit response for a pending memory
        if chat_id in self._edit_pending:
            pending_id = self._edit_pending.pop(chat_id)
            await self._bus.emit(
                InputReceived(
                    input_type="text",
                    content=text,
                    source_chat_id=chat_id,
                    context={"edit_pending_id": pending_id},
                )
            )
            return

        logger.info("Received text from %s: %s", chat_id, text[:80])
        await self._bus.emit(InputReceived(input_type="text", content=text, source_chat_id=chat_id))

    async def _handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            logger.warning("Unauthorized photo message from user %s", update.effective_user.id)
            return

        chat_id = str(update.effective_chat.id)
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        caption = update.message.caption or ""

        logger.info("Received photo from %s", chat_id)

        await self._bus.emit(
            InputReceived(
                input_type="image",
                content={
                    "image_bytes": bytes(file_bytes),
                    "caption": caption,
                    "file_path": file.file_path,
                },
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

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return

        query = update.callback_query
        data = query.data
        action, pending_id = data.split(":", 1)
        chat_id = self._pending_chat_ids.get(pending_id, str(update.effective_chat.id))

        if action == "save":
            await self._bus.emit(MemoryConfirmed(pending_id=pending_id, source_chat_id=chat_id))
            await query.message.edit_text(query.message.text + "\n\nSaved.")
            await query.answer("Saved")
        elif action == "edit":
            self._edit_pending[chat_id] = pending_id
            await query.message.edit_text(query.message.text + "\n\nSend your corrections.")
            await query.answer()
        elif action == "discard":
            await self._bus.emit(MemoryDiscarded(pending_id=pending_id, source_chat_id=chat_id))
            await query.message.edit_text(query.message.text + "\n\nDiscarded.")
            await query.answer("Discarded")
        elif action == "review":
            await self._bus.emit(
                MemoryConfirmed(
                    pending_id=pending_id,
                    source_chat_id=chat_id,
                    needs_review=True,
                )
            )
            await query.message.edit_text(query.message.text + "\n\nSaved for review.")
            await query.answer("Saved for review")

        self._pending_chat_ids.pop(pending_id, None)

    async def handle_memory_pending(self, event: MemoryPending) -> None:
        if not self._app:
            return

        preview = event.preview_data
        tags_str = ", ".join(preview.get("tags", []))
        text = f"Memory Preview\n\nTitle: {preview['title']}\nCategory: {preview['category']}\n"
        if tags_str:
            text += f"Tags: {tags_str}\n"
        text += f"Content: {preview['content']}"

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Save", callback_data=f"save:{event.pending_id}"),
                    InlineKeyboardButton(
                        "Review Later", callback_data=f"review:{event.pending_id}"
                    ),
                ],
                [
                    InlineKeyboardButton("Edit", callback_data=f"edit:{event.pending_id}"),
                    InlineKeyboardButton("Discard", callback_data=f"discard:{event.pending_id}"),
                ],
            ]
        )

        await self._app.bot.send_message(
            chat_id=int(event.source_chat_id),
            text=text,
            reply_markup=keyboard,
        )
        self._pending_chat_ids[event.pending_id] = event.source_chat_id

    async def handle_send_message(self, event: SendMessage) -> None:
        if self._app:
            await self._app.bot.send_message(chat_id=int(event.chat_id), text=event.text)

    async def handle_reminder_due(self, event: ReminderDue) -> None:
        if self._app:
            await self._app.bot.send_message(
                chat_id=int(event.source_chat_id),
                text=f"Reminder: {event.content}",
            )
