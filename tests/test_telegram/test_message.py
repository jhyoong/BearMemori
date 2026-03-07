"""Tests for message handlers in tg_gateway/handlers/message.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Update
from telegram.ext import ContextTypes

from shared_lib.enums import JobType
from tg_gateway.core_client import CoreUnavailableError
from tg_gateway.handlers.conversation import (
    AWAITING_BUTTON_ACTION,
    LLM_CONVERSATION_METADATA,
    PENDING_REMINDER_MEMORY_ID,
    PENDING_TAG_MEMORY_ID,
    PENDING_TASK_MEMORY_ID,
)
from tg_gateway.handlers.message import _process_image_queue_item, handle_text


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_update(text: str = "hello world", user_id: int = 99) -> MagicMock:
    """Return a minimal mock Update with a message."""
    update = MagicMock(spec=Update)
    update.message = MagicMock()
    update.message.text = text
    update.message.chat_id = 12345
    update.message.message_id = 1
    update.message.date = None
    update.message.reply_text = AsyncMock()
    user = MagicMock()
    user.id = user_id
    user.full_name = "Test User"
    update.message.from_user = user
    return update


def _make_context(
    user_data: dict | None = None, bot_data: dict | None = None
) -> MagicMock:
    """Return a minimal mock context with controllable user_data and bot_data."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = user_data if user_data is not None else {}
    context.bot_data = bot_data if bot_data is not None else {}
    return context


def _make_core_client(
    active_conversation=None,
    queue_status=None,
) -> MagicMock:
    """Return a mock CoreClient with async methods for the new queue-based flow.

    Args:
        active_conversation: Return value for get_active_conversation.
        queue_status: Return value for get_queue_status.
    """
    client = MagicMock()
    client.ensure_user = AsyncMock()
    client.create_memory = AsyncMock()
    client.create_llm_job = AsyncMock()
    client.get_active_conversation = AsyncMock(return_value=active_conversation)
    client.enqueue_message = AsyncMock(
        return_value=MagicMock(id="qi-1")
    )
    # dequeue returns an object with .item
    dequeue_item = MagicMock()
    dequeue_item.id = "qi-1"
    dequeue_resp = MagicMock()
    dequeue_resp.item = dequeue_item
    client.dequeue_message = AsyncMock(return_value=dequeue_resp)
    client.start_conversation = AsyncMock()
    client.get_settings = AsyncMock(side_effect=Exception("no settings"))
    if queue_status is not None:
        client.get_queue_status = AsyncMock(return_value=queue_status)
    else:
        qs = MagicMock()
        qs.queue_length = 0
        qs.conversation_active = False
        client.get_queue_status = AsyncMock(return_value=qs)
    return client


# ---------------------------------------------------------------------------
# Queue-first text flow (new: enqueue -> dequeue -> start_conversation)
# ---------------------------------------------------------------------------


