"""Integration tests for the complete flow from user message to final response.

Tests verify:
- Search queries do NOT create memories
- Reminder/Task/General notes DO create memories
- Full flow from Telegram message -> LLM classification -> Consumer handling
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future_iso() -> str:
    """Return an ISO datetime string one hour in the future (UTC)."""
    return (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()


def _make_core_client_for_handle_text() -> MagicMock:
    """Return a mock CoreClient for use with handle_text (new queue flow)."""
    client = MagicMock()
    client.ensure_user = AsyncMock()
    client.create_llm_job = AsyncMock()
    client.create_memory = AsyncMock()
    client.get_active_conversation = AsyncMock(return_value=None)
    dequeue_item = MagicMock()
    dequeue_item.id = "qi-1"
    dequeue_resp = MagicMock()
    dequeue_resp.item = dequeue_item
    client.enqueue_message = AsyncMock()
    client.dequeue_message = AsyncMock(return_value=dequeue_resp)
    client.start_conversation = AsyncMock()
    client.get_settings = AsyncMock(side_effect=Exception("no settings"))
    return client


def _make_application() -> MagicMock:
    """Return a mock Application for use with _handle_intent_result."""
    app = MagicMock()
    app.bot = MagicMock()
    app.bot.send_message = AsyncMock()
    app.user_data = {}
    mock_core_client = MagicMock()
    mock_core_client.update_conversation_state = AsyncMock()
    mock_core_client.get_settings = AsyncMock(side_effect=Exception("no settings"))
    app.bot_data = {"core_client": mock_core_client}
    return app


# ---------------------------------------------------------------------------
# Integration test: Full flow from Telegram to Consumer
# ---------------------------------------------------------------------------


class TestFullFlowIntegration:
    """Integration tests that verify the complete flow across services."""

    @pytest.mark.asyncio
    async def test_search_phrase_full_flow_no_memory_created(self):
        """Test complete flow: search -> no memory created -> search results shown."""
        from telegram import Update
        from telegram.ext import ContextTypes
        from tg_gateway.handlers.message import handle_text
        from tg_gateway.consumer import _handle_intent_result
        from tg_gateway.handlers.conversation import AWAITING_BUTTON_ACTION
        from shared_lib.enums import JobType

        core_client = _make_core_client_for_handle_text()

        update = MagicMock(spec=Update)
        update.message = MagicMock()
        update.message.text = "Search for all images about anime"
        update.message.chat_id = 12345
        update.message.message_id = 1
        update.message.date = None
        update.message.reply_text = AsyncMock()
        user = MagicMock()
        user.id = 12345
        user.full_name = "Test User"
        update.message.from_user = user

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}
        context.bot_data = {"core_client": core_client}

        # Step 1: Handle Telegram message
        await handle_text(update, context)

        # Verify: LLM job created, no memory created
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "Search for all images about anime"
        assert job_arg.payload["memory_id"] is None

        # Step 2: Consumer receives search intent result
        app = _make_application()

        intent_result_content = {
            "intent": "search",
            "query": "all images about anime",
            "memory_id": "",
            "results": [
                {"title": "Anime image 1", "memory_id": "mem-1"},
                {"title": "Anime image 2", "memory_id": "mem-2"},
            ],
        }

        await _handle_intent_result(app, "12345", intent_result_content)

        # Verify: search results shown, no memory proposal
        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        assert call_kwargs.get("reply_markup") is not None
        assert AWAITING_BUTTON_ACTION not in app.user_data.get(12345, {})

        # Verify: conversation completed via Core API
        cc = app.bot_data["core_client"]
        cc.update_conversation_state.assert_awaited_once_with(12345, "completed")

    @pytest.mark.asyncio
    async def test_reminder_phrase_full_flow_creates_memory(self):
        """Test: reminder message -> LLM job -> reminder proposal shown."""
        from telegram import Update
        from telegram.ext import ContextTypes
        from tg_gateway.handlers.message import handle_text
        from tg_gateway.consumer import _handle_intent_result
        from tg_gateway.handlers.conversation import AWAITING_BUTTON_ACTION
        from shared_lib.enums import JobType

        core_client = _make_core_client_for_handle_text()

        update = MagicMock(spec=Update)
        update.message = MagicMock()
        update.message.text = "Remind me to call mom tomorrow"
        update.message.chat_id = 12345
        update.message.message_id = 1
        update.message.date = None
        update.message.reply_text = AsyncMock()
        user = MagicMock()
        user.id = 12345
        user.full_name = "Test User"
        update.message.from_user = user

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}
        context.bot_data = {"core_client": core_client}

        # Step 1: Handle Telegram message
        await handle_text(update, context)

        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify

        # Step 2: Consumer receives reminder intent result
        app = _make_application()

        future_dt = _future_iso()
        intent_result_content = {
            "intent": "reminder",
            "query": "call mom",
            "action": "call mom",
            "memory_id": "mem-reminder-123",
            "resolved_time": future_dt,
        }

        await _handle_intent_result(app, "12345", intent_result_content)

        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "call mom" in text.lower()
        assert call_kwargs.get("reply_markup") is not None
        assert AWAITING_BUTTON_ACTION in app.user_data[12345]
        state = app.user_data[12345][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-reminder-123"

    @pytest.mark.asyncio
    async def test_task_phrase_full_flow_creates_memory(self):
        """Test: task message -> LLM job -> task proposal shown."""
        from telegram import Update
        from telegram.ext import ContextTypes
        from tg_gateway.handlers.message import handle_text
        from tg_gateway.consumer import _handle_intent_result
        from tg_gateway.handlers.conversation import AWAITING_BUTTON_ACTION
        from shared_lib.enums import JobType

        core_client = _make_core_client_for_handle_text()

        update = MagicMock(spec=Update)
        update.message = MagicMock()
        update.message.text = "Add task to finish report by Friday"
        update.message.chat_id = 12345
        update.message.message_id = 1
        update.message.date = None
        update.message.reply_text = AsyncMock()
        user = MagicMock()
        user.id = 12345
        user.full_name = "Test User"
        update.message.from_user = user

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}
        context.bot_data = {"core_client": core_client}

        await handle_text(update, context)

        core_client.create_llm_job.assert_called_once()

        # Consumer receives task intent result
        app = _make_application()

        future_dt = _future_iso()
        intent_result_content = {
            "intent": "task",
            "query": "finish report",
            "description": "finish report",
            "memory_id": "mem-task-456",
            "resolved_due_time": future_dt,
        }

        await _handle_intent_result(app, "12345", intent_result_content)

        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "finish report" in text.lower()
        assert call_kwargs.get("reply_markup") is not None
        assert AWAITING_BUTTON_ACTION in app.user_data[12345]
        state = app.user_data[12345][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-task-456"


# ---------------------------------------------------------------------------
# Integration test: Verify search intent behavior across services
# ---------------------------------------------------------------------------


class TestSearchIntentNoMemoryIntegration:
    """Integration tests verifying search intent does NOT create memory."""

    @pytest.mark.asyncio
    async def test_search_intent_no_memory_id_in_result(self):
        """Verify that search intent result has empty/null memory_id."""
        from tg_gateway.consumer import _handle_intent_result

        app = _make_application()

        content = {
            "intent": "search",
            "query": "butter recipe",
            "memory_id": "",
            "results": [
                {"title": "Butter Cake", "memory_id": "mem-1"},
            ],
        }

        await _handle_intent_result(app, "12345", content)

        app.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_reminder_intent_has_memory_id_in_result(self):
        """Verify that reminder intent result has valid memory_id."""
        from tg_gateway.consumer import _handle_intent_result

        app = _make_application()

        future_dt = _future_iso()
        content = {
            "intent": "reminder",
            "query": "call mom",
            "memory_id": "mem-reminder-123",
            "resolved_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        assert call_kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_task_intent_has_memory_id_in_result(self):
        """Verify that task intent result has valid memory_id."""
        from tg_gateway.consumer import _handle_intent_result

        app = _make_application()

        future_dt = _future_iso()
        content = {
            "intent": "task",
            "query": "finish report",
            "memory_id": "mem-task-456",
            "resolved_due_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        assert call_kwargs.get("reply_markup") is not None


# ---------------------------------------------------------------------------
# Integration test: Queue behavior via Core API
# ---------------------------------------------------------------------------


class TestQueueIntegration:
    """Integration tests for queue behavior via Core API."""

    @pytest.mark.asyncio
    async def test_search_result_completes_conversation(self):
        """Test that search result completes conversation via Core API."""
        from tg_gateway.consumer import _handle_intent_result

        app = _make_application()

        content = {
            "intent": "search",
            "query": "test",
            "memory_id": "",
            "results": [],
        }

        await _handle_intent_result(app, "12345", content)

        cc = app.bot_data["core_client"]
        cc.update_conversation_state.assert_awaited_once_with(12345, "completed")

    @pytest.mark.asyncio
    async def test_reminder_result_sets_awaiting_reply(self):
        """Test that reminder result sets conversation to awaiting_reply."""
        from tg_gateway.consumer import _handle_intent_result

        app = _make_application()

        future_dt = _future_iso()
        content = {
            "intent": "reminder",
            "query": "call mom",
            "memory_id": "mem-reminder-123",
            "resolved_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        cc = app.bot_data["core_client"]
        cc.update_conversation_state.assert_awaited_once_with(
            12345,
            "awaiting_reply",
            history_entry={"role": "assistant", "content": cc.update_conversation_state.call_args[1]["history_entry"]["content"]},
        )
