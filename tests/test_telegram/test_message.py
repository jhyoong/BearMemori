"""Tests for message handlers in tg_gateway/handlers/message.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Update
from telegram.ext import ContextTypes

from shared_lib.enums import JobType
from tg_gateway.core_client import CoreUnavailableError
from tg_gateway.handlers.conversation import (
    AWAITING_BUTTON_ACTION,
    PENDING_LLM_CONVERSATION,
    PENDING_REMINDER_MEMORY_ID,
    PENDING_TAG_MEMORY_ID,
    PENDING_TASK_MEMORY_ID,
    USER_QUEUE_COUNT,
)
from tg_gateway.handlers.message import handle_text


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


def _make_core_client() -> MagicMock:
    """Return a mock CoreClient with async methods."""
    client = MagicMock()
    client.ensure_user = AsyncMock()
    client.create_memory = AsyncMock()
    client.create_llm_job = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Queue-first text flow
# ---------------------------------------------------------------------------


class TestHandleTextQueueFlow:
    """Tests for the queue-first text handling flow."""

    @pytest.mark.asyncio
    async def test_empty_queue_replies_processing(self):
        """When queue is empty (count == 0), reply is 'Processing your message...'."""
        core_client = _make_core_client()
        update = _make_update(text="Remember to buy milk")
        context = _make_context(bot_data={"core_client": core_client})
        # No queue count set — defaults to 0

        await handle_text(update, context)

        update.message.reply_text.assert_called_once_with("Processing your message...")

    @pytest.mark.asyncio
    async def test_nonempty_queue_replies_added_to_queue(self):
        """When queue already has items (count > 0), reply includes queue count."""
        core_client = _make_core_client()
        update = _make_update(text="Second message")
        redis_client = AsyncMock()
        redis_client.get = AsyncMock(return_value=b'{"status": "healthy"}')
        context = _make_context(
            user_data={USER_QUEUE_COUNT: 1},
            bot_data={
                "core_client": core_client,
                "redis": redis_client,
            },
        )

        await handle_text(update, context)

        update.message.reply_text.assert_called_once_with("Added to queue (1 message ahead)")

    @pytest.mark.asyncio
    async def test_creates_llm_job_on_text(self):
        """An LLM intent_classify job is created for the incoming text."""
        core_client = _make_core_client()
        update = _make_update(text="Note to self")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "Note to self"

    @pytest.mark.asyncio
    async def test_llm_job_payload_contains_source_fields(self):
        """The LLM job payload includes chat_id, message_id, and message_timestamp."""
        core_client = _make_core_client()
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
        """message_timestamp is the ISO string of msg.date when date is present."""
        from datetime import datetime, timezone

        core_client = _make_core_client()
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
        core_client = _make_core_client()
        update = _make_update(text="Hello", user_id=555)
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.user_id == 555

    @pytest.mark.asyncio
    async def test_queue_count_incremented_after_job(self):
        """Queue counter is incremented after queuing the LLM job."""
        core_client = _make_core_client()
        update = _make_update(text="Increment me")
        context = _make_context(bot_data={"core_client": core_client})

        assert context.user_data.get(USER_QUEUE_COUNT, 0) == 0
        await handle_text(update, context)
        assert context.user_data.get(USER_QUEUE_COUNT, 0) == 1

    @pytest.mark.asyncio
    async def test_ensure_user_called_before_job(self):
        """ensure_user is called with the Telegram user's id and full_name."""
        core_client = _make_core_client()
        update = _make_update(text="Test", user_id=77)
        update.message.from_user.full_name = "Alice"
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.ensure_user.assert_called_once_with(77, "Alice")

    @pytest.mark.asyncio
    async def test_no_memory_created(self):
        """No memory is created directly — only an LLM job."""
        core_client = _make_core_client()
        core_client.create_memory = AsyncMock()  # should never be called
        update = _make_update(text="Some text")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.create_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_job_payload_has_memory_id_none(self):
        """The LLM job payload should have memory_id set to None, not a memory object."""
        core_client = _make_core_client()
        core_client.create_memory = AsyncMock()  # should not be called
        update = _make_update(text="Remember to buy milk")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        # Memory ID should be None, not a memory object
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
        core_client.ensure_user = AsyncMock(side_effect=CoreUnavailableError("down"))
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
        core_client.ensure_user = AsyncMock(side_effect=CoreUnavailableError("down"))
        update = _make_update(text="Hello")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        core_client.create_llm_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_core_unavailable_on_create_llm_job_replies_error(self):
        """CoreUnavailableError from create_llm_job causes a friendly error reply."""
        core_client = _make_core_client()
        core_client.create_llm_job = AsyncMock(side_effect=CoreUnavailableError("down"))
        update = _make_update(text="Hello")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        # There will be two reply_text calls: first "Processing..." then the error message.
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

        # No LLM job created
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
        """Text during PENDING_REMINDER_MEMORY_ID state is routed to receive_custom_reminder."""
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
    async def test_pending_llm_conversation_routes_to_receive_followup_answer(self):
        """Text during PENDING_LLM_CONVERSATION state is routed to receive_followup_answer."""
        core_client = _make_core_client()
        pending_state = {
            "memory_id": "mem-4",
            "original_text": "Buy milk",
            "followup_question": "When?",
        }
        update = _make_update(text="Tomorrow")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        with patch(
            "tg_gateway.handlers.message.conversation.receive_followup_answer",
            new_callable=AsyncMock,
        ) as mock_followup:
            await handle_text(update, context)
            mock_followup.assert_called_once_with(update, context)

        core_client.create_llm_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_awaiting_button_action_without_llm_conversation_queues_as_new(self):
        """Text during AWAITING_BUTTON_ACTION (no PENDING_LLM_CONVERSATION) queues as new."""
        core_client = _make_core_client()
        update = _make_update(text="New text while buttons shown")
        context = _make_context(
            user_data={AWAITING_BUTTON_ACTION: True},
            bot_data={"core_client": core_client},
        )

        await handle_text(update, context)

        # Should queue as new message
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "New text while buttons shown"

    @pytest.mark.asyncio
    async def test_pending_llm_conversation_takes_priority_over_awaiting_button(self):
        """PENDING_LLM_CONVERSATION takes priority over AWAITING_BUTTON_ACTION."""
        core_client = _make_core_client()
        pending_state = {
            "memory_id": "mem-5",
            "original_text": "Something",
            "followup_question": "What?",
        }
        update = _make_update(text="My answer")
        context = _make_context(
            user_data={
                PENDING_LLM_CONVERSATION: pending_state,
                AWAITING_BUTTON_ACTION: True,
            },
            bot_data={"core_client": core_client},
        )

        with patch(
            "tg_gateway.handlers.message.conversation.receive_followup_answer",
            new_callable=AsyncMock,
        ) as mock_followup:
            await handle_text(update, context)
            mock_followup.assert_called_once_with(update, context)

        # No LLM intent job created
        core_client.create_llm_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_tag_state_takes_priority_over_llm_conversation(self):
        """PENDING_TAG_MEMORY_ID takes priority over PENDING_LLM_CONVERSATION."""
        core_client = _make_core_client()
        pending_state = {
            "memory_id": "mem-6",
            "original_text": "Something",
            "followup_question": "What?",
        }
        update = _make_update(text="work, home")
        context = _make_context(
            user_data={
                PENDING_TAG_MEMORY_ID: "mem-6",
                PENDING_LLM_CONVERSATION: pending_state,
            },
            bot_data={"core_client": core_client},
        )

        with patch(
            "tg_gateway.handlers.message.conversation.receive_tags",
            new_callable=AsyncMock,
        ) as mock_receive_tags:
            with patch(
                "tg_gateway.handlers.message.conversation.receive_followup_answer",
                new_callable=AsyncMock,
            ) as mock_followup:
                await handle_text(update, context)
                mock_receive_tags.assert_called_once_with(update, context)
                mock_followup.assert_not_called()


