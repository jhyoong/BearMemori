from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.events.bus import EventBus
from bearmemori.events.domain import (
    InputReceived,
    MemoryConfirmed,
    MemoryDiscarded,
    MemoryPending,
    ReminderDue,
    SendMessage,
)
from bearmemori.interfaces.telegram import TelegramInterface

ALLOWED_USER_ID = 12345


@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def interface(bus):
    return TelegramInterface(bus=bus, token="fake-token", allowed_user_id=ALLOWED_USER_ID)


def _make_update(user_id=ALLOWED_USER_ID):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = 12345
    return update


@pytest.mark.asyncio
async def test_handle_text_emits_input_received(interface, bus):
    received = []
    bus.on(InputReceived, lambda e: received.append(e))

    update = _make_update()
    update.message.text = "I like pizza"
    context = MagicMock()

    await interface._handle_text(update, context)

    assert len(received) == 1
    assert received[0].content == "I like pizza"
    assert received[0].input_type == "text"
    assert received[0].source_chat_id == "12345"


@pytest.mark.asyncio
async def test_handle_text_ignores_unauthorized_user(interface, bus):
    received = []
    bus.on(InputReceived, lambda e: received.append(e))

    update = _make_update(user_id=99999)
    update.message.text = "I like pizza"
    context = MagicMock()

    await interface._handle_text(update, context)

    assert len(received) == 0


@pytest.mark.asyncio
async def test_handle_photo_ignores_unauthorized_user(interface, bus):
    received = []
    bus.on(InputReceived, lambda e: received.append(e))

    update = _make_update(user_id=99999)
    context = MagicMock()

    await interface._handle_photo(update, context)

    assert len(received) == 0


@pytest.mark.asyncio
async def test_handle_send_message(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    event = SendMessage(chat_id="12345", text="Hello back")
    await interface.handle_send_message(event)

    mock_bot.send_message.assert_called_once_with(chat_id=12345, text="Hello back")


@pytest.mark.asyncio
async def test_handle_reminder_due(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    event = ReminderDue(
        memory_id="rem-1",
        content="Take meds",
        source_chat_id="42",
        remind_at_iso="2026-03-21T20:00:00",
    )
    await interface.handle_reminder_due(event)

    mock_bot.send_message.assert_called_once_with(
        chat_id=42,
        text="Reminder: Take meds",
    )


@pytest.mark.asyncio
async def test_handle_memory_pending_sends_preview(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    event = MemoryPending(
        pending_id="pend_abc123",
        preview_data={
            "title": "Dentist appointment",
            "category": "reminder",
            "content": "Dentist on Tuesday",
            "tags": ["health"],
        },
        source_chat_id="42",
    )

    await interface.handle_memory_pending(event)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == 42
    assert "Dentist appointment" in call_kwargs["text"]
    assert call_kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_callback_save_emits_confirmed(interface, bus):
    confirmed = []
    bus.on(MemoryConfirmed, lambda e: confirmed.append(e))

    interface._app = MagicMock()
    interface._app.bot = AsyncMock()
    interface._pending_chat_ids = {"pend_abc123": "42"}

    query = AsyncMock()
    query.data = "save:pend_abc123"
    query.message = AsyncMock()

    update = _make_update()
    update.callback_query = query

    await interface._handle_callback(update, MagicMock())

    assert len(confirmed) == 1
    assert confirmed[0].pending_id == "pend_abc123"
    query.answer.assert_called_once_with("Saved")


@pytest.mark.asyncio
async def test_callback_discard_emits_discarded(interface, bus):
    discarded = []
    bus.on(MemoryDiscarded, lambda e: discarded.append(e))

    interface._app = MagicMock()
    interface._app.bot = AsyncMock()
    interface._pending_chat_ids = {"pend_abc123": "42"}

    query = AsyncMock()
    query.data = "discard:pend_abc123"
    query.message = AsyncMock()

    update = _make_update()
    update.callback_query = query

    await interface._handle_callback(update, MagicMock())

    assert len(discarded) == 1
    assert discarded[0].pending_id == "pend_abc123"
    query.answer.assert_called_once_with("Discarded")


@pytest.mark.asyncio
async def test_callback_edit_sets_edit_pending(interface):
    interface._app = MagicMock()
    interface._app.bot = AsyncMock()
    interface._pending_chat_ids = {"pend_abc123": "42"}

    query = AsyncMock()
    query.data = "edit:pend_abc123"
    query.message = AsyncMock()

    update = _make_update()
    update.callback_query = query

    await interface._handle_callback(update, MagicMock())

    assert interface._edit_pending["42"] == "pend_abc123"
    query.answer.assert_called_once_with()


@pytest.mark.asyncio
async def test_edit_text_routes_to_pending(interface, bus):
    received = []
    bus.on(InputReceived, lambda e: received.append(e))

    interface._edit_pending["12345"] = "pend_abc123"

    update = _make_update()
    update.message.text = "Actually it's Wednesday"
    context = MagicMock()

    await interface._handle_text(update, context)

    assert len(received) == 1
    assert received[0].context == {"edit_pending_id": "pend_abc123"}
    assert "12345" not in interface._edit_pending
