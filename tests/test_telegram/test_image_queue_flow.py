"""Integration test for the full image queue flow."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from telegram.ext import ContextTypes

from shared_lib.schemas import DequeueResponse, QueueItem


def _make_mock_context() -> MagicMock:
    """Create a minimal mock context with a mock core_client in bot_data."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {}
    mock_core_client = MagicMock()
    mock_core_client.update_conversation_state = AsyncMock()
    context.bot_data = {"core_client": mock_core_client}
    return context


@pytest.mark.asyncio
async def test_image_queued_then_processed_after_conversation_ends():
    """Full flow: text conversation active -> image queued -> text completes -> image dequeued and processed."""
    from tg_gateway.handlers.message import handle_image
    from tg_gateway.handlers.callback import _clear_conversation_state

    mock_context = _make_mock_context()
    core_client = mock_context.bot_data["core_client"]

    # -- Phase 1: Image arrives while text conversation is active --
    core_client.ensure_user = AsyncMock()
    memory_stub = MagicMock()
    memory_stub.id = "mem-img"
    core_client.create_memory = AsyncMock(return_value=memory_stub)
    core_client.get_active_conversation = AsyncMock(
        return_value=type("C", (), {"state": "processing"})(),
    )
    core_client.enqueue_message = AsyncMock()
    core_client.get_queue_status = AsyncMock(
        return_value=type("S", (), {"queue_length": 1})(),
    )

    mock_update = MagicMock()
    mock_update.message.from_user.id = 12345
    mock_update.message.from_user.full_name = "Test User"
    mock_update.message.photo = [type("P", (), {"file_id": "photo-123"})()]
    mock_update.message.caption = "My sunset"
    mock_update.message.chat_id = 99
    mock_update.message.message_id = 1
    mock_update.message.date = None
    mock_update.message.reply_text = AsyncMock()

    with patch(
        "tg_gateway.handlers.message.download_and_upload_image",
        new_callable=AsyncMock,
        return_value="/data/images/sunset.jpg",
    ):
        await handle_image(mock_update, mock_context)

    # Image was enqueued (not processed immediately)
    core_client.enqueue_message.assert_called_once()
    core_client.dequeue_message.assert_not_called()
    reply = mock_update.message.reply_text.call_args[0][0]
    assert "queue" in reply.lower() or "ahead" in reply.lower()

    # -- Phase 2: Text conversation completes, image auto-dequeued --
    image_item = QueueItem(
        id="q-img",
        content="My sunset",
        memory_id="mem-img",
        image_local_path="/data/images/sunset.jpg",
        message_timestamp=None,
        created_at=datetime(2026, 3, 7, 10, 0, 0, tzinfo=timezone.utc),
    )
    core_client.dequeue_message = AsyncMock(
        return_value=DequeueResponse(item=image_item),
    )
    core_client.start_conversation = AsyncMock()
    core_client.create_llm_job = AsyncMock()

    await _clear_conversation_state(mock_context, user_id=12345)

    # Verify conversation was marked completed
    core_client.update_conversation_state.assert_called_once_with(12345, "completed")

    # Verify next item was dequeued, conversation started, and image LLM job created
    core_client.start_conversation.assert_called_once_with(12345, queue_item_id="q-img")
    core_client.create_llm_job.assert_called_once()
    job = core_client.create_llm_job.call_args[0][0]
    assert job.job_type.value == "image_tag"
    assert job.payload["memory_id"] == "mem-img"