# ---------------------------------------------------------------------------
# Specific phrase integration tests - full flow from user message
# ---------------------------------------------------------------------------


class TestHandleTextSpecificPhrases:
    """Tests for specific user phrases to verify correct flow."""

    @pytest.mark.asyncio
    async def test_search_phrase_creates_llm_job(self):
        """Test 'Search for all images about anime' creates LLM job."""
        core_client = _make_core_client()
        update = _make_update(text="Search for all images about anime")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        # Verify LLM job is created for search
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "Search for all images about anime"
        # Memory ID should be None for new job (not yet created)
        assert job_arg.payload["memory_id"] is None

    @pytest.mark.asyncio
    async def test_reminder_phrase_creates_llm_job(self):
        """Test 'Remind me to call mom tomorrow' creates LLM job."""
        core_client = _make_core_client()
        update = _make_update(text="Remind me to call mom tomorrow")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        # Verify LLM job is created for reminder
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "Remind me to call mom tomorrow"

    @pytest.mark.asyncio
    async def test_task_phrase_creates_llm_job(self):
        """Test 'Add task to finish report by Friday' creates LLM job."""
        core_client = _make_core_client()
        update = _make_update(text="Add task to finish report by Friday")
        context = _make_context(bot_data={"core_client": core_client})

        await handle_text(update, context)

        # Verify LLM job is created for task
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "Add task to finish report by Friday"

    @pytest.mark.asyncio
    async def test_search_phrase_queue_count_increments(self):
        """Test that search phrase increments queue count."""
        core_client = _make_core_client()
        update = _make_update(text="Search for all images about anime")
        context = _make_context(bot_data={"core_client": core_client})

        assert context.user_data.get(USER_QUEUE_COUNT, 0) == 0
        await handle_text(update, context)
        assert context.user_data.get(USER_QUEUE_COUNT, 0) == 1

    @pytest.mark.asyncio
    async def test_reminder_phrase_queue_count_increments(self):
        """Test that reminder phrase increments queue count."""
        core_client = _make_core_client()
        update = _make_update(text="Remind me to call mom tomorrow")
        context = _make_context(bot_data={"core_client": core_client})

        assert context.user_data.get(USER_QUEUE_COUNT, 0) == 0
        await handle_text(update, context)
        assert context.user_data.get(USER_QUEUE_COUNT, 0) == 1

    @pytest.mark.asyncio
    async def test_task_phrase_queue_count_increments(self):
        """Test that task phrase increments queue count."""
        core_client = _make_core_client()
        update = _make_update(text="Add task to finish report by Friday")
        context = _make_context(bot_data={"core_client": core_client})

        assert context.user_data.get(USER_QUEUE_COUNT, 0) == 0
        await handle_text(update, context)
        assert context.user_data.get(USER_QUEUE_COUNT, 0) == 1