class TestHandleTextQueueFlow:
    """Tests for the queue-based text handling flow."""

    @pytest.mark.asyncio
    async def test_no_active_conversation_replies_processing(self):
        """When no active conversation, reply is 'Processing your message...'."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Remember to buy milk")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        update.message.reply_text.assert_called_once_with(
            "Processing your message..."
        )

    @pytest.mark.asyncio
    async def test_active_processing_conversation_enqueues_and_replies(self):
        """When active conversation is processing, enqueue and reply with queue count."""
        active_conv = MagicMock()
        active_conv.state = "processing"
        qs = MagicMock()
        qs.queue_length = 2
        core_client = _make_core_client(
            active_conversation=active_conv,
            queue_status=qs,
        )
        update = _make_update(text="Second message")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.enqueue_message.assert_called_once()
        core_client.get_queue_status.assert_called_once()
        update.message.reply_text.assert_called_once_with(
            "Added to queue (2 messages ahead)"
        )

    @pytest.mark.asyncio
    async def test_creates_llm_job_on_text(self):
        """An LLM intent_classify job is created for the incoming text."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Note to self")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "Note to self"

    @pytest.mark.asyncio
    async def test_llm_job_payload_contains_source_fields(self):
        """The LLM job payload includes chat_id, message_id."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Some text")
        update.message.chat_id = 42
        update.message.message_id = 7
        update.message.date = None
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.payload["source_chat_id"] == 42
        assert job_arg.payload["source_message_id"] == 7
        assert job_arg.payload["original_timestamp"] is None

    @pytest.mark.asyncio
    async def test_llm_job_payload_timestamp_when_date_set(self):
        """original_timestamp is the ISO string of msg.date when date is present."""
        from datetime import datetime, timezone

        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Timestamped message")
        dt = datetime(2025, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
        update.message.date = dt
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.payload["original_timestamp"] == dt.isoformat()

    @pytest.mark.asyncio
    async def test_llm_job_user_id_matches_telegram_user(self):
        """The LLM job carries the Telegram user's ID."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Hello", user_id=555)
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.user_id == 555

    @pytest.mark.asyncio
    async def test_enqueue_dequeue_start_conversation_called(self):
        """When no active conversation, enqueue, dequeue, and start_conversation are called."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Increment me")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.enqueue_message.assert_called_once()
        core_client.dequeue_message.assert_called_once()
        core_client.start_conversation.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_user_called_before_job(self):
        """ensure_user is called with the Telegram user's id and full_name."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Test", user_id=77)
        update.message.from_user.full_name = "Alice"
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.ensure_user.assert_called_once_with(77, "Alice")

    @pytest.mark.asyncio
    async def test_no_memory_created(self):
        """No memory is created directly -- only an LLM job."""
        core_client = _make_core_client(active_conversation=None)
        core_client.create_memory = AsyncMock()
        update = _make_update(text="Some text")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.create_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_job_payload_has_memory_id_none(self):
        """The LLM job payload should have memory_id set to None."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Remember to buy milk")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.payload["memory_id"] is None


# ---------------------------------------------------------------------------
# CoreUnavailableError handling
# ---------------------------------------------------------------------------


class TestHandleTextCoreUnavailable:
    """Tests for CoreUnavailableError handling in handle_text."""

    @pytest.mark.asyncio
    async def test_core_unavailable_on_ensure_user_replies_error(self):
        """CoreUnavailableError from ensure_user causes a friendly error reply."""
        core_client = _make_core_client()
        core_client.ensure_user = AsyncMock(
            side_effect=CoreUnavailableError("down")
        )
        update = _make_update(text="Hello")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        update.message.reply_text.assert_called_once()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "trouble" in reply_text.lower() or "try again" in reply_text.lower()

    @pytest.mark.asyncio
    async def test_core_unavailable_does_not_create_job(self):
        """CoreUnavailableError stops execution before creating an LLM job."""
        core_client = _make_core_client()
        core_client.ensure_user = AsyncMock(
            side_effect=CoreUnavailableError("down")
        )
        update = _make_update(text="Hello")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.create_llm_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_core_unavailable_on_create_llm_job_replies_error(self):
        """CoreUnavailableError from create_llm_job causes a friendly error reply."""
        core_client = _make_core_client(active_conversation=None)
        core_client.create_llm_job = AsyncMock(
            side_effect=CoreUnavailableError("down")
        )
        update = _make_update(text="Hello")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        # There will be two reply_text calls: first "Processing..." then the error.
        assert update.message.reply_text.call_count == 2
        last_reply = update.message.reply_text.call_args_list[-1][0][0]
        assert "trouble" in last_reply.lower() or "try again" in last_reply.lower()


# ---------------------------------------------------------------------------
# Pending conversation state routing
# ---------------------------------------------------------------------------


class TestHandleTextConversationRouting:
    """Tests for routing to conversation handlers based on pending state."""

    @pytest.mark.asyncio
    async def test_pending_tag_routes_to_receive_tags(self):
        """Text during PENDING_TAG_MEMORY_ID state is routed to receive_tags."""
        core_client = _make_core_client()
        update = _make_update(text="work, health")
        context = _make_context(
            user_data={PENDING_TAG_MEMORY_ID: "mem-1"},
            bot_data={"core_client": core_client},
        )

        with patch(
            "tg_gateway.handlers.message.conversation.receive_tags",
            new_callable=AsyncMock,
        ) as mock_receive_tags:
            await handle_text(update, context)
            mock_receive_tags.assert_called_once_with(update, context)

        core_client.create_llm_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_task_routes_to_receive_custom_date(self):
        """Text during PENDING_TASK_MEMORY_ID state is routed to receive_custom_date."""
        core_client = _make_core_client()
        update = _make_update(text="2024-12-25")
        context = _make_context(
            user_data={PENDING_TASK_MEMORY_ID: "mem-2"},
            bot_data={"core_client": core_client},
        )

        with patch(
            "tg_gateway.handlers.message.conversation.receive_custom_date",
            new_callable=AsyncMock,
        ) as mock_receive_date:
            await handle_text(update, context)
            mock_receive_date.assert_called_once_with(update, context)

        core_client.create_llm_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_pending_reminder_routes_to_receive_custom_reminder(self):
        """Text during PENDING_REMINDER_MEMORY_ID routes to receive_custom_reminder."""
        core_client = _make_core_client()
        update = _make_update(text="2024-12-20 09:00")
        context = _make_context(
            user_data={PENDING_REMINDER_MEMORY_ID: "mem-3"},
            bot_data={"core_client": core_client},
        )

        with patch(
            "tg_gateway.handlers.message.conversation.receive_custom_reminder",
            new_callable=AsyncMock,
        ) as mock_receive_reminder:
            await handle_text(update, context)
            mock_receive_reminder.assert_called_once_with(update, context)

        core_client.create_llm_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_active_awaiting_reply_conversation_routes_to_followup(self):
        """When Core API shows awaiting_reply conversation, reply creates followup job."""
        active_conv = MagicMock()
        active_conv.state = "awaiting_reply"
        conv_resp = MagicMock()
        conv_resp.history = []
        core_client = _make_core_client(active_conversation=active_conv)
        core_client.reply_to_conversation = AsyncMock(return_value=conv_resp)

        update = _make_update(text="Tomorrow")
        context = _make_context(
            user_data={
                LLM_CONVERSATION_METADATA: {
                    "memory_id": "mem-4",
                    "original_text": "Buy milk",
                    "followup_question": "When?",
                },
            },
            bot_data={"core_client": core_client},
        )

        await handle_text(update, context)

        core_client.reply_to_conversation.assert_called_once()
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.followup

    @pytest.mark.asyncio
    async def test_awaiting_button_action_without_active_conv_queues_new(self):
        """Text during AWAITING_BUTTON_ACTION with no active conv queues as new."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="New text while buttons shown")
        context = _make_context(
            user_data={AWAITING_BUTTON_ACTION: True},
            bot_data={"core_client": core_client},
        )

        await handle_text(update, context)

        # Should queue as new message (enqueue, dequeue, start, create job)
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify

    @pytest.mark.asyncio
    async def test_tag_state_takes_priority_over_active_conversation(self):
        """PENDING_TAG_MEMORY_ID takes priority over active conversation."""
        active_conv = MagicMock()
        active_conv.state = "awaiting_reply"
        core_client = _make_core_client(active_conversation=active_conv)
        update = _make_update(text="work, home")
        context = _make_context(
            user_data={PENDING_TAG_MEMORY_ID: "mem-6"},
            bot_data={"core_client": core_client},
        )

        with patch(
            "tg_gateway.handlers.message.conversation.receive_tags",
            new_callable=AsyncMock,
        ) as mock_receive_tags:
            await handle_text(update, context)
            mock_receive_tags.assert_called_once_with(update, context)

        core_client.create_llm_job.assert_not_called()


