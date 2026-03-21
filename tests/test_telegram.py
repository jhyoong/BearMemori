from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import InputReceived, SendMessage
from bearmemori.interfaces.telegram import TelegramInterface


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def interface(bus):
    return TelegramInterface(bus=bus, token="fake-token")


@pytest.mark.asyncio
async def test_handle_text_emits_input_received(interface, bus):
    received = []
    bus.on(InputReceived, lambda e: received.append(e))

    update = MagicMock()
    update.effective_chat.id = 12345
    update.message.text = "I like pizza"
    context = MagicMock()

    await interface._handle_text(update, context)

    assert len(received) == 1
    assert received[0].content == "I like pizza"
    assert received[0].input_type == "text"
    assert received[0].source_chat_id == "12345"


@pytest.mark.asyncio
async def test_handle_send_message(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    event = SendMessage(chat_id="12345", text="Hello back")
    await interface.handle_send_message(event)

    mock_bot.send_message.assert_called_once_with(chat_id=12345, text="Hello back")
