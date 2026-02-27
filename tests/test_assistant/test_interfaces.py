"""Tests for the interface layer."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from assistant_svc.interfaces.base import BaseInterface


class TestBaseInterface:
    def test_cannot_instantiate_directly(self):
        """BaseInterface cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseInterface()

    def test_requires_send_message(self):
        """Subclass must implement send_message."""
        class Incomplete(BaseInterface):
            async def start(self):
                pass
            async def stop(self):
                pass
        with pytest.raises(TypeError):
            Incomplete()

    def test_requires_start(self):
        """Subclass must implement start."""
        class Incomplete(BaseInterface):
            async def send_message(self, user_id, text):
                pass
            async def stop(self):
                pass
        with pytest.raises(TypeError):
            Incomplete()

    def test_requires_stop(self):
        """Subclass must implement stop."""
        class Incomplete(BaseInterface):
            async def send_message(self, user_id, text):
                pass
            async def start(self):
                pass
        with pytest.raises(TypeError):
            Incomplete()

    def test_complete_subclass_works(self):
        """A complete subclass can be instantiated."""
        class Complete(BaseInterface):
            async def send_message(self, user_id: int, text: str) -> None:
                pass
            async def start(self) -> None:
                pass
            async def stop(self) -> None:
                pass
        instance = Complete()
        assert instance is not None


class TestTelegramInterface:
    def test_instantiation(self):
        """TelegramInterface can be created with required args."""
        from assistant_svc.interfaces.telegram import TelegramInterface
        agent = AsyncMock()
        interface = TelegramInterface(
            agent=agent,
            bot_token="test-token",
            allowed_user_ids={1, 2},
        )
        assert interface._allowed_user_ids == {1, 2}

    @pytest.mark.asyncio
    async def test_handle_message_allowed_user(self):
        """Allowed user's message is processed by the agent."""
        from assistant_svc.interfaces.telegram import TelegramInterface
        agent = AsyncMock()
        agent.handle_message.return_value = "Hello back!"

        interface = TelegramInterface(
            agent=agent,
            bot_token="test-token",
            allowed_user_ids={42},
        )

        update = MagicMock()
        update.effective_user.id = 42
        update.message.text = "Hello"
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        await interface._handle_message(update, context)
        agent.handle_message.assert_called_once_with(user_id=42, text="Hello")
        update.message.reply_text.assert_called_once_with("Hello back!")

    @pytest.mark.asyncio
    async def test_handle_message_unauthorized_user(self):
        """Unauthorized user's message is ignored."""
        from assistant_svc.interfaces.telegram import TelegramInterface
        agent = AsyncMock()

        interface = TelegramInterface(
            agent=agent,
            bot_token="test-token",
            allowed_user_ids={42},
        )

        update = MagicMock()
        update.effective_user.id = 999
        update.message.text = "Hello"
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        await interface._handle_message(update, context)
        agent.handle_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_error(self):
        """Agent errors result in a friendly error message."""
        from assistant_svc.interfaces.telegram import TelegramInterface
        agent = AsyncMock()
        agent.handle_message.side_effect = Exception("LLM failed")

        interface = TelegramInterface(
            agent=agent,
            bot_token="test-token",
            allowed_user_ids={42},
        )

        update = MagicMock()
        update.effective_user.id = 42
        update.message.text = "Hello"
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        await interface._handle_message(update, context)
        update.message.reply_text.assert_called_once_with(
            "Sorry, something went wrong. Please try again."
        )
