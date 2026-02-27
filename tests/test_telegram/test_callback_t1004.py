"""Tests for the callback "custom" choice parsing fix (T1004).

Tests to verify that "custom" callback choice unambiguously routes to
the correct handler (ReminderTimeChoice, not DueDateChoice).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update
from telegram.ext import ContextTypes

from tg_gateway.handlers.callback import (
    _parse_callback_data,
    handle_callback,
)
from tg_gateway.callback_data import (
    DueDateChoice,
    ReminderTimeChoice,
)
from tg_gateway.handlers.conversation import (
    PENDING_TASK_MEMORY_ID,
    PENDING_REMINDER_MEMORY_ID,
)


class TestCustomChoiceParsing:
    """Tests for _parse_callback_data with 'custom' choice (T1004)."""

    def test_custom_choice_parses_as_reminder_time_choice(self):
        """Test that 'custom' choice parses as ReminderTimeChoice, not DueDateChoice.

        This is the key fix for T1004: "custom" should unambiguously route to
        reminder time flow, not task/due-date flow.
        """
        result = _parse_callback_data('{"memory_id": "1", "choice": "custom"}')

        assert isinstance(result, ReminderTimeChoice), (
            f"'custom' choice should parse as ReminderTimeChoice, "
            f"but got {type(result).__name__}"
        )
        assert result.choice == "custom"
        assert result.memory_id == "1"

    def test_custom_choice_does_not_parse_as_due_date_choice(self):
        """Test that 'custom' choice does NOT parse as DueDateChoice."""
        result = _parse_callback_data('{"memory_id": "1", "choice": "custom"}')

        assert not isinstance(result, DueDateChoice), (
            "'custom' choice should NOT parse as DueDateChoice"
        )

    def test_due_date_choices_still_work(self):
        """Test that non-custom due date choices still parse correctly."""
        due_date_choices = ["today", "tomorrow", "next_week", "no_date"]
        for choice in due_date_choices:
            result = _parse_callback_data(f'{{"memory_id": "1", "choice": "{choice}"}}')
            assert isinstance(result, DueDateChoice), (
                f"'{choice}' should parse as DueDateChoice"
            )
            assert result.choice == choice

    def test_reminder_time_choices_still_work(self):
        """Test that non-custom reminder time choices still parse correctly."""
        reminder_time_choices = ["1h", "tomorrow_9am"]
        for choice in reminder_time_choices:
            result = _parse_callback_data(f'{{"memory_id": "1", "choice": "{choice}"}}')
            assert isinstance(result, ReminderTimeChoice), (
                f"'{choice}' should parse as ReminderTimeChoice"
            )
            assert result.choice == choice


class TestCustomChoiceDispatch:
    """Tests for callback dispatch with 'custom' choice (T1004)."""

    @pytest.fixture
    def mock_update(self):
        """Create a mock update with callback query."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.message = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 12345
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        core_client = MagicMock()
        core_client.update_memory = AsyncMock()
        core_client.get_memory = AsyncMock()
        context.bot_data = {"core_client": core_client}
        context.user_data = {}
        return context

    @pytest.mark.asyncio
    async def test_custom_choice_dispatches_to_reminder_time_handler(
        self, mock_update, mock_context
    ):
        """Test that 'custom' choice correctly dispatches to handle_reminder_time_choice.

        When user clicks 'Custom' on reminder_time_keyboard, it should call
        handle_reminder_time_choice, not handle_due_date_choice.
        """
        # Simulate clicking "Custom" on reminder_time_keyboard
        mock_update.callback_query.data = '{"memory_id": "1", "choice": "custom"}'

        with patch(
            "tg_gateway.handlers.callback.handle_reminder_time_choice",
            new_callable=AsyncMock,
        ) as mock_reminder_handler:
            with patch(
                "tg_gateway.handlers.callback.handle_due_date_choice",
                new_callable=AsyncMock,
            ) as mock_date_handler:
                await handle_callback(mock_update, mock_context)

                # Should call reminder time handler
                mock_reminder_handler.assert_called_once()
                # Should NOT call due date handler
                mock_date_handler.assert_not_called()

    @pytest.mark.asyncio
    async def test_custom_choice_does_not_set_pending_task_memory_id(
        self, mock_update, mock_context
    ):
        """Test that 'custom' choice does NOT set PENDING_TASK_MEMORY_ID.

        This verifies the bug is fixed: clicking 'Custom' on reminder keyboard
        should not create a task via PENDING_TASK_MEMORY_ID.
        """
        mock_update.callback_query.data = '{"memory_id": "1", "choice": "custom"}'

        await handle_callback(mock_update, mock_context)

        # Should NOT set PENDING_TASK_MEMORY_ID (which is for due date flow)
        assert PENDING_TASK_MEMORY_ID not in mock_context.user_data, (
            "'custom' reminder choice should NOT set PENDING_TASK_MEMORY_ID"
        )

    @pytest.mark.asyncio
    async def test_custom_choice_sets_pending_reminder_memory_id(
        self, mock_update, mock_context
    ):
        """Test that 'custom' choice correctly sets PENDING_REMINDER_MEMORY_ID.

        The reminder flow should set PENDING_REMINDER_MEMORY_ID for the
        receive_custom_reminder message handler to pick up.
        """
        mock_update.callback_query.data = '{"memory_id": "1", "choice": "custom"}'

        await handle_callback(mock_update, mock_context)

        # Should set PENDING_REMINDER_MEMORY_ID
        assert PENDING_REMINDER_MEMORY_ID in mock_context.user_data, (
            "'custom' reminder choice should set PENDING_REMINDER_MEMORY_ID"
        )
        assert mock_context.user_data[PENDING_REMINDER_MEMORY_ID] == "1"


