import logging
from pathlib import Path

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
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
from bearmemori.storage.database import MemoryDatabase

logger = logging.getLogger(__name__)


class TelegramInterface:
    def __init__(
        self,
        bus: EventBus,
        token: str,
        allowed_user_id: int,
        db: MemoryDatabase | None = None,
        image_storage_dir: str = "",
    ) -> None:
        self._bus = bus
        self._token = token
        self._allowed_user_id = allowed_user_id
        self._app: Application | None = None
        self._pending_chat_ids: dict[str, str] = {}  # pending_id -> chat_id
        self._edit_pending: dict[str, str] = {}  # chat_id -> pending_id
        self._db = db
        self._image_storage_dir = image_storage_dir

    def _is_authorized(self, update: Update) -> bool:
        return update.effective_user.id == self._allowed_user_id

    def build(self) -> Application:
        async def post_init(application: Application) -> None:
            await application.bot.set_my_commands(
                [
                    BotCommand("start", "Welcome message"),
                    BotCommand("recall", "Retrieve a memory by ID"),
                ]
            )

        self._app = Application.builder().token(self._token).post_init(post_init).build()
        self._app.add_handler(CallbackQueryHandler(self._handle_callback))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text))
        self._app.add_handler(MessageHandler(filters.PHOTO, self._handle_photo))
        self._app.add_handler(CommandHandler("start", self._handle_start))
        self._app.add_handler(CommandHandler("recall", self._handle_recall))
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

    @staticmethod
    async def _update_callback_message(query, suffix: str) -> None:
        """Update a callback message, handling both text and photo messages."""
        if query.message.photo:
            await query.message.edit_caption(caption=(query.message.caption or "") + suffix)
        else:
            await query.message.edit_text(query.message.text + suffix)

    async def _handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return

        query = update.callback_query
        data = query.data
        action, pending_id = data.split(":", 1)
        chat_id = self._pending_chat_ids.get(pending_id, str(update.effective_chat.id))

        if action == "save":
            await self._bus.emit(MemoryConfirmed(pending_id=pending_id, source_chat_id=chat_id))
            await self._update_callback_message(query, "\n\nSaved.")
            await query.answer("Saved")
        elif action == "edit":
            self._edit_pending[chat_id] = pending_id
            await self._update_callback_message(query, "\n\nSend your corrections.")
            await query.answer()
        elif action == "discard":
            await self._bus.emit(MemoryDiscarded(pending_id=pending_id, source_chat_id=chat_id))
            await self._update_callback_message(query, "\n\nDiscarded.")
            await query.answer("Discarded")
        elif action == "review":
            await self._bus.emit(
                MemoryConfirmed(
                    pending_id=pending_id,
                    source_chat_id=chat_id,
                    needs_review=True,
                )
            )
            await self._update_callback_message(query, "\n\nSaved for review.")
            await query.answer("Saved for review")

        self._pending_chat_ids.pop(pending_id, None)

    async def _handle_recall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_authorized(update):
            return

        chat_id = str(update.effective_chat.id)

        if not context.args:
            await self._app.bot.send_message(
                chat_id=int(chat_id),
                text="Usage: /recall <memory_id>",
            )
            return

        memory_id = context.args[0]

        if not self._db:
            await self._app.bot.send_message(
                chat_id=int(chat_id),
                text="Database not available.",
            )
            return

        record = self._db.get(memory_id)
        if record is None:
            await self._app.bot.send_message(
                chat_id=int(chat_id),
                text=f"Memory {memory_id} not found.",
            )
            return

        tags_str = ", ".join(record.tags) if record.tags else ""
        text = f"Title: {record.title}\nCategory: {record.category.value}\n"
        if tags_str:
            text += f"Tags: {tags_str}\n"
        text += f"Content: {record.content}"

        # Send photo if image exists
        if record.image_path and self._image_storage_dir:
            image_file = Path(self._image_storage_dir) / record.image_path
            if image_file.exists():
                await self._app.bot.send_photo(
                    chat_id=int(chat_id),
                    photo=image_file.read_bytes(),
                    caption=text,
                )
                return

        await self._app.bot.send_message(
            chat_id=int(chat_id),
            text=text,
        )

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

        if event.image_bytes:
            await self._app.bot.send_photo(
                chat_id=int(event.source_chat_id),
                photo=event.image_bytes,
                caption=text,
                reply_markup=keyboard,
            )
        else:
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
        if not self._app or not event.source_chat_id:
            if not event.source_chat_id:
                logger.warning(
                    "Reminder %s has no source_chat_id, cannot deliver", event.memory_id
                )
            return
        await self._app.bot.send_message(
            chat_id=int(event.source_chat_id),
            text=f"Reminder: {event.content}",
        )
