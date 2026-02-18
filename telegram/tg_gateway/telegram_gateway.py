from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from tg_gateway.gateway import Gateway
from typing import Any


class TelegramGateway(Gateway):
    """Telegram implementation of the Gateway abstract class."""

    def __init__(self, bot: Bot) -> None:
        """Initialize the Telegram gateway with a bot instance.

        Args:
            bot: The Telegram Bot instance to use for sending messages.
        """
        self._bot = bot

    async def send_text(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> int:
        """Send a plain text message.

        Args:
            chat_id: The target chat ID.
            text: The message text.
            reply_to_message_id: Optional message ID to reply to.

        Returns:
            The sent message ID.
        """
        return (
            await self._bot.send_message(
                chat_id, text, reply_to_message_id=reply_to_message_id
            )
        ).message_id

    async def send_image(
        self,
        chat_id: int,
        image: str | bytes,
        caption: str | None = None,
    ) -> int:
        """Send an image.

        Args:
            chat_id: The target chat ID.
            image: Image file_id string or raw bytes.
            caption: Optional caption for the image.

        Returns:
            The sent message ID.
        """
        return (
            await self._bot.send_photo(chat_id, photo=image, caption=caption)
        ).message_id

    async def send_inline_keyboard(
        self,
        chat_id: int,
        text: str,
        buttons: list[list[dict[str, Any]]],
        reply_to_message_id: int | None = None,
    ) -> int:
        """Send a message with inline keyboard.

        Args:
            chat_id: The target chat ID.
            text: The message text.
            buttons: List of rows; each row is list of dicts with 'text' and 'callback_data' keys.
            reply_to_message_id: Optional message ID to reply to.

        Returns:
            The sent message ID.
        """
        markup = self._build_markup(buttons)
        return (
            await self._bot.send_message(
                chat_id,
                text,
                reply_markup=markup,
                reply_to_message_id=reply_to_message_id,
            )
        ).message_id

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        buttons: list[list[dict[str, Any]]] | None = None,
    ) -> None:
        """Edit an existing message's text and optionally replace its inline keyboard.

        Args:
            chat_id: The chat ID of the message.
            message_id: The message ID to edit.
            text: The new text.
            buttons: Optional new inline keyboard.
        """
        markup = self._build_markup(buttons) if buttons else None
        await self._bot.edit_message_text(
            text, chat_id, message_id, reply_markup=markup
        )

    async def answer_callback(
        self,
        callback_query_id: str,
        text: str | None = None,
    ) -> None:
        """Acknowledge a callback query.

        Args:
            callback_query_id: The callback query ID.
            text: Optional text to show in a toast.
        """
        await self._bot.answer_callback_query(callback_query_id, text=text)

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Delete a message.

        Args:
            chat_id: The chat ID of the message.
            message_id: The message ID to delete.
        """
        await self._bot.delete_message(chat_id, message_id)

    @staticmethod
    def _build_markup(
        buttons: list[list[dict[str, Any]]],
    ) -> InlineKeyboardMarkup:
        """Convert button dictionaries to InlineKeyboardMarkup.

        Args:
            buttons: List of rows; each row is list of dicts with 'text' and 'callback_data' keys.

        Returns:
            An InlineKeyboardMarkup object for Telegram.
        """
        keyboard = []
        for row in buttons:
            keyboard_row = []
            for btn in row:
                keyboard_row.append(
                    InlineKeyboardButton(
                        text=btn["text"], callback_data=btn["callback_data"]
                    )
                )
            keyboard.append(keyboard_row)
        return InlineKeyboardMarkup(keyboard=keyboard)