class TestCustomTaskChoiceParsing:
    """Tests for 'custom_task' choice routing to the task due date flow.

    The fix for the custom/custom_task ambiguity uses 'custom_task' as the
    choice value in due_date_keyboard so it is unambiguously a DueDateChoice.
    """

    def test_custom_task_choice_parses_as_due_date_choice(self):
        """'custom_task' choice must parse as DueDateChoice, not ReminderTimeChoice."""
        result = _parse_callback_data('{"memory_id": "1", "choice": "custom_task"}')

        assert isinstance(result, DueDateChoice), (
            f"'custom_task' should parse as DueDateChoice, got {type(result).__name__}"
        )
        assert result.choice == "custom_task"

    def test_custom_task_does_not_parse_as_reminder_time_choice(self):
        """'custom_task' choice must NOT parse as ReminderTimeChoice."""
        result = _parse_callback_data('{"memory_id": "1", "choice": "custom_task"}')

        assert not isinstance(result, ReminderTimeChoice), (
            "'custom_task' should NOT parse as ReminderTimeChoice"
        )

    @pytest.mark.asyncio
    async def test_custom_task_sets_pending_task_memory_id(self, mock_update, mock_context):
        """'custom_task' choice must set PENDING_TASK_MEMORY_ID, not PENDING_REMINDER_MEMORY_ID.

        This verifies the task due-date 'Custom' flow works correctly after the fix.
        """
        mock_update.callback_query.data = '{"memory_id": "task-mem-1", "choice": "custom_task"}'

        await handle_callback(mock_update, mock_context)

        assert PENDING_TASK_MEMORY_ID in mock_context.user_data, (
            "'custom_task' choice should set PENDING_TASK_MEMORY_ID"
        )
        assert mock_context.user_data[PENDING_TASK_MEMORY_ID] == "task-mem-1"
        assert PENDING_REMINDER_MEMORY_ID not in mock_context.user_data, (
            "'custom_task' choice should NOT set PENDING_REMINDER_MEMORY_ID"
        )

    @pytest.fixture
    def mock_update(self):
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.message = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 12345
        return update

    @pytest.fixture
    def mock_context(self):
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        core_client = MagicMock()
        core_client.update_memory = AsyncMock()
        core_client.get_memory = AsyncMock()
        context.bot_data = {"core_client": core_client}
        context.user_data = {}
        return context
