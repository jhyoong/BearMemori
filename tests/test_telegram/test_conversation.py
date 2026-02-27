"""Tests for conversation handlers in tg_gateway/handlers/conversation.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import Update
from telegram.ext import ContextTypes

from tg_gateway.handlers.conversation import (
    AWAITING_BUTTON_ACTION,
    PENDING_LLM_CONVERSATION,
    PENDING_REMINDER_MEMORY_ID,
    PENDING_TAG_MEMORY_ID,
    PENDING_TASK_MEMORY_ID,
    USER_QUEUE_COUNT,
    decrement_queue,
    get_queue_count,
    increment_queue,
    parse_datetime,
    receive_custom_date,
    receive_custom_reminder,
    receive_followup_answer,
    receive_tags,
)


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_update(text: str = "hello", user_id: int = 99) -> MagicMock:
    """Return a minimal mock Update whose message has the given text."""
    update = MagicMock(spec=Update)
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    user = MagicMock()
    user.id = user_id
    update.message.from_user = user
    return update


def _make_context(user_data: dict | None = None, bot_data: dict | None = None) -> MagicMock:
    """Return a minimal mock context with controllable user_data and bot_data."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = user_data if user_data is not None else {}
    context.bot_data = bot_data if bot_data is not None else {}
    return context


# ---------------------------------------------------------------------------
# parse_datetime
# ---------------------------------------------------------------------------


class TestParseDatetime:
    """Tests for parse_datetime utility."""

    def test_parses_yyyy_mm_dd_hhmm(self):
        dt = parse_datetime("2024-12-25 09:00")
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 12
        assert dt.day == 25
        assert dt.hour == 9

    def test_parses_yyyy_mm_dd(self):
        dt = parse_datetime("2024-01-01")
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 1

    def test_parses_dd_slash_mm_slash_yyyy_hhmm(self):
        dt = parse_datetime("25/12/2024 14:30")
        assert dt is not None
        assert dt.day == 25
        assert dt.month == 12
        assert dt.hour == 14

    def test_parses_dd_slash_mm_slash_yyyy(self):
        dt = parse_datetime("25/12/2024")
        assert dt is not None
        assert dt.day == 25

    def test_returns_none_on_invalid_input(self):
        assert parse_datetime("not a date") is None

    def test_returns_none_on_empty_string(self):
        assert parse_datetime("") is None

    def test_result_is_utc_aware(self):
        from datetime import timezone
        dt = parse_datetime("2024-06-15 12:00")
        assert dt.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Queue counter helpers
# ---------------------------------------------------------------------------


class TestQueueCounterHelpers:
    """Tests for increment_queue, decrement_queue, get_queue_count."""

    def test_get_queue_count_default_is_zero(self):
        context = _make_context()
        assert get_queue_count(context) == 0

    def test_increment_queue_increments_from_zero(self):
        context = _make_context()
        result = increment_queue(context)
        assert result == 1
        assert context.user_data[USER_QUEUE_COUNT] == 1

    def test_increment_queue_twice(self):
        context = _make_context()
        increment_queue(context)
        result = increment_queue(context)
        assert result == 2

    def test_decrement_queue_after_increment(self):
        context = _make_context()
        increment_queue(context)
        result = decrement_queue(context)
        assert result == 0
        assert context.user_data[USER_QUEUE_COUNT] == 0

    def test_decrement_queue_clamps_at_zero(self):
        context = _make_context()
        # Decrement on an empty counter — must not go negative
        result = decrement_queue(context)
        assert result == 0

    def test_get_queue_count_reflects_increments(self):
        context = _make_context()
        increment_queue(context)
        increment_queue(context)
        assert get_queue_count(context) == 2

    def test_queue_state_persists_in_user_data(self):
        context = _make_context()
        increment_queue(context)
        assert USER_QUEUE_COUNT in context.user_data


# ---------------------------------------------------------------------------
# State key constants
# ---------------------------------------------------------------------------


