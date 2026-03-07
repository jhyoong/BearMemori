"""Tests for multi-round followup conversation support.

Covers the bugs where:
1. consumer.py llm_followup_result handler does not update conversation state
   or LLM_CONVERSATION_METADATA, causing the next user reply to be enqueued
   as a new message instead of being treated as a conversation reply.
2. message.py handle_text hardcodes a 3-item conversation history instead of
   accumulating it across multiple followup rounds.
3. consumer.py ambiguous intent handler does not initialize conversation_history
   in LLM_CONVERSATION_METADATA.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from shared_lib.enums import JobType
from tg_gateway.consumer import _dispatch_notification
from tg_gateway.handlers.conversation import LLM_CONVERSATION_METADATA
from tg_gateway.handlers.message import handle_text

from telegram import Update
from telegram.ext import ContextTypes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_application(user_data: dict | None = None) -> MagicMock:
    """Return a mock Application with a mocked bot and user_data store."""
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.send_message = AsyncMock()
    app.user_data = user_data if user_data is not None else {}
    mock_core_client = MagicMock()
    mock_core_client.update_conversation_state = AsyncMock()
    mock_core_client.get_settings = AsyncMock(side_effect=Exception("no settings"))
    app.bot_data = {"core_client": mock_core_client}
    return app


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


def _make_core_client(active_conversation=None) -> MagicMock:
    """Return a mock CoreClient for handle_text tests."""
    client = MagicMock()
    client.ensure_user = AsyncMock()
    client.create_llm_job = AsyncMock()
    client.get_active_conversation = AsyncMock(return_value=active_conversation)
    client.reply_to_conversation = AsyncMock(return_value=MagicMock(history=[]))
    client.enqueue_message = AsyncMock(return_value=MagicMock(id="qi-1"))
    dequeue_item = MagicMock()
    dequeue_item.id = "qi-1"
    dequeue_resp = MagicMock()
    dequeue_resp.item = dequeue_item
    client.dequeue_message = AsyncMock(return_value=dequeue_resp)
    client.start_conversation = AsyncMock()
    client.get_settings = AsyncMock(side_effect=Exception("no settings"))
    qs = MagicMock()
    qs.queue_length = 1
    client.get_queue_status = AsyncMock(return_value=qs)
    return client


# ---------------------------------------------------------------------------
# Test 1: llm_followup_result should update conversation state
# ---------------------------------------------------------------------------


class TestFollowupResultUpdatesState:
    """Consumer llm_followup_result handler must set state to awaiting_reply."""

    @pytest.mark.asyncio
    async def test_followup_result_sets_conversation_state_to_awaiting_reply(self):
        """When llm_followup_result is received, conversation state must be
        updated to awaiting_reply so the next user message is treated as a reply."""
        app = _make_application(
            user_data={
                12345: {
                    LLM_CONVERSATION_METADATA: {
                        "memory_id": "mem-1",
                        "original_text": "exercise at 8pm",
                        "followup_question": "What kind?",
                    }
                }
            }
        )

        data = {
            "user_id": "12345",
            "message_type": "llm_followup_result",
            "content": {"question": "What type of exercise?"},
        }

        await _dispatch_notification(app, data)

        core_client = app.bot_data["core_client"]
        core_client.update_conversation_state.assert_called_once_with(
            12345,
            "awaiting_reply",
            history_entry={"role": "assistant", "content": "What type of exercise?"},
        )

    @pytest.mark.asyncio
    async def test_followup_result_updates_metadata_followup_question(self):
        """When llm_followup_result is received, the followup_question in
        LLM_CONVERSATION_METADATA must be updated to the new question."""
        app = _make_application(
            user_data={
                12345: {
                    LLM_CONVERSATION_METADATA: {
                        "memory_id": "mem-1",
                        "original_text": "exercise at 8pm",
                        "followup_question": "What kind?",
                    }
                }
            }
        )

        data = {
            "user_id": "12345",
            "message_type": "llm_followup_result",
            "content": {"question": "What type of exercise?"},
        }

        await _dispatch_notification(app, data)

        metadata = app.user_data[12345][LLM_CONVERSATION_METADATA]
        assert metadata["followup_question"] == "What type of exercise?"

    @pytest.mark.asyncio
    async def test_followup_result_appends_to_conversation_history(self):
        """When llm_followup_result is received, the new question must be
        appended to the conversation_history in metadata."""
        app = _make_application(
            user_data={
                12345: {
                    LLM_CONVERSATION_METADATA: {
                        "memory_id": "mem-1",
                        "original_text": "exercise at 8pm",
                        "followup_question": "What kind?",
                        "conversation_history": [
                            {"role": "user", "content": "exercise at 8pm"},
                            {"role": "assistant", "content": "What kind?"},
                            {"role": "user", "content": "running"},
                        ],
                    }
                }
            }
        )

        data = {
            "user_id": "12345",
            "message_type": "llm_followup_result",
            "content": {"question": "What type of exercise?"},
        }

        await _dispatch_notification(app, data)

        metadata = app.user_data[12345][LLM_CONVERSATION_METADATA]
        history = metadata["conversation_history"]
        assert len(history) == 4
        assert history[-1] == {
            "role": "assistant",
            "content": "What type of exercise?",
        }


# ---------------------------------------------------------------------------
# Test 2: handle_text should accumulate conversation history
# ---------------------------------------------------------------------------


class TestHandleTextAccumulatesHistory:
    """handle_text must use accumulated history from metadata, not hardcode."""

    @pytest.mark.asyncio
    async def test_second_round_reply_uses_accumulated_history(self):
        """When user replies in a second followup round, the LLM job should
        contain the full accumulated conversation history, not just 3 items."""
        active_conv = MagicMock()
        active_conv.state = "awaiting_reply"
        core_client = _make_core_client(active_conversation=active_conv)

        # Simulate second round: history already has 4 items (2 rounds of Q&A)
        existing_history = [
            {"role": "user", "content": "exercise at 8pm"},
            {"role": "assistant", "content": "What kind?"},
            {"role": "user", "content": "running"},
            {"role": "assistant", "content": "Indoor or outdoor?"},
        ]

        update = _make_update(text="outdoor", user_id=99)
        context = _make_context(
            user_data={
                LLM_CONVERSATION_METADATA: {
                    "memory_id": "mem-1",
                    "original_text": "exercise at 8pm",
                    "followup_question": "Indoor or outdoor?",
                    "conversation_history": list(existing_history),
                },
            },
            bot_data={"core_client": core_client},
        )

        await handle_text(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify

        followup_context = job_arg.payload["followup_context"]
        history = followup_context["conversation_history"]

        # Should have 5 items: the 4 existing + the new user answer
        assert len(history) == 5
        assert history[-1] == {"role": "user", "content": "outdoor"}
        # Earlier history should be preserved
        assert history[0] == {"role": "user", "content": "exercise at 8pm"}
        assert history[1] == {"role": "assistant", "content": "What kind?"}
        assert history[2] == {"role": "user", "content": "running"}
        assert history[3] == {"role": "assistant", "content": "Indoor or outdoor?"}

    @pytest.mark.asyncio
    async def test_first_round_reply_builds_history_from_scratch(self):
        """When no conversation_history exists in metadata (first round),
        the history should be built from original_text and followup_question."""
        active_conv = MagicMock()
        active_conv.state = "awaiting_reply"
        core_client = _make_core_client(active_conversation=active_conv)

        update = _make_update(text="running", user_id=99)
        context = _make_context(
            user_data={
                LLM_CONVERSATION_METADATA: {
                    "memory_id": "mem-1",
                    "original_text": "exercise at 8pm",
                    "followup_question": "What kind?",
                    # No conversation_history key
                },
            },
            bot_data={"core_client": core_client},
        )

        await handle_text(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        followup_context = job_arg.payload["followup_context"]
        history = followup_context["conversation_history"]

        assert len(history) == 3
        assert history[0] == {"role": "user", "content": "exercise at 8pm"}
        assert history[1] == {"role": "assistant", "content": "What kind?"}
        assert history[2] == {"role": "user", "content": "running"}


# ---------------------------------------------------------------------------
# Test 3: ambiguous intent should initialize conversation_history
# ---------------------------------------------------------------------------


class TestAmbiguousIntentInitializesHistory:
    """_handle_intent_result with intent=ambiguous must store conversation_history."""

    @pytest.mark.asyncio
    async def test_ambiguous_intent_stores_conversation_history(self):
        """When ambiguous intent is received, LLM_CONVERSATION_METADATA must
        include a conversation_history with the initial user message and
        the followup question."""
        from tg_gateway.consumer import _handle_intent_result

        app = _make_application()
        content = {
            "intent": "ambiguous",
            "query": "exercise at 8pm",
            "memory_id": "mem-1",
            "followup_question": "What kind of exercise?",
            "user_timezone": "UTC",
            "original_timestamp": "2024-01-15T10:30:00",
            "source_chat_id": "123",
            "source_message_id": "456",
        }

        await _handle_intent_result(app, "12345", content)

        metadata = app.user_data[12345][LLM_CONVERSATION_METADATA]
        assert "conversation_history" in metadata
        history = metadata["conversation_history"]
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "exercise at 8pm"}
        assert history[1] == {
            "role": "assistant",
            "content": "What kind of exercise?",
        }