# ---------------------------------------------------------------------------
# Specific phrase integration tests - full flow from user message
# ---------------------------------------------------------------------------


class TestHandleTextSpecificPhrases:
    """Tests for specific user phrases to verify correct flow."""

    @pytest.mark.asyncio
    async def test_search_phrase_creates_llm_job(self):
        """Test 'Search for all images about anime' creates LLM job."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Search for all images about anime")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "Search for all images about anime"
        assert job_arg.payload["memory_id"] is None

    @pytest.mark.asyncio
    async def test_reminder_phrase_creates_llm_job(self):
        """Test 'Remind me to call mom tomorrow' creates LLM job."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Remind me to call mom tomorrow")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify

    @pytest.mark.asyncio
    async def test_task_phrase_creates_llm_job(self):
        """Test 'Add task to finish report by Friday' creates LLM job."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Add task to finish report by Friday")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify

    @pytest.mark.asyncio
    async def test_new_message_calls_enqueue_and_dequeue(self):
        """Test that new messages go through enqueue -> dequeue -> start flow."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Search for all images about anime")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.enqueue_message.assert_called_once()
        core_client.dequeue_message.assert_called_once()
        core_client.start_conversation.assert_called_once()


# ---------------------------------------------------------------------------
# Telegram API failure resilience tests
# ---------------------------------------------------------------------------