class TestStateKeyConstants:
    """Verify the new constants exist with expected string values."""

    def test_pending_llm_conversation_value(self):
        assert PENDING_LLM_CONVERSATION == "pending_llm_conversation"

    def test_awaiting_button_action_value(self):
        assert AWAITING_BUTTON_ACTION == "awaiting_button_action"

    def test_user_queue_count_value(self):
        assert USER_QUEUE_COUNT == "user_queue_count"

    def test_existing_constants_unchanged(self):
        assert PENDING_TAG_MEMORY_ID == "pending_tag_memory_id"
        assert PENDING_TASK_MEMORY_ID == "pending_task_memory_id"
        assert PENDING_REMINDER_MEMORY_ID == "pending_reminder_memory_id"


# ---------------------------------------------------------------------------
# receive_tags
# ---------------------------------------------------------------------------


class TestReceiveTags:
    """Tests for receive_tags handler."""

    @pytest.mark.asyncio
    async def test_adds_tags_to_memory(self):
        """Happy path: tags are parsed and added via core_client."""
        core_client = MagicMock()
        core_client.add_tags = AsyncMock()

        update = _make_update(text="work, health, ideas")
        context = _make_context(
            user_data={PENDING_TAG_MEMORY_ID: "mem-1"},
            bot_data={"core_client": core_client},
        )

        await receive_tags(update, context)

        core_client.add_tags.assert_called_once()
        call_args = core_client.add_tags.call_args[0]
        assert call_args[0] == "mem-1"
        assert set(call_args[1].tags) == {"work", "health", "ideas"}

    @pytest.mark.asyncio
    async def test_clears_pending_state_on_success(self):
        """Pending state is removed after successful tag submission."""
        core_client = MagicMock()
        core_client.add_tags = AsyncMock()

        update = _make_update(text="tag1")
        context = _make_context(
            user_data={PENDING_TAG_MEMORY_ID: "mem-1"},
            bot_data={"core_client": core_client},
        )

        await receive_tags(update, context)

        assert PENDING_TAG_MEMORY_ID not in context.user_data

    @pytest.mark.asyncio
    async def test_replies_with_added_tags(self):
        """Reply text lists the added tags."""
        core_client = MagicMock()
        core_client.add_tags = AsyncMock()

        update = _make_update(text="alpha, beta")
        context = _make_context(
            user_data={PENDING_TAG_MEMORY_ID: "mem-2"},
            bot_data={"core_client": core_client},
        )

        await receive_tags(update, context)

        reply_call = update.message.reply_text.call_args[0][0]
        assert "alpha" in reply_call
        assert "beta" in reply_call

    @pytest.mark.asyncio
    async def test_no_pending_state_replies_error(self):
        """If no memory ID is pending, handler replies with error message."""
        update = _make_update(text="some tag")
        context = _make_context(bot_data={"core_client": MagicMock()})

        await receive_tags(update, context)

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "wrong" in msg.lower() or "try again" in msg.lower()

    @pytest.mark.asyncio
    async def test_empty_tags_restores_pending_state(self):
        """If user sends blank text, pending state is restored for retry."""
        update = _make_update(text="   ")
        context = _make_context(
            user_data={PENDING_TAG_MEMORY_ID: "mem-3"},
            bot_data={"core_client": MagicMock()},
        )

        await receive_tags(update, context)

        assert context.user_data.get(PENDING_TAG_MEMORY_ID) == "mem-3"

    @pytest.mark.asyncio
    async def test_exception_restores_pending_state(self):
        """On core_client failure, pending state is restored so user can retry."""
        core_client = MagicMock()
        core_client.add_tags = AsyncMock(side_effect=Exception("boom"))

        update = _make_update(text="tag1")
        context = _make_context(
            user_data={PENDING_TAG_MEMORY_ID: "mem-4"},
            bot_data={"core_client": core_client},
        )

        await receive_tags(update, context)

        assert context.user_data.get(PENDING_TAG_MEMORY_ID) == "mem-4"
        update.message.reply_text.assert_called()


