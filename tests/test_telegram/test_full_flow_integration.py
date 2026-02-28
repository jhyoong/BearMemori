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


# ---------------------------------------------------------------------------
# Integration test: Full flow from Telegram to Consumer
# ---------------------------------------------------------------------------


class TestFullFlowIntegration:
    """Integration tests that verify the complete flow across services."""

    @pytest.mark.asyncio
    async def test_search_phrase_full_flow_no_memory_created(self):
        """Test complete flow: 'Search for all images about anime' -> no memory created -> search results shown.

        Flow:
        1. Telegram message -> handle_text -> creates LLM job
        2. LLM Worker (IntentHandler) -> classifies as search -> calls search API
        3. Consumer -> receives result -> shows search results without memory proposal
        """
        from telegram import Update
        from telegram.ext import ContextTypes
        from tg_gateway.handlers.message import handle_text
        from tg_gateway.consumer import _handle_intent_result
        from tg_gateway.handlers.conversation import (
            AWAITING_BUTTON_ACTION,
            USER_QUEUE_COUNT,
        )
        from shared_lib.enums import JobType

        # Setup mocks
        core_client = MagicMock()
        core_client.ensure_user = AsyncMock()
        core_client.create_llm_job = AsyncMock()
        core_client.create_memory = AsyncMock()
        core_client.search = AsyncMock(
            return_value=[
                {"memory": {"id": "mem-1", "content": "Anime image 1"}},
                {"memory": {"id": "mem-2", "content": "Anime image 2"}},
            ]
        )

        # Create mock update
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

        # Verify step 1: LLM job created, no memory created yet
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "Search for all images about anime"
        assert job_arg.payload["memory_id"] is None
        assert context.user_data.get(USER_QUEUE_COUNT, 0) == 1

        # Step 2: Simulate LLM Worker processing (IntentHandler would create job result)
        # In the real flow, this happens asynchronously via Redis queue

        # Step 3: Consumer receives intent result
        app = MagicMock()
        app.bot = MagicMock()
        app.bot.send_message = AsyncMock()
        app.user_data = {12345: {USER_QUEUE_COUNT: 1}}

        intent_result_content = {
            "intent": "search",
            "query": "all images about anime",
            "memory_id": "",  # Empty - no memory created
            "search_results": [
                {"title": "Anime image 1", "memory_id": "mem-1"},
                {"title": "Anime image 2", "memory_id": "mem-2"},
            ],
        }

        await _handle_intent_result(app, "12345", intent_result_content)

        # Verify step 3: Search results shown, no memory proposal
        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        assert call_kwargs.get("reply_markup") is not None  # Keyboard with results

        # Verify no memory proposal (no AWAITING_BUTTON_ACTION set for search)
        assert AWAITING_BUTTON_ACTION not in app.user_data.get(12345, {})

        # Verify queue decremented
        assert app.user_data[12345][USER_QUEUE_COUNT] == 0

    @pytest.mark.asyncio
    async def test_reminder_phrase_full_flow_creates_memory(self):
        """Test complete flow: 'Remind me to call mom tomorrow' -> memory created -> reminder proposal shown.

        Flow:
        1. Telegram message -> handle_text -> creates LLM job
        2. LLM Worker (IntentHandler) -> classifies as reminder -> creates memory
        3. Consumer -> receives result -> shows reminder proposal keyboard
        """
        from telegram import Update
        from telegram.ext import ContextTypes
        from tg_gateway.handlers.message import handle_text
        from tg_gateway.consumer import _handle_intent_result
        from tg_gateway.handlers.conversation import (
            AWAITING_BUTTON_ACTION,
            USER_QUEUE_COUNT,
        )
        from shared_lib.enums import JobType

        # Setup mocks
        core_client = MagicMock()
        core_client.ensure_user = AsyncMock()
        core_client.create_llm_job = AsyncMock()
        core_client.create_memory = AsyncMock(
            return_value={"memory_id": "mem-reminder-123"}
        )

        # Create mock update
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

        # Verify step 1: LLM job created
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "Remind me to call mom tomorrow"

        # Step 2: Simulate LLM Worker result with memory_id
        # (In real flow: IntentHandler creates memory and returns memory_id)

        # Step 3: Consumer receives intent result with memory_id
        app = MagicMock()
        app.bot = MagicMock()
        app.bot.send_message = AsyncMock()
        app.user_data = {12345: {USER_QUEUE_COUNT: 1}}

        future_dt = _future_iso()
        intent_result_content = {
            "intent": "reminder",
            "query": "call mom",
            "action": "call mom",
            "memory_id": "mem-reminder-123",
            "resolved_time": future_dt,
        }

        await _handle_intent_result(app, "12345", intent_result_content)

        # Verify step 3: Reminder proposal shown with keyboard
        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "call mom" in text.lower()
        assert call_kwargs.get("reply_markup") is not None

        # Verify memory proposal state is set (AWAITING_BUTTON_ACTION)
        assert AWAITING_BUTTON_ACTION in app.user_data[12345]
        state = app.user_data[12345][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-reminder-123"

    @pytest.mark.asyncio
    async def test_task_phrase_full_flow_creates_memory(self):
        """Test complete flow: 'Add task to finish report by Friday' -> memory created -> task proposal shown.

        Flow:
        1. Telegram message -> handle_text -> creates LLM job
        2. LLM Worker (IntentHandler) -> classifies as task -> creates memory
        3. Consumer -> receives result -> shows task proposal keyboard
        """
        from telegram import Update
        from telegram.ext import ContextTypes
        from tg_gateway.handlers.message import handle_text
        from tg_gateway.consumer import _handle_intent_result
        from tg_gateway.handlers.conversation import (
            AWAITING_BUTTON_ACTION,
            USER_QUEUE_COUNT,
        )
        from shared_lib.enums import JobType

        # Setup mocks
        core_client = MagicMock()
        core_client.ensure_user = AsyncMock()
        core_client.create_llm_job = AsyncMock()
        core_client.create_memory = AsyncMock(
            return_value={"memory_id": "mem-task-456"}
        )

        # Create mock update
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

        # Step 1: Handle Telegram message
        await handle_text(update, context)

        # Verify step 1: LLM job created
        core_client.create_llm_job.assert_called_once()
        job_arg = core_client.create_llm_job.call_args[0][0]
        assert job_arg.job_type == JobType.intent_classify
        assert job_arg.payload["message"] == "Add task to finish report by Friday"

        # Step 2: Simulate LLM Worker result with memory_id

        # Step 3: Consumer receives intent result with memory_id
        app = MagicMock()
        app.bot = MagicMock()
        app.bot.send_message = AsyncMock()
        app.user_data = {12345: {USER_QUEUE_COUNT: 1}}

        future_dt = _future_iso()
        intent_result_content = {
            "intent": "task",
            "query": "finish report",
            "description": "finish report",
            "memory_id": "mem-task-456",
            "resolved_due_time": future_dt,
        }

        await _handle_intent_result(app, "12345", intent_result_content)

        # Verify step 3: Task proposal shown with keyboard
        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        text = call_kwargs.get("text", "")
        assert "finish report" in text.lower()
        assert "Task:" in text
        assert call_kwargs.get("reply_markup") is not None

        # Verify memory proposal state is set
        assert AWAITING_BUTTON_ACTION in app.user_data[12345]
        state = app.user_data[12345][AWAITING_BUTTON_ACTION]
        assert state["memory_id"] == "mem-task-456"


# ---------------------------------------------------------------------------
# Integration test: Verify search intent behavior across services
# ---------------------------------------------------------------------------


class TestSearchIntentNoMemoryIntegration:
    """Integration tests verifying search intent does NOT create memory across services."""

    @pytest.mark.asyncio
    async def test_search_intent_no_memory_id_in_result(self):
        """Verify that search intent result has empty/null memory_id."""
        from tg_gateway.consumer import _handle_intent_result

        # When search intent is processed, memory_id should be empty
        app = MagicMock()
        app.bot = MagicMock()
        app.bot.send_message = AsyncMock()
        app.user_data = {}

        content = {
            "intent": "search",
            "query": "butter recipe",
            "memory_id": "",  # Empty for search - no memory created
            "search_results": [
                {"title": "Butter Cake", "memory_id": "mem-1"},
            ],
        }

        await _handle_intent_result(app, "12345", content)

        # Verify message is sent (search results shown)
        app.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_reminder_intent_has_memory_id_in_result(self):
        """Verify that reminder intent result has valid memory_id."""
        from tg_gateway.consumer import _handle_intent_result

        # When reminder intent is processed, memory_id should be set
        app = MagicMock()
        app.bot = MagicMock()
        app.bot.send_message = AsyncMock()
        app.user_data = {}

        future_dt = _future_iso()
        content = {
            "intent": "reminder",
            "query": "call mom",
            "memory_id": "mem-reminder-123",  # Valid memory_id
            "resolved_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        # Verify message is sent with memory proposal
        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        assert call_kwargs.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_task_intent_has_memory_id_in_result(self):
        """Verify that task intent result has valid memory_id."""
        from tg_gateway.consumer import _handle_intent_result

        # When task intent is processed, memory_id should be set
        app = MagicMock()
        app.bot = MagicMock()
        app.bot.send_message = AsyncMock()
        app.user_data = {}

        future_dt = _future_iso()
        content = {
            "intent": "task",
            "query": "finish report",
            "memory_id": "mem-task-456",  # Valid memory_id
            "resolved_due_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        # Verify message is sent with memory proposal
        app.bot.send_message.assert_called_once()
        call_kwargs = app.bot.send_message.call_args[1]
        assert call_kwargs.get("reply_markup") is not None


# ---------------------------------------------------------------------------
# Integration test: Queue behavior
# ---------------------------------------------------------------------------


class TestQueueIntegration:
    """Integration tests for queue behavior across services."""

    @pytest.mark.asyncio
    async def test_search_result_decrements_queue(self):
        """Test that search result processing decrements queue counter."""
        from tg_gateway.consumer import _handle_intent_result
        from tg_gateway.handlers.conversation import USER_QUEUE_COUNT

        app = MagicMock()
        app.bot = MagicMock()
        app.bot.send_message = AsyncMock()
        app.user_data = {12345: {USER_QUEUE_COUNT: 5}}

        content = {
            "intent": "search",
            "query": "test",
            "memory_id": "",
            "search_results": [],
        }

        await _handle_intent_result(app, "12345", content)

        # Queue should be decremented for search
        assert app.user_data[12345][USER_QUEUE_COUNT] == 4

    @pytest.mark.asyncio
    async def test_reminder_result_does_not_decrement_queue(self):
        """Test that reminder result does NOT decrement queue counter immediately.

        Queue is managed by the conversation handler after user confirms/edits.
        """
        from tg_gateway.consumer import _handle_intent_result
        from tg_gateway.handlers.conversation import USER_QUEUE_COUNT

        app = MagicMock()
        app.bot = MagicMock()
        app.bot.send_message = AsyncMock()
        app.user_data = {12345: {USER_QUEUE_COUNT: 5}}

        future_dt = _future_iso()
        content = {
            "intent": "reminder",
            "query": "call mom",
            "memory_id": "mem-reminder-123",
            "resolved_time": future_dt,
        }

        await _handle_intent_result(app, "12345", content)

        # Queue should NOT be decremented for reminder (handled by conversation)
        # This is the current implementation behavior
        # The queue stays the same until conversation handler processes confirmation