class TestHandleTextTelegramApiFailures:
    """Tests for resilience when Telegram API fails during handle_text."""

    @pytest.mark.asyncio
    async def test_reply_text_exception_still_creates_llm_job(self):
        """If reply_text raises, LLM job should still be created."""
        core_client = _make_core_client(active_conversation=None)
        update = _make_update(text="Hello world")
        context = _make_context(bot_data={"core_client": core_client})

        update.message.reply_text = AsyncMock(
            side_effect=Exception("Telegram API error")
        )

        await handle_text(update, context)

        # LLM job MUST be created even if reply_text failed
        core_client.create_llm_job.assert_called_once()

    @pytest.mark.asyncio
    async def test_core_unavailable_error_preserves_error_reply(self):
        """CoreUnavailableError should still reply with error message."""
        core_client = _make_core_client(active_conversation=None)
        core_client.create_llm_job = AsyncMock(
            side_effect=CoreUnavailableError("Core is down")
        )
        update = _make_update(text="Hello")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        update.message.reply_text.assert_called()
        reply_text = update.message.reply_text.call_args[0][0]
        assert "trouble" in reply_text.lower() or "try again" in reply_text.lower()


# ---------------------------------------------------------------------------
# _process_image_queue_item tests
# ---------------------------------------------------------------------------


class TestProcessImageQueueItem:
    """Tests for the _process_image_queue_item helper."""

    @pytest.mark.asyncio
    async def test_process_image_queue_item_creates_llm_job(self):
        """_process_image_queue_item creates an image_tag LLM job using the stored local_path."""
        core_client = _make_core_client()

        queue_item = type("QueueItem", (), {
            "memory_id": "mem-456",
            "image_local_path": "/data/images/abc.jpg",
            "content": "sunset photo",
        })()

        core_client.create_llm_job = AsyncMock()

        await _process_image_queue_item(core_client, user_id=12345, queue_item=queue_item)

        core_client.create_llm_job.assert_called_once()
        call_args = core_client.create_llm_job.call_args[0][0]
        assert call_args.job_type == JobType.image_tag
        assert call_args.payload["memory_id"] == "mem-456"
        assert call_args.payload["image_path"] == "/data/images/abc.jpg"
        assert call_args.user_id == 12345

    @pytest.mark.asyncio
    async def test_process_image_queue_item_skips_job_if_no_local_path(self):
        """If image_local_path is None (download failed earlier), skip LLM job."""
        core_client = _make_core_client()

        queue_item = type("QueueItem", (), {
            "memory_id": "mem-456",
            "image_local_path": None,
            "content": "sunset photo",
        })()

        core_client.create_llm_job = AsyncMock()

        await _process_image_queue_item(core_client, user_id=12345, queue_item=queue_item)

        core_client.create_llm_job.assert_not_called()
