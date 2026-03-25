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
async def test_handle_memory_pending_sends_photo_when_image_present(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    event = MemoryPending(
        pending_id="pend_img123",
        preview_data={
            "title": "Photo memory",
            "category": "general",
            "content": "A nice sunset",
            "tags": ["photo"],
        },
        source_chat_id="42",
        image_bytes=b"fake-jpeg-data",
    )

    await interface.handle_memory_pending(event)

    mock_bot.send_photo.assert_called_once()
    call_kwargs = mock_bot.send_photo.call_args.kwargs
    assert call_kwargs["chat_id"] == 42
    assert "Photo memory" in call_kwargs["caption"]
    assert call_kwargs["reply_markup"] is not None
    mock_bot.send_message.assert_not_called()


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


@pytest.mark.asyncio
async def test_callback_review_emits_confirmed_with_needs_review(interface, bus):
    confirmed = []
    bus.on(MemoryConfirmed, lambda e: confirmed.append(e))

    interface._app = MagicMock()
    interface._app.bot = AsyncMock()
    interface._pending_chat_ids = {"pend_abc123": "42"}

    query = AsyncMock()
    query.data = "review:pend_abc123"
    query.message = AsyncMock()

    update = _make_update()
    update.callback_query = query

    await interface._handle_callback(update, MagicMock())

    assert len(confirmed) == 1
    assert confirmed[0].pending_id == "pend_abc123"
    assert confirmed[0].needs_review is True
    query.answer.assert_called_once_with("Saved for review")


@pytest.mark.asyncio
async def test_callback_review_removes_buttons_and_updates_text(interface, bus):
    confirmed = []
    bus.on(MemoryConfirmed, lambda e: confirmed.append(e))

    interface._app = MagicMock()
    interface._app.bot = AsyncMock()
    interface._pending_chat_ids = {"pend_abc123": "42"}

    query = AsyncMock()
    query.data = "review:pend_abc123"
    query.message = AsyncMock()
    query.message.text = "Memory Preview\n\nTitle: Test\nCategory: reminder\nContent: Test content"

    update = _make_update()
    update.callback_query = query

    await interface._handle_callback(update, MagicMock())

    assert len(confirmed) == 1
    assert confirmed[0].needs_review is True
    query.message.edit_text.assert_called_once()
    call_args = query.message.edit_text.call_args
    assert "Saved for review" in call_args[0][0]


@pytest.mark.asyncio
async def test_recall_sends_memory_details(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from datetime import UTC, datetime
    from unittest.mock import MagicMock as SyncMock

    from bearmemori.storage.models import MemoryCategory, MemoryRecord

    mock_db = SyncMock()
    interface._db = mock_db

    record = MemoryRecord(
        id="mem_abc123",
        category=MemoryCategory.GENERAL,
        title="Pizza preference",
        content="I like pepperoni pizza",
        created_at=datetime.now(UTC),
        tags=["food"],
    )
    mock_db.get.return_value = record

    update = _make_update()
    context = MagicMock()
    context.args = ["mem_abc123"]

    await interface._handle_recall(update, context)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "Pizza preference" in call_kwargs["text"]
    assert "pepperoni" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_recall_sends_photo_when_image_exists(interface, tmp_path):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from datetime import UTC, datetime
    from unittest.mock import MagicMock as SyncMock

    from bearmemori.storage.models import MemoryCategory, MemoryRecord

    mock_db = SyncMock()
    interface._db = mock_db
    interface._image_storage_dir = str(tmp_path)

    (tmp_path / "mem_img456.jpg").write_bytes(b"fake-photo")

    record = MemoryRecord(
        id="mem_img456",
        category=MemoryCategory.GENERAL,
        title="Sunset photo",
        content="Beautiful sunset at the beach",
        created_at=datetime.now(UTC),
        tags=["photo"],
        image_path="images/mem_img456.jpg",
    )
    mock_db.get.return_value = record

    update = _make_update()
    context = MagicMock()
    context.args = ["mem_img456"]

    await interface._handle_recall(update, context)

    mock_bot.send_photo.assert_called_once()
    call_kwargs = mock_bot.send_photo.call_args.kwargs
    assert "Sunset photo" in call_kwargs["caption"]


@pytest.mark.asyncio
async def test_recall_not_found(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from unittest.mock import MagicMock as SyncMock

    mock_db = SyncMock()
    interface._db = mock_db
    mock_db.get.return_value = None

    update = _make_update()
    context = MagicMock()
    context.args = ["mem_nonexistent"]

    await interface._handle_recall(update, context)

    mock_bot.send_message.assert_called_once()
    assert "not found" in mock_bot.send_message.call_args.kwargs["text"].lower()