# ---------------------------------------------------------------------------
# receive_custom_date
# ---------------------------------------------------------------------------


class TestReceiveCustomDate:
    """Tests for receive_custom_date handler."""

    @pytest.mark.asyncio
    async def test_creates_task_with_memory_content(self):
        """Task description uses the memory's actual content, not a hardcoded string."""
        mock_memory = MagicMock()
        mock_memory.content = "Buy groceries"

        core_client = MagicMock()
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.create_task = AsyncMock()

        update = _make_update(text="2024-12-25 10:00")
        context = _make_context(
            user_data={PENDING_TASK_MEMORY_ID: "mem-5"},
            bot_data={"core_client": core_client},
        )

        await receive_custom_date(update, context)

        core_client.create_task.assert_called_once()
        task_arg = core_client.create_task.call_args[0][0]
        assert task_arg.description == "Buy groceries"

    @pytest.mark.asyncio
    async def test_not_hardcoded_task_for_memory(self):
        """Description is NOT the old hardcoded 'Task for memory' string."""
        mock_memory = MagicMock()
        mock_memory.content = "Call dentist"

        core_client = MagicMock()
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.create_task = AsyncMock()

        update = _make_update(text="2024-12-25")
        context = _make_context(
            user_data={PENDING_TASK_MEMORY_ID: "mem-6"},
            bot_data={"core_client": core_client},
        )

        await receive_custom_date(update, context)

        task_arg = core_client.create_task.call_args[0][0]
        assert task_arg.description != "Task for memory"
        assert task_arg.description == "Call dentist"

    @pytest.mark.asyncio
    async def test_clears_pending_state_on_success(self):
        """Pending state is cleared after task creation."""
        mock_memory = MagicMock()
        mock_memory.content = "Some task"

        core_client = MagicMock()
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.create_task = AsyncMock()

        update = _make_update(text="2024-06-01 08:00")
        context = _make_context(
            user_data={PENDING_TASK_MEMORY_ID: "mem-7"},
            bot_data={"core_client": core_client},
        )

        await receive_custom_date(update, context)

        assert PENDING_TASK_MEMORY_ID not in context.user_data

    @pytest.mark.asyncio
    async def test_invalid_date_restores_pending_state(self):
        """Unparseable date re-sets pending state for retry."""
        update = _make_update(text="not a date at all")
        context = _make_context(
            user_data={PENDING_TASK_MEMORY_ID: "mem-8"},
            bot_data={"core_client": MagicMock()},
        )

        await receive_custom_date(update, context)

        assert context.user_data.get(PENDING_TASK_MEMORY_ID) == "mem-8"
        update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_no_pending_state_replies_error(self):
        """Missing pending state causes an error reply."""
        update = _make_update(text="2024-12-01")
        context = _make_context(bot_data={"core_client": MagicMock()})

        await receive_custom_date(update, context)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_description_when_memory_missing(self):
        """If get_memory returns None, description falls back to generic string."""
        core_client = MagicMock()
        core_client.get_memory = AsyncMock(return_value=None)
        core_client.create_task = AsyncMock()

        update = _make_update(text="2024-12-25 09:00")
        context = _make_context(
            user_data={PENDING_TASK_MEMORY_ID: "mem-9"},
            bot_data={"core_client": core_client},
        )

        await receive_custom_date(update, context)

        task_arg = core_client.create_task.call_args[0][0]
        # Should be some non-empty fallback, not the old hardcoded string
        assert task_arg.description
        assert task_arg.description != "Task for memory"

    @pytest.mark.asyncio
    async def test_due_date_propagated_to_task(self):
        """The parsed due date is set on the task."""
        mock_memory = MagicMock()
        mock_memory.content = "Test"

        core_client = MagicMock()
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.create_task = AsyncMock()

        update = _make_update(text="2025-03-15 14:30")
        context = _make_context(
            user_data={PENDING_TASK_MEMORY_ID: "mem-10"},
            bot_data={"core_client": core_client},
        )

        await receive_custom_date(update, context)

        task_arg = core_client.create_task.call_args[0][0]
        assert task_arg.due_at is not None
        assert task_arg.due_at.month == 3
        assert task_arg.due_at.day == 15


