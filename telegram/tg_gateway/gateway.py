from abc import ABC, abstractmethod
from typing import Any


class Gateway(ABC):
    """Abstract base class for Telegram gateway implementations."""

    @abstractmethod
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
        ...

    @abstractmethod
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
        ...

    @abstractmethod
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
        ...

    @abstractmethod
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
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    async def delete_message(self, chat_id: int, message_id: int) -> None:
        """Delete a message.

        Args:
            chat_id: The chat ID of the message.
            message_id: The message ID to delete.
        """
        ...
