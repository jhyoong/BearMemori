"""Abstract base interface for the assistant."""

from abc import ABC, abstractmethod


class BaseInterface(ABC):
    """Abstract chat interface. Subclass for Telegram, web, etc."""

    @abstractmethod
    async def send_message(self, user_id: int, text: str) -> None:
        """Send a message to the user."""

    @abstractmethod
    async def start(self) -> None:
        """Start listening for messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening and clean up."""
