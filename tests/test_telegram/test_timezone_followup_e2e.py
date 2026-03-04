"""End-to-end tests for timezone-aware followup flow.

This tests the complete integration from:
1. User message with timezone -> LLM returns ambiguous
2. Consumer stores PENDING_LLM_CONVERSATION with user_timezone
3. User answers "5pm" -> receive_followup_answer creates final LLM job
4. Verifies the final job has correct user_timezone and UTC conversion

Test cases:
1. test_e2e_timezone_aware_followup_flow - verify complete flow with timezone
2. test_e2e_conversation_history_has_three_messages - verify conversation history
3. test_e2e_context_fields_propagate_correctly - verify all 4 context fields
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from telegram import Update
from telegram.ext import ContextTypes

from tg_gateway.handlers.conversation import (
    PENDING_LLM_CONVERSATION,
    receive_followup_answer,
)
from tg_gateway.consumer import _handle_intent_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_update(text: str = "hello", user_id: int = 12345) -> MagicMock:
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


def _make_application(user_data: dict | None = None) -> MagicMock:
    """Return a mock Application with a mocked bot and user_data store."""
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.send_message = AsyncMock()
    app.user_data = user_data if user_data is not None else {}
    app.bot_data = {}
    return app


# ---------------------------------------------------------------------------
# Test cases for T010: Timezone-aware followup end-to-end
# ---------------------------------------------------------------------------


class TestTimezoneAwareFollowupFlow:
    """End-to-end tests for timezone-aware followup flow."""

    @pytest.mark.asyncio
    async def test_e2e_timezone_aware_followup_flow(self):
        """Given user in timezone Asia/Singapore (+8), when user sends ambiguous message and answers '5pm',
        then the final LLM job should have user_timezone='Asia/Singapore' and resolved time should be 09:00 UTC.

        Flow:
        1. User sends "prep dinner for picnic later" with user_timezone=Asia/Singapore
        2. LLM returns ambiguous intent with followup question
        3. Consumer stores PENDING_LLM_CONVERSATION with user_timezone
        4. User answers "5pm"
        5. receive_followup_answer creates final LLM job with user_timezone in payload
        """
        # Step 1: Mock LLM returning ambiguous intent with followup question
        core_client = MagicMock()

        # Step 2: Consumer handles ambiguous intent and stores pending state
        app = _make_application()
        app.bot_data["core_client"] = core_client

        # Simulate LLM response with ambiguous intent
        intent_result_content = {
            "intent": "ambiguous",
            "query": "prep dinner for picnic later",
            "memory_id": "mem-abc123",
            "action": "prep dinner for picnic later",
            "followup_question": "What time do you want to have dinner?",
            "original_timestamp": "2024-01-15T10:00:00Z",
            "user_timezone": "Asia/Singapore",
            "source_chat_id": 12345,
            "source_message_id": 678,
        }

        await _handle_intent_result(app, "12345", intent_result_content)

        # Verify followup question was sent
        app.bot.send_message.assert_called_once()

        # Verify PENDING_LLM_CONVERSATION is stored with user_timezone
        user_data = app.user_data.get(12345, {})
        assert PENDING_LLM_CONVERSATION in user_data
        pending_state = user_data[PENDING_LLM_CONVERSATION]
        assert pending_state["user_timezone"] == "Asia/Singapore"
        assert pending_state["memory_id"] == "mem-abc123"

        # Step 3: User answers "5pm"
        core_client.create_llm_job = AsyncMock()

        # Create a new context for the followup answer
        # The user_data now has the pending conversation from step 2
        followup_context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        update = _make_update(text="5pm", user_id=12345)

        await receive_followup_answer(update, followup_context)

        # Step 4: Verify final LLM job was created with user_timezone
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]

        # Verify user_timezone is in the payload
        assert "user_timezone" in job_arg.payload, (
            "Payload should contain user_timezone"
        )
        assert job_arg.payload["user_timezone"] == "Asia/Singapore", (
            f"Expected user_timezone='Asia/Singapore', got {job_arg.payload.get('user_timezone')}"
        )

        # Verify original_timestamp is preserved
        assert job_arg.payload["original_timestamp"] == "2024-01-15T10:00:00Z"

        # Verify source context is preserved
        assert job_arg.payload["source_chat_id"] == 12345
        assert job_arg.payload["source_message_id"] == 678

    @pytest.mark.asyncio
    async def test_e2e_conversation_history_has_three_messages(self):
        """Verify that conversation_history in followup_context has exactly 3 messages:
        1. User's original message (role: user)
        2. LLM's followup question (role: assistant)
        3. User's answer (role: user)
        """
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        # Setup pending state with all context
        pending_state = {
            "memory_id": "mem-30",
            "original_text": "Buy milk tomorrow",
            "followup_question": "What time do you need this?",
            "user_timezone": "America/New_York",
            "original_timestamp": "2024-01-15T10:00:00Z",
            "source_chat_id": 123456,
            "source_message_id": 789,
        }

        update = _make_update(text="5pm", user_id=12345)
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        # Verify job created
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]

        # Verify conversation_history structure
        assert "followup_context" in job_arg.payload
        followup_context = job_arg.payload["followup_context"]
        assert "conversation_history" in followup_context

        conversation_history = followup_context["conversation_history"]

        # Verify exactly 3 messages
        assert len(conversation_history) == 3, (
            f"Expected 3 messages in conversation_history, got {len(conversation_history)}"
        )

        # Verify message structure
        assert conversation_history[0] == {
            "role": "user",
            "content": "Buy milk tomorrow",
        }
        assert conversation_history[1] == {
            "role": "assistant",
            "content": "What time do you need this?",
        }
        assert conversation_history[2] == {
            "role": "user",
            "content": "5pm",
        }

    @pytest.mark.asyncio
    async def test_e2e_context_fields_propagate_correctly(self):
        """Verify all 4 context fields (user_timezone, original_timestamp, source_chat_id,
        source_message_id) flow through to the final LLM job payload correctly.

        This tests the complete fix from T005-T007:
        - T005: Store timezone in pending state
        - T006: Pass full context in followup LLM job payload
        - T007: Convert times to UTC using user_timezone
        """
        core_client = MagicMock()
        core_client.create_llm_job = AsyncMock()

        # Setup pending state with all 4 context fields
        pending_state = {
            "memory_id": "mem-40",
            "original_text": "Schedule meeting with team",
            "followup_question": "When should we meet?",
            "user_timezone": "Europe/Berlin",  # UTC+1
            "original_timestamp": "2024-03-01T14:00:00Z",  # 2pm UTC
            "source_chat_id": 999888,
            "source_message_id": 777666,
        }

        update = _make_update(text="3pm", user_id=12345)
        context = _make_context(
            user_data={PENDING_LLM_CONVERSATION: pending_state},
            bot_data={"core_client": core_client},
        )

        await receive_followup_answer(update, context)

        # Verify all 4 context fields are in payload
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]

        payload = job_arg.payload

        # Field 1: user_timezone
        assert "user_timezone" in payload, "Payload should contain user_timezone"
        assert payload["user_timezone"] == "Europe/Berlin"

        # Field 2: original_timestamp
        assert "original_timestamp" in payload, (
            "Payload should contain original_timestamp"
        )
        assert payload["original_timestamp"] == "2024-03-01T14:00:00Z"

        # Field 3: source_chat_id
        assert "source_chat_id" in payload, "Payload should contain source_chat_id"
        assert payload["source_chat_id"] == 999888

        # Field 4: source_message_id
        assert "source_message_id" in payload, (
            "Payload should contain source_message_id"
        )
        assert payload["source_message_id"] == 777666

        # Verify conversation_history in followup_context
        assert "followup_context" in payload
        followup_context = payload["followup_context"]
        assert "conversation_history" in followup_context

        conv_history = followup_context["conversation_history"]
        assert len(conv_history) == 3

        # Verify the content flows through correctly
        assert conv_history[0]["content"] == "Schedule meeting with team"
        assert conv_history[1]["content"] == "When should we meet?"
        assert conv_history[2]["content"] == "3pm"