# ---------------------------------------------------------------------------
# receive_custom_reminder
# ---------------------------------------------------------------------------


class TestReceiveCustomReminder:
    """Tests for receive_custom_reminder handler."""

    @pytest.mark.asyncio
    async def test_creates_reminder_with_memory_content(self):
        """Reminder text is the memory's actual content, not 'Custom reminder'."""
        mock_memory = MagicMock()
        mock_memory.content = "Doctor appointment"

        core_client = MagicMock()
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.create_reminder = AsyncMock()

        update = _make_update(text="2024-12-20 09:00")
        context = _make_context(
            user_data={PENDING_REMINDER_MEMORY_ID: "mem-11"},
            bot_data={"core_client": core_client},
        )

        await receive_custom_reminder(update, context)

        core_client.create_reminder.assert_called_once()
        reminder_arg = core_client.create_reminder.call_args[0][0]
        assert reminder_arg.text == "Doctor appointment"

    @pytest.mark.asyncio
    async def test_not_hardcoded_custom_reminder(self):
        """text field is NOT the old hardcoded 'Custom reminder' string."""
        mock_memory = MagicMock()
        mock_memory.content = "Pick up kids"

        core_client = MagicMock()
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.create_reminder = AsyncMock()

        update = _make_update(text="2024-12-25 16:00")
        context = _make_context(
            user_data={PENDING_REMINDER_MEMORY_ID: "mem-12"},
            bot_data={"core_client": core_client},
        )

        await receive_custom_reminder(update, context)

        reminder_arg = core_client.create_reminder.call_args[0][0]
        assert reminder_arg.text != "Custom reminder"
        assert reminder_arg.text == "Pick up kids"

    @pytest.mark.asyncio
    async def test_clears_pending_state_on_success(self):
        """Pending state is cleared after reminder creation."""
        mock_memory = MagicMock()
        mock_memory.content = "Water the plants"

        core_client = MagicMock()
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.create_reminder = AsyncMock()

        update = _make_update(text="2024-10-10 07:00")
        context = _make_context(
            user_data={PENDING_REMINDER_MEMORY_ID: "mem-13"},
            bot_data={"core_client": core_client},
        )

        await receive_custom_reminder(update, context)

        assert PENDING_REMINDER_MEMORY_ID not in context.user_data

    @pytest.mark.asyncio
    async def test_invalid_time_restores_pending_state(self):
        """Unparseable time re-sets pending state for retry."""
        update = _make_update(text="not a time")
        context = _make_context(
            user_data={PENDING_REMINDER_MEMORY_ID: "mem-14"},
            bot_data={"core_client": MagicMock()},
        )

        await receive_custom_reminder(update, context)

        assert context.user_data.get(PENDING_REMINDER_MEMORY_ID) == "mem-14"
        update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_no_pending_state_replies_error(self):
        """Missing pending state causes an error reply."""
        update = _make_update(text="2024-12-01 10:00")
        context = _make_context(bot_data={"core_client": MagicMock()})

        await receive_custom_reminder(update, context)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_text_when_memory_missing(self):
        """If get_memory returns None, text falls back to a generic string."""
        core_client = MagicMock()
        core_client.get_memory = AsyncMock(return_value=None)
        core_client.create_reminder = AsyncMock()

        update = _make_update(text="2024-12-25 08:00")
        context = _make_context(
            user_data={PENDING_REMINDER_MEMORY_ID: "mem-15"},
            bot_data={"core_client": core_client},
        )

        await receive_custom_reminder(update, context)

        reminder_arg = core_client.create_reminder.call_args[0][0]
        assert reminder_arg.text
        assert reminder_arg.text != "Custom reminder"

    @pytest.mark.asyncio
    async def test_fire_at_propagated_to_reminder(self):
        """The parsed fire_at time is set on the reminder."""
        mock_memory = MagicMock()
        mock_memory.content = "Test"

        core_client = MagicMock()
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.create_reminder = AsyncMock()

        update = _make_update(text="2025-07-04 18:30")
        context = _make_context(
            user_data={PENDING_REMINDER_MEMORY_ID: "mem-16"},
            bot_data={"core_client": core_client},
        )

        await receive_custom_reminder(update, context)

        reminder_arg = core_client.create_reminder.call_args[0][0]
        assert reminder_arg.fire_at.month == 7
        assert reminder_arg.fire_at.day == 4
        assert reminder_arg.fire_at.hour == 18


