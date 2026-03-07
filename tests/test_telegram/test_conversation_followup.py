"""Tests for receive_followup_answer passing full context in LLM job payload.

This tests the behavior described in T006: Pass full context in followup LLM job payload.
When the user answers a followup question, the LLM job should include:
- user_timezone
- original_timestamp
- source_chat_id
- source_message_id
- conversation_history in followup_context
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from telegram import Update
from telegram.ext import ContextTypes

from tg_gateway.handlers.conversation import (
    PENDING_LLM_CONVERSATION,
    receive_followup_answer,
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


def _make_context(
    user_data: dict | None = None, bot_data: dict | None = None
) -> MagicMock:
    """Return a minimal mock context with controllable user_data and bot_data."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = user_data if user_data is not None else {}
    context.bot_data = bot_data if bot_data is not None else {}
    return context


# ---------------------------------------------------------------------------
# Tests for T006: Pass full context in followup LLM job payload
# ---------------------------------------------------------------------------


class TestFollowupAnswerFullContext:
    """Tests for full context fields in followup LLM job payload."""

    @pytest.mark.asyncio
    async def test_payload_includes_user_timezone(self):
        """Given a pending followup with user_timezone stored, when receive_followup_answer is called, then the LLM job payload should contain user_timezone."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-30",
            "original_text": "Buy milk",
            "followup_question": "When do you need this done?",
            "user_timezone": "America/New_York",
            "original_timestamp": "2024-01-15T10:00:00Z",
            "source_chat_id": 123456,
            "source_message_id": 789,
        }

        update = _make_update(text="Tomorrow morning")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert "user_timezone" in job_arg.payload, (
            "Payload should contain user_timezone"
        )
        assert job_arg.payload["user_timezone"] == "America/New_York"

    @pytest.mark.asyncio
    async def test_payload_includes_original_timestamp(self):
        """Given a pending followup with original_timestamp stored, when receive_followup_answer is called, then the LLM job payload should contain original_timestamp."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-31",
            "original_text": "Call John",
            "followup_question": "Priority?",
            "user_timezone": "Europe/London",
            "original_timestamp": "2024-02-20T14:30:00Z",
            "source_chat_id": 111,
            "source_message_id": 222,
        }

        update = _make_update(text="High priority")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert "original_timestamp" in job_arg.payload, (
            "Payload should contain original_timestamp"
        )
        assert job_arg.payload["original_timestamp"] == "2024-02-20T14:30:00Z"

    @pytest.mark.asyncio
    async def test_payload_includes_source_chat_id(self):
        """Given a pending followup with source_chat_id stored, when receive_followup_answer is called, then the LLM job payload should contain source_chat_id."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-32",
            "original_text": "Email boss",
            "followup_question": "When?",
            "user_timezone": "Asia/Tokyo",
            "original_timestamp": "2024-03-10T08:00:00Z",
            "source_chat_id": 999888,
            "source_message_id": 777666,
        }

        update = _make_update(text="Next Monday")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert "source_chat_id" in job_arg.payload, (
            "Payload should contain source_chat_id"
        )
        assert job_arg.payload["source_chat_id"] == 999888

    @pytest.mark.asyncio
    async def test_payload_includes_source_message_id(self):
        """Given a pending followup with source_message_id stored, when receive_followup_answer is called, then the LLM job payload should contain source_message_id."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-33",
            "original_text": "Buy groceries",
            "followup_question": "Budget?",
            "user_timezone": "UTC",
            "original_timestamp": "2024-04-05T12:00:00Z",
            "source_chat_id": 555,
            "source_message_id": 444333,
        }

        update = _make_update(text="$50")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert "source_message_id" in job_arg.payload, (
            "Payload should contain source_message_id"
        )
        assert job_arg.payload["source_message_id"] == 444333

    @pytest.mark.asyncio
    async def test_payload_includes_conversation_history(self):
        """Given a pending followup with all context fields stored, when receive_followup_answer is called, then the created LLMJobCreate payload should contain conversation_history in followup_context."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-34",
            "original_text": "Schedule meeting",
            "followup_question": "What time?",
            "user_timezone": "America/Los_Angeles",
            "original_timestamp": "2024-05-01T09:00:00Z",
            "source_chat_id": 123456789,
            "source_message_id": 987654321,
        }

        update = _make_update(text="3pm")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]

        assert "followup_context" in job_arg.payload
        followup_context = job_arg.payload["followup_context"]
        assert "conversation_history" in followup_context, (
            "followup_context should contain conversation_history"
        )

        # Verify the conversation_history has 3 messages
        conversation_history = followup_context["conversation_history"]
        assert len(conversation_history) == 3, (
            "conversation_history should have exactly 3 messages"
        )

        # Verify the structure of each message
        assert conversation_history[0] == {
            "role": "user",
            "content": "Schedule meeting",
        }
        assert conversation_history[1] == {"role": "assistant", "content": "What time?"}
        assert conversation_history[2] == {"role": "user", "content": "3pm"}

    @pytest.mark.asyncio
    async def test_payload_with_all_context_fields(self):
        """Given a pending followup with all context fields stored, when receive_followup_answer is called, then the created LLMJobCreate payload should contain all required fields: user_timezone, original_timestamp, source_chat_id, source_message_id, and conversation_history."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-35",
            "original_text": "Remember to call mom",
            "followup_question": "When?",
            "user_timezone": "Europe/Berlin",
            "original_timestamp": "2024-06-15T18:00:00Z",
            "source_chat_id": 111222333,
            "source_message_id": 444555666,
        }

        update = _make_update(text="Sunday")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]

        # Check all top-level fields
        assert job_arg.payload["user_timezone"] == "Europe/Berlin"
        assert job_arg.payload["original_timestamp"] == "2024-06-15T18:00:00Z"
        assert job_arg.payload["source_chat_id"] == 111222333
        assert job_arg.payload["source_message_id"] == 444555666

        # Check conversation_history in followup_context
        conv_history = job_arg.payload["followup_context"]["conversation_history"]
        assert len(conv_history) == 3
        assert conv_history[0] == {"role": "user", "content": "Remember to call mom"}
        assert conv_history[1] == {"role": "assistant", "content": "When?"}
        assert conv_history[2] == {"role": "user", "content": "Sunday"}


class TestFollowupAnswerTimezoneEdgeCases:
    """Tests for edge cases with user_timezone in followup LLM job payload."""

    @pytest.mark.asyncio
    async def test_handles_none_user_timezone(self):
        """Given user_timezone is None, then should still create job with default or empty timezone."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        pending_state = {
            "memory_id": "mem-36",
            "original_text": "Test note",
            "followup_question": "Important?",
            "user_timezone": None,
            "original_timestamp": "2024-07-01T10:00:00Z",
            "source_chat_id": 100,
            "source_message_id": 200,
        }

        update = _make_update(text="Yes")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        # Should include user_timezone key, even if value is None
        assert "user_timezone" in job_arg.payload
        # The value can be None or some default
        assert (
            job_arg.payload["user_timezone"] is None
            or job_arg.payload["user_timezone"] == ""
        )

    @pytest.mark.asyncio
    async def test_handles_missing_context_fields(self):
        """Given pending followup with missing optional fields, should still create job with available data."""
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        # Only minimal required fields
        pending_state = {
            "memory_id": "mem-37",
            "original_text": "Quick note",
            "followup_question": "OK?",
        }

        update = _make_update(text="Sure")
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        # Should still have conversation_history even without other context
        assert "followup_context" in job_arg.payload
        assert "conversation_history" in job_arg.payload["followup_context"]