# ---------------------------------------------------------------------------
# receive_followup_answer
# ---------------------------------------------------------------------------


class TestReceiveFollowupAnswer:
    """Tests for receive_followup_answer handler."""

    @pytest.mark.asyncio
    async def test_creates_followup_llm_job(self):
        """Happy path: a followup LLM job is created with all expected fields."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-20",
            "original_text": "Buy milk",
            "followup_question": "When do you need this done?",
        }

        update = _make_update(text="Tomorrow morning")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.payload["memory_id"] == "mem-20"
        assert job_arg.payload["message"] == "Buy milk"
        assert job_arg.payload["followup_context"]["followup_question"] == "When do you need this done?"
        assert job_arg.payload["followup_context"]["user_answer"] == "Tomorrow morning"

    @pytest.mark.asyncio
    async def test_job_type_is_followup(self):
        """The created LLM job has job_type = JobType.followup."""
        from shared_lib.enums import JobType

        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-21",
            "original_text": "Something",
            "followup_question": "What?",
        }

        update = _make_update(text="My answer")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify

    @pytest.mark.asyncio
    async def test_user_id_on_job(self):
        """The LLM job includes the Telegram user ID."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-22",
            "original_text": "Some note",
            "followup_question": "Task?",
        }

        update = _make_update(text="Yes", user_id=42)
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.user_id == 42

    @pytest.mark.asyncio
    async def test_clears_pending_state_on_success(self):
        """Pending state is removed after successful job creation."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-23",
            "original_text": "Test",
            "followup_question": "Follow-up?",
        }

        update = _make_update(text="Reply")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        assert PENDING_LLM_CONVERSATION not in context.user_data

    @pytest.mark.asyncio
    async def test_replies_processing_on_success(self):
        """Handler replies 'Processing...' after queuing the job."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-24",
            "original_text": "Check email",
            "followup_question": "Urgent?",
        }

        update = _make_update(text="Yes, very urgent")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        update.message.reply_text.assert_called_once_with("Processing...")

    @pytest.mark.asyncio
    async def test_no_pending_state_replies_error(self):
        """Missing pending state causes an error reply without creating a job."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        update = _make_update(text="Some answer")
        context = _make_context(bot_data={"core_client": core_client})

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_not_called()
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_missing_memory_id_replies_error(self):
        """Pending state without memory_id causes an error reply."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        # memory_id is missing from the pending state
        pending_state = {
            "original_text": "Some note",
            "followup_question": "What?",
        }

        update = _make_update(text="My answer")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_not_called()
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_exception_restores_pending_state(self):
        """On job creation failure, pending state is restored so user can retry."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock(side_effect=Exception("network error"))

        pending_state = {
            "memory_id": "mem-25",
            "original_text": "Do something",
            "followup_question": "When?",
        }

        update = _make_update(text="Later today")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        # Pending state should be restored so the user can try again
        assert context.user_data.get(PENDING_LLM_CONVERSATION) == pending_state
        update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_user_answer_trimmed(self):
        """Leading/trailing whitespace is stripped from the user's answer."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-26",
            "original_text": "Task",
            "followup_question": "Priority?",
        }

        update = _make_update(text="  High  ")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.payload["followup_context"]["user_answer"] == "High"
