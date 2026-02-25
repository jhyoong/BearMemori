"""Tests for callback handlers."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from tg_gateway.handlers.callback import (
    handle_callback,
    handle_invalid,
    _parse_callback_data,
    _clear_conversation_state,
    handle_memory_action,
    handle_due_date_choice,
    handle_reminder_time_choice,
    handle_confirm_delete,
    handle_search_detail,
    handle_task_action,
    handle_tag_confirm,
    handle_intent_confirm,
    handle_reschedule_action,
)
from tg_gateway.callback_data import (
    MemoryAction,
    DueDateChoice,
    ReminderTimeChoice,
    ConfirmDelete,
    SearchDetail,
    TaskAction,
    TagConfirm,
    IntentConfirm,
    RescheduleAction,
)
from tg_gateway.core_client import CoreUnavailableError, CoreNotFoundError
from tg_gateway.handlers.conversation import (
    AWAITING_BUTTON_ACTION,
    PENDING_LLM_CONVERSATION,
    PENDING_REMINDER_MEMORY_ID,
    USER_QUEUE_COUNT,
)


class TestParseCallbackData:
    """Tests for _parse_callback_data function."""

    def test_parse_memory_action(self):
        """Test parsing MemoryAction callback data."""
        result = _parse_callback_data('{"action": "set_task", "memory_id": "123"}')
        assert isinstance(result, MemoryAction)
        assert result.action == "set_task"
        assert result.memory_id == "123"

    def test_parse_due_date_choice_today(self):
        """Test parsing DueDateChoice callback data - today."""
        result = _parse_callback_data('{"memory_id": "123", "choice": "today"}')
        assert isinstance(result, DueDateChoice)
        assert result.choice == "today"
        assert result.memory_id == "123"

    def test_parse_due_date_choice_tomorrow(self):
        """Test parsing DueDateChoice callback data - tomorrow."""
        result = _parse_callback_data('{"memory_id": "123", "choice": "tomorrow"}')
        assert isinstance(result, DueDateChoice)
        assert result.choice == "tomorrow"

    def test_parse_reminder_time_choice_1h(self):
        """Test parsing ReminderTimeChoice callback data - 1h."""
        result = _parse_callback_data('{"memory_id": "123", "choice": "1h"}')
        assert isinstance(result, ReminderTimeChoice)
        assert result.choice == "1h"

    def test_parse_reminder_time_choice_tomorrow_9am(self):
        """Test parsing ReminderTimeChoice callback data - tomorrow_9am."""
        result = _parse_callback_data('{"memory_id": "123", "choice": "tomorrow_9am"}')
        assert isinstance(result, ReminderTimeChoice)
        assert result.choice == "tomorrow_9am"

    def test_parse_confirm_delete_yes(self):
        """Test parsing ConfirmDelete callback data - confirmed."""
        result = _parse_callback_data('{"memory_id": "123", "confirmed": true}')
        assert isinstance(result, ConfirmDelete)
        assert result.confirmed is True

    def test_parse_confirm_delete_no(self):
        """Test parsing ConfirmDelete callback data - not confirmed."""
        result = _parse_callback_data('{"memory_id": "123", "confirmed": false}')
        assert isinstance(result, ConfirmDelete)
        assert result.confirmed is False

    def test_parse_search_detail(self):
        """Test parsing SearchDetail callback data."""
        result = _parse_callback_data('{"memory_id": "123"}')
        assert isinstance(result, SearchDetail)
        assert result.memory_id == "123"

    def test_parse_task_action(self):
        """Test parsing TaskAction callback data."""
        result = _parse_callback_data('{"action": "mark_done", "task_id": "456"}')
        assert isinstance(result, TaskAction)
        assert result.action == "mark_done"
        assert result.task_id == "456"

    def test_parse_tag_confirm(self):
        """Test parsing TagConfirm callback data."""
        result = _parse_callback_data('{"memory_id": "123", "action": "confirm_all"}')
        assert isinstance(result, TagConfirm)
        assert result.memory_id == "123"
        assert result.action == "confirm_all"

    def test_parse_intent_confirm_confirm_reminder(self):
        """Test parsing IntentConfirm callback data - confirm_reminder action."""
        result = _parse_callback_data('{"memory_id": "123", "action": "confirm_reminder"}')
        assert isinstance(result, IntentConfirm)
        assert result.memory_id == "123"
        assert result.action == "confirm_reminder"

    def test_parse_intent_confirm_edit_reminder_time(self):
        """Test parsing IntentConfirm callback data - edit_reminder_time action."""
        result = _parse_callback_data('{"memory_id": "123", "action": "edit_reminder_time"}')
        assert isinstance(result, IntentConfirm)
        assert result.action == "edit_reminder_time"

    def test_parse_intent_confirm_confirm_task(self):
        """Test parsing IntentConfirm callback data - confirm_task action."""
        result = _parse_callback_data('{"memory_id": "123", "action": "confirm_task"}')
        assert isinstance(result, IntentConfirm)
        assert result.action == "confirm_task"

    def test_parse_intent_confirm_edit_task(self):
        """Test parsing IntentConfirm callback data - edit_task action."""
        result = _parse_callback_data('{"memory_id": "123", "action": "edit_task"}')
        assert isinstance(result, IntentConfirm)
        assert result.action == "edit_task"

    def test_parse_intent_confirm_just_a_note(self):
        """Test parsing IntentConfirm callback data - just_a_note action."""
        result = _parse_callback_data('{"memory_id": "123", "action": "just_a_note"}')
        assert isinstance(result, IntentConfirm)
        assert result.action == "just_a_note"

    def test_parse_reschedule_action_reschedule(self):
        """Test parsing RescheduleAction callback data - reschedule action."""
        result = _parse_callback_data('{"memory_id": "123", "action": "reschedule"}')
        assert isinstance(result, RescheduleAction)
        assert result.memory_id == "123"
        assert result.action == "reschedule"

    def test_parse_reschedule_action_dismiss(self):
        """Test parsing RescheduleAction callback data - dismiss action."""
        result = _parse_callback_data('{"memory_id": "123", "action": "dismiss"}')
        assert isinstance(result, RescheduleAction)
        assert result.action == "dismiss"

    def test_parse_invalid_json(self):
        """Test parsing invalid JSON returns None."""
        result = _parse_callback_data("not valid json")
        assert result is None

    def test_parse_empty_string(self):
        """Test parsing empty string returns None."""
        result = _parse_callback_data("")
        assert result is None

    def test_parse_unknown_structure(self):
        """Test parsing unknown data structure returns None."""
        result = _parse_callback_data('{"unknown_key": "value"}')
        assert result is None


class TestHandleCallback:
    """Tests for handle_callback function."""

    @pytest.fixture
    def mock_update(self):
        """Create a mock update with callback query."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.data = '{"action": "set_task", "memory_id": "123"}'
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.message = MagicMock()
        update.callback_query.message.edit_text = AsyncMock()
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        core_client = MagicMock()
        core_client.update_memory = AsyncMock()
        context.bot_data = {"core_client": core_client}
        context.user_data = {}
        return context

    @pytest.mark.asyncio
    async def test_callback_answered_immediately(self, mock_update, mock_context):
        """Test that callback query is answered immediately."""
        await handle_callback(mock_update, mock_context)
        mock_update.callback_query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_to_memory_action(self, mock_update, mock_context):
        """Test dispatching to handle_memory_action."""
        mock_update.callback_query.data = '{"action": "set_task", "memory_id": "123"}'

        with patch(
            "tg_gateway.handlers.callback.handle_memory_action", new_callable=AsyncMock
        ) as mock_handler:
            await handle_callback(mock_update, mock_context)
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_to_due_date_choice(self, mock_update, mock_context):
        """Test dispatching to handle_due_date_choice."""
        mock_update.callback_query.data = '{"memory_id": "123", "choice": "today"}'

        with patch(
            "tg_gateway.handlers.callback.handle_due_date_choice",
            new_callable=AsyncMock,
        ) as mock_handler:
            await handle_callback(mock_update, mock_context)
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_to_reminder_time_choice(self, mock_update, mock_context):
        """Test dispatching to handle_reminder_time_choice."""
        mock_update.callback_query.data = '{"memory_id": "123", "choice": "1h"}'

        with patch(
            "tg_gateway.handlers.callback.handle_reminder_time_choice",
            new_callable=AsyncMock,
        ) as mock_handler:
            await handle_callback(mock_update, mock_context)
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_to_confirm_delete(self, mock_update, mock_context):
        """Test dispatching to handle_confirm_delete."""
        mock_update.callback_query.data = '{"memory_id": "123", "confirmed": true}'

        with patch(
            "tg_gateway.handlers.callback.handle_confirm_delete", new_callable=AsyncMock
        ) as mock_handler:
            await handle_callback(mock_update, mock_context)
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_to_search_detail(self, mock_update, mock_context):
        """Test dispatching to handle_search_detail."""
        mock_update.callback_query.data = '{"memory_id": "123"}'

        with patch(
            "tg_gateway.handlers.callback.handle_search_detail", new_callable=AsyncMock
        ) as mock_handler:
            await handle_callback(mock_update, mock_context)
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatches_to_task_action(self, mock_update, mock_context):
        """Test dispatching to handle_task_action."""
        mock_update.callback_query.data = '{"action": "mark_done", "task_id": "456"}'

        with patch(
            "tg_gateway.handlers.callback.handle_task_action", new_callable=AsyncMock
        ) as mock_handler:
            await handle_callback(mock_update, mock_context)
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_core_not_found_error(self, mock_update, mock_context):
        """Test handling CoreNotFoundError."""
        mock_update.callback_query.data = '{"action": "set_task", "memory_id": "123"}'

        with patch(
            "tg_gateway.handlers.callback.handle_memory_action",
            side_effect=CoreNotFoundError("not found"),
        ):
            await handle_callback(mock_update, mock_context)

        mock_update.callback_query.edit_message_text.assert_called_with(
            "This item no longer exists."
        )

    @pytest.mark.asyncio
    async def test_not_found_message_matches_spec(self, mock_update, mock_context):
        """Test that the CoreNotFoundError message matches the spec exactly."""
        mock_update.callback_query.data = '{"action": "set_task", "memory_id": "123"}'

        with patch(
            "tg_gateway.handlers.callback.handle_memory_action",
            side_effect=CoreNotFoundError("not found"),
        ):
            await handle_callback(mock_update, mock_context)

        # Check exact message from spec
        call_args = mock_update.callback_query.edit_message_text.call_args[0][0]
        assert call_args == "This item no longer exists."

    @pytest.mark.asyncio
    async def test_dispatches_to_tag_confirm(self, mock_update, mock_context):
        """Test dispatching to handle_tag_confirm."""
        # Use proper TagConfirm callback data
        mock_update.callback_query.data = (
            '{"memory_id": "123", "action": "confirm_all"}'
        )

        with patch(
            "tg_gateway.handlers.callback.handle_tag_confirm", new_callable=AsyncMock
        ) as mock_handler:
            await handle_callback(mock_update, mock_context)
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_core_unavailable_error(self, mock_update, mock_context):
        """Test handling CoreUnavailableError."""
        mock_update.callback_query.data = '{"action": "set_task", "memory_id": "123"}'

        with patch(
            "tg_gateway.handlers.callback.handle_memory_action",
            side_effect=CoreUnavailableError("unavailable"),
        ):
            await handle_callback(mock_update, mock_context)

        mock_update.callback_query.edit_message_text.assert_called_with(
            "I'm having trouble reaching my backend. Please try again in a moment."
        )

    @pytest.mark.asyncio
    async def test_unavailable_message_matches_spec(self, mock_update, mock_context):
        """Test that the CoreUnavailableError message matches the spec exactly."""
        mock_update.callback_query.data = '{"action": "set_task", "memory_id": "123"}'

        with patch(
            "tg_gateway.handlers.callback.handle_memory_action",
            side_effect=CoreUnavailableError("unavailable"),
        ):
            await handle_callback(mock_update, mock_context)

        # Check that it contains "I'm having trouble reaching my backend"
        call_args = mock_update.callback_query.edit_message_text.call_args[0][0]
        assert "I'm having trouble reaching my backend." in call_args

    @pytest.mark.asyncio
    async def test_handles_invalid_callback_data(self, mock_update, mock_context):
        """Test handling unknown callback data type."""
        mock_update.callback_query.data = "invalid data"

        with patch("tg_gateway.handlers.callback.logger") as mock_logger:
            await handle_callback(mock_update, mock_context)
            mock_logger.warning.assert_called()


class TestHandleInvalid:
    """Tests for handle_invalid function."""

    @pytest.fixture
    def mock_update(self):
        """Create a mock update with callback query."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        return update

    @pytest.mark.asyncio
    async def test_shows_alert_for_expired_button(self, mock_update):
        """Test that expired button shows alert message."""
        await handle_invalid(mock_update, MagicMock())

        mock_update.callback_query.answer.assert_called_once_with(
            "This button has expired. Please send your message again.",
            show_alert=True,
        )


class TestStubHandlers:
    """Tests that stub handlers exist and can be called."""

    @pytest.fixture
    def mock_update(self):
        """Create a mock update with callback query."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()
        return update

    @pytest.mark.asyncio
    async def test_memory_action_stub(self, mock_update):
        """Test that handle_memory_action can be called."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}
        core_client = MagicMock()
        core_client.update_memory = AsyncMock()
        callback_data = MemoryAction(action="set_task", memory_id="123")

        # Should not raise - should complete without error
        await handle_memory_action(mock_update, context, callback_data, core_client)

    @pytest.mark.asyncio
    async def test_due_date_choice_stub(self):
        """Test that handle_due_date_choice stub can be called."""
        from datetime import datetime

        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.bot_data = {"user_id": 12345}

        core_client = MagicMock()
        # Set up async mocks for core_client methods
        mock_memory = MagicMock()
        mock_memory.content = "Test memory content"
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.create_task = AsyncMock()

        callback_data = DueDateChoice(memory_id="123", choice="today")

        await handle_due_date_choice(update, context, callback_data, core_client)

        # Verify the methods were called
        core_client.get_memory.assert_called_once_with("123")
        core_client.create_task.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_reminder_time_choice_stub(self):
        """Test that handle_reminder_time_choice stub can be called."""
        from datetime import datetime

        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.bot_data = {"user_id": 12345}

        core_client = MagicMock()
        # Set up async mocks for core_client methods
        mock_memory = MagicMock()
        mock_memory.content = "Test memory content"
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.create_reminder = AsyncMock()
        core_client.get_settings = AsyncMock()

        callback_data = ReminderTimeChoice(memory_id="123", choice="1h")

        await handle_reminder_time_choice(update, context, callback_data, core_client)

        # Verify the methods were called
        core_client.get_memory.assert_called_once_with("123")
        core_client.create_reminder.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_confirm_delete_stub(self):
        """Test that handle_confirm_delete can be called with proper mocks."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.edit_message_caption = AsyncMock()
        # Set up message as text message (no photo)
        update.callback_query.message = MagicMock()
        update.callback_query.message.photo = None

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.bot_data = {"user_id": 12345}
        context.user_data = {}

        core_client = MagicMock()
        # Set up async mocks for core_client methods
        mock_memory = MagicMock()
        mock_memory.content = "Test memory content"
        mock_memory.media_type = None
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.delete_memory = AsyncMock(return_value=True)

        callback_data = ConfirmDelete(memory_id="123", confirmed=True)

        await handle_confirm_delete(update, context, callback_data, core_client)

        # Verify the methods were called
        core_client.delete_memory.assert_called_once_with("123")
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_detail_stub(self):
        """Test that handle_search_detail stub can be called."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

        core_client = MagicMock()
        mock_memory = MagicMock()
        mock_memory.content = "Test memory content"
        mock_memory.media_type = None
        mock_memory.media_file_id = None
        core_client.get_memory = AsyncMock(return_value=mock_memory)

        callback_data = SearchDetail(memory_id="123")

        await handle_search_detail(update, context, callback_data, core_client)

        # Verify the methods were called
        core_client.get_memory.assert_called_once_with("123")
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_task_action_stub(self):
        """Test that handle_task_action stub can be called."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

        core_client = MagicMock()
        # Mock update_task to return a task without recurrence
        mock_task = MagicMock()
        mock_task.recurrence_minutes = None
        core_client.update_task = AsyncMock(return_value=mock_task)

        callback_data = TaskAction(action="mark_done", task_id="456")

        await handle_task_action(update, context, callback_data, core_client)

        # Verify the methods were called
        core_client.update_task.assert_called_once()
        update.callback_query.edit_message_text.assert_called_with(
            "Task marked as done!"
        )

    @pytest.mark.asyncio
    async def test_task_action_with_recurrence(self):
        """Test that handle_task_action handles recurring tasks."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)

        core_client = MagicMock()
        # Mock update_task to return a task with recurrence
        mock_task = MagicMock()
        mock_task.recurrence_minutes = 60
        core_client.update_task = AsyncMock(return_value=mock_task)

        callback_data = TaskAction(action="mark_done", task_id="456")

        await handle_task_action(update, context, callback_data, core_client)

        # Verify the methods were called and recurrence is noted
        core_client.update_task.assert_called_once()
        update.callback_query.edit_message_text.assert_called_with(
            "Task marked as done! Next instance created (recurs every 60 min)."
        )

    @pytest.mark.asyncio
    async def test_tag_confirm_stub(self):
        """Test that handle_tag_confirm stub can be called."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()

        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}

        core_client = MagicMock()
        mock_memory = MagicMock()
        # Mock tags as MemoryTagResponse objects with tag and status
        mock_tag1 = MagicMock()
        mock_tag1.tag = "tag1"
        mock_tag1.status = "suggested"
        mock_tag2 = MagicMock()
        mock_tag2.tag = "tag2"
        mock_tag2.status = "confirmed"
        mock_memory.tags = [mock_tag1, mock_tag2]
        core_client.get_memory = AsyncMock(return_value=mock_memory)
        core_client.add_tags = AsyncMock()
        core_client.update_memory = AsyncMock()

        callback_data = TagConfirm(memory_id="123", action="confirm_all")

        await handle_tag_confirm(update, context, callback_data, core_client)

        # Verify the methods were called
        core_client.get_memory.assert_called_once_with("123")
        # Should confirm suggested tags in a single batch call
        core_client.add_tags.assert_called_once()
        core_client.update_memory.assert_called_once()
        # Check that add_tags was called with TagsAddRequest containing all suggested tags
        call_args = core_client.add_tags.call_args[0]
        assert call_args[0] == "123"
        # Should be TagsAddRequest with tags list ["tag1"] and status "confirmed"
        assert call_args[1].tags == ["tag1"]
        assert call_args[1].status == "confirmed"
        update.callback_query.edit_message_text.assert_called_with(
            "Tags confirmed: tag1"
        )


class TestIntentConfirmDataclass:
    """Tests for IntentConfirm dataclass structure."""

    def test_frozen_immutable(self):
        """Test that IntentConfirm is frozen (immutable)."""
        obj = IntentConfirm(memory_id="abc", action="confirm_reminder")
        with pytest.raises(Exception):
            obj.action = "something_else"  # type: ignore[misc]

    def test_fields_stored_correctly(self):
        """Test that field values are stored as provided."""
        obj = IntentConfirm(memory_id="mem-42", action="confirm_task")
        assert obj.memory_id == "mem-42"
        assert obj.action == "confirm_task"

    def test_all_valid_actions_parseable(self):
        """Test that all five valid IntentConfirm actions parse correctly."""
        valid_actions = (
            "confirm_reminder",
            "edit_reminder_time",
            "confirm_task",
            "edit_task",
            "just_a_note",
        )
        for action in valid_actions:
            result = _parse_callback_data(f'{{"memory_id": "1", "action": "{action}"}}')
            assert isinstance(result, IntentConfirm), f"Expected IntentConfirm for action={action}"
            assert result.action == action


class TestRescheduleActionDataclass:
    """Tests for RescheduleAction dataclass structure."""

    def test_frozen_immutable(self):
        """Test that RescheduleAction is frozen (immutable)."""
        obj = RescheduleAction(memory_id="abc", action="reschedule")
        with pytest.raises(Exception):
            obj.action = "something_else"  # type: ignore[misc]

    def test_fields_stored_correctly(self):
        """Test that field values are stored as provided."""
        obj = RescheduleAction(memory_id="mem-99", action="dismiss")
        assert obj.memory_id == "mem-99"
        assert obj.action == "dismiss"

    def test_both_valid_actions_parseable(self):
        """Test that both valid RescheduleAction actions parse correctly."""
        for action in ("reschedule", "dismiss"):
            result = _parse_callback_data(f'{{"memory_id": "1", "action": "{action}"}}')
            assert isinstance(result, RescheduleAction), (
                f"Expected RescheduleAction for action={action}"
            )
            assert result.action == action


class TestDispatchNewCallbackTypes:
    """Tests that handle_callback dispatches IntentConfirm and RescheduleAction."""

    @pytest.fixture
    def mock_update(self):
        """Create a mock update with callback query."""
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.message = MagicMock()
        return update

    @pytest.fixture
    def mock_context(self):
        """Create a mock context."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.bot_data = {"core_client": MagicMock()}
        context.user_data = {}
        return context

    @pytest.mark.asyncio
    async def test_intent_confirm_dispatches_to_handler(self, mock_update, mock_context):
        """Test that IntentConfirm callback data dispatches to handle_intent_confirm."""
        mock_update.callback_query.data = '{"memory_id": "123", "action": "confirm_task"}'

        with patch(
            "tg_gateway.handlers.callback.handle_intent_confirm", new_callable=AsyncMock
        ) as mock_handler:
            await handle_callback(mock_update, mock_context)
            mock_handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_reschedule_action_dispatches_to_handler(self, mock_update, mock_context):
        """Test that RescheduleAction callback data dispatches to handle_reschedule_action."""
        mock_update.callback_query.data = '{"memory_id": "123", "action": "reschedule"}'

        with patch(
            "tg_gateway.handlers.callback.handle_reschedule_action", new_callable=AsyncMock
        ) as mock_handler:
            await handle_callback(mock_update, mock_context)
            mock_handler.assert_called_once()


class TestClearConversationState:
    """Tests for _clear_conversation_state helper."""

    def test_clears_awaiting_button_action(self):
        """Test that AWAITING_BUTTON_ACTION is removed from user_data."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {AWAITING_BUTTON_ACTION: True, USER_QUEUE_COUNT: 2}
        _clear_conversation_state(context)
        assert AWAITING_BUTTON_ACTION not in context.user_data

    def test_clears_pending_llm_conversation(self):
        """Test that PENDING_LLM_CONVERSATION is removed from user_data."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {PENDING_LLM_CONVERSATION: {"memory_id": "1"}, USER_QUEUE_COUNT: 1}
        _clear_conversation_state(context)
        assert PENDING_LLM_CONVERSATION not in context.user_data

    def test_decrements_queue_count(self):
        """Test that USER_QUEUE_COUNT is decremented by one."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {USER_QUEUE_COUNT: 3}
        _clear_conversation_state(context)
        assert context.user_data[USER_QUEUE_COUNT] == 2

    def test_queue_count_clamps_at_zero(self):
        """Test that USER_QUEUE_COUNT never goes below zero."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {USER_QUEUE_COUNT: 0}
        _clear_conversation_state(context)
        assert context.user_data[USER_QUEUE_COUNT] == 0

    def test_handles_missing_keys_gracefully(self):
        """Test that missing keys in user_data do not raise exceptions."""
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {}
        # Should not raise
        _clear_conversation_state(context)
        assert context.user_data[USER_QUEUE_COUNT] == 0


class TestHandleIntentConfirm:
    """Tests for handle_intent_confirm handler."""

    @pytest.fixture
    def mock_update(self):
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()
        return update

    @pytest.fixture
    def mock_context(self):
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {AWAITING_BUTTON_ACTION: True, PENDING_LLM_CONVERSATION: {}, USER_QUEUE_COUNT: 1}
        return context

    @pytest.fixture
    def mock_core_client(self):
        client = MagicMock()
        client.update_memory = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_confirm_reminder_shows_reminder_time_keyboard(
        self, mock_update, mock_context, mock_core_client
    ):
        """Test confirm_reminder shows reminder time keyboard."""
        callback_data = IntentConfirm(memory_id="mem-1", action="confirm_reminder")
        await handle_intent_confirm(mock_update, mock_context, callback_data, mock_core_client)

        mock_core_client.update_memory.assert_awaited_once()
        call_args = mock_update.callback_query.edit_message_text.call_args
        assert call_args[0][0] == "Select when to be reminded:"
        assert call_args[1]["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_edit_reminder_time_shows_reminder_time_keyboard(
        self, mock_update, mock_context, mock_core_client
    ):
        """Test edit_reminder_time shows reminder time keyboard."""
        callback_data = IntentConfirm(memory_id="mem-1", action="edit_reminder_time")
        await handle_intent_confirm(mock_update, mock_context, callback_data, mock_core_client)

        mock_core_client.update_memory.assert_awaited_once()
        call_args = mock_update.callback_query.edit_message_text.call_args
        assert call_args[0][0] == "Select a new reminder time:"
        assert call_args[1]["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_confirm_task_shows_due_date_keyboard(
        self, mock_update, mock_context, mock_core_client
    ):
        """Test confirm_task shows due date keyboard."""
        callback_data = IntentConfirm(memory_id="mem-1", action="confirm_task")
        await handle_intent_confirm(mock_update, mock_context, callback_data, mock_core_client)

        mock_core_client.update_memory.assert_awaited_once()
        call_args = mock_update.callback_query.edit_message_text.call_args
        assert call_args[0][0] == "Select a due date for the task:"
        assert call_args[1]["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_edit_task_shows_due_date_keyboard(
        self, mock_update, mock_context, mock_core_client
    ):
        """Test edit_task shows due date keyboard."""
        callback_data = IntentConfirm(memory_id="mem-1", action="edit_task")
        await handle_intent_confirm(mock_update, mock_context, callback_data, mock_core_client)

        mock_core_client.update_memory.assert_awaited_once()
        call_args = mock_update.callback_query.edit_message_text.call_args
        assert call_args[0][0] == "Select a due date:"
        assert call_args[1]["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_just_a_note_replies_with_kept_as_note(
        self, mock_update, mock_context, mock_core_client
    ):
        """Test just_a_note confirms memory and shows memory_actions keyboard."""
        callback_data = IntentConfirm(memory_id="mem-1", action="just_a_note")
        await handle_intent_confirm(mock_update, mock_context, callback_data, mock_core_client)

        mock_core_client.update_memory.assert_awaited_once()
        call_args = mock_update.callback_query.edit_message_text.call_args
        assert call_args[0][0] == "Kept as a note."
        assert call_args[1]["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_all_actions_confirm_memory(
        self, mock_update, mock_context, mock_core_client
    ):
        """Test that all IntentConfirm actions confirm the memory."""
        actions = ("confirm_reminder", "edit_reminder_time", "confirm_task", "edit_task", "just_a_note")
        for action in actions:
            mock_core_client.update_memory.reset_mock()
            context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
            context.user_data = {USER_QUEUE_COUNT: 1}
            callback_data = IntentConfirm(memory_id="mem-1", action=action)
            await handle_intent_confirm(mock_update, context, callback_data, mock_core_client)
            mock_core_client.update_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_all_actions_clear_conversation_state(
        self, mock_update, mock_core_client
    ):
        """Test that all IntentConfirm actions clear conversation state."""
        actions = ("confirm_reminder", "edit_reminder_time", "confirm_task", "edit_task", "just_a_note")
        for action in actions:
            context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
            context.user_data = {
                AWAITING_BUTTON_ACTION: True,
                PENDING_LLM_CONVERSATION: {},
                USER_QUEUE_COUNT: 2,
            }
            callback_data = IntentConfirm(memory_id="mem-1", action=action)
            await handle_intent_confirm(mock_update, context, callback_data, mock_core_client)
            assert AWAITING_BUTTON_ACTION not in context.user_data
            assert PENDING_LLM_CONVERSATION not in context.user_data
            assert context.user_data[USER_QUEUE_COUNT] == 1


class TestHandleRescheduleAction:
    """Tests for handle_reschedule_action handler."""

    @pytest.fixture
    def mock_update(self):
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()
        return update

    @pytest.fixture
    def mock_context(self):
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {AWAITING_BUTTON_ACTION: True, USER_QUEUE_COUNT: 1}
        return context

    @pytest.fixture
    def mock_core_client(self):
        client = MagicMock()
        client.update_memory = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_reschedule_sets_pending_reminder_and_prompts(
        self, mock_update, mock_context, mock_core_client
    ):
        """Test reschedule sets PENDING_REMINDER_MEMORY_ID and prompts for date/time."""
        callback_data = RescheduleAction(memory_id="mem-2", action="reschedule")
        await handle_reschedule_action(mock_update, mock_context, callback_data, mock_core_client)

        mock_core_client.update_memory.assert_awaited_once()
        assert mock_context.user_data.get(PENDING_REMINDER_MEMORY_ID) == "mem-2"
        call_text = mock_update.callback_query.edit_message_text.call_args[0][0]
        assert "2024-12-31 14:30" in call_text

    @pytest.mark.asyncio
    async def test_dismiss_replies_dismissed(
        self, mock_update, mock_context, mock_core_client
    ):
        """Test dismiss confirms memory and replies with Dismissed."""
        callback_data = RescheduleAction(memory_id="mem-2", action="dismiss")
        await handle_reschedule_action(mock_update, mock_context, callback_data, mock_core_client)

        mock_core_client.update_memory.assert_awaited_once()
        mock_update.callback_query.edit_message_text.assert_awaited_once_with("Dismissed.")

    @pytest.mark.asyncio
    async def test_both_actions_confirm_memory(
        self, mock_update, mock_core_client
    ):
        """Test that both RescheduleAction actions confirm the memory."""
        for action in ("reschedule", "dismiss"):
            mock_core_client.update_memory.reset_mock()
            context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
            context.user_data = {USER_QUEUE_COUNT: 1}
            callback_data = RescheduleAction(memory_id="mem-2", action=action)
            await handle_reschedule_action(mock_update, context, callback_data, mock_core_client)
            mock_core_client.update_memory.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_both_actions_clear_conversation_state(
        self, mock_update, mock_core_client
    ):
        """Test that both RescheduleAction actions clear conversation state."""
        for action in ("reschedule", "dismiss"):
            context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
            context.user_data = {
                AWAITING_BUTTON_ACTION: True,
                PENDING_LLM_CONVERSATION: {},
                USER_QUEUE_COUNT: 2,
            }
            callback_data = RescheduleAction(memory_id="mem-2", action=action)
            await handle_reschedule_action(mock_update, context, callback_data, mock_core_client)
            assert AWAITING_BUTTON_ACTION not in context.user_data
            assert PENDING_LLM_CONVERSATION not in context.user_data
            assert context.user_data[USER_QUEUE_COUNT] == 1


class TestExistingHandlersStateClearingAndConfirmation:
    """Tests that existing handlers confirm pending memories and clear conversation state."""

    @pytest.fixture
    def mock_update(self):
        update = MagicMock(spec=Update)
        update.callback_query = MagicMock()
        update.callback_query.edit_message_text = AsyncMock()
        update.callback_query.edit_message_caption = AsyncMock()
        update.callback_query.message = MagicMock()
        update.callback_query.message.photo = None
        update.effective_user = MagicMock()
        update.effective_user.id = 12345
        return update

    @pytest.fixture
    def mock_context_with_state(self):
        context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
        context.user_data = {
            AWAITING_BUTTON_ACTION: True,
            PENDING_LLM_CONVERSATION: {"memory_id": "1"},
            USER_QUEUE_COUNT: 2,
        }
        return context

    @pytest.fixture
    def mock_core_client(self):
        client = MagicMock()
        client.update_memory = AsyncMock()
        client.delete_memory = AsyncMock()
        client.get_memory = AsyncMock()
        client.add_tags = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_memory_action_set_task_confirms_and_clears_state(
        self, mock_update, mock_context_with_state, mock_core_client
    ):
        """Test that set_task confirms memory and clears conversation state."""
        callback_data = MemoryAction(action="set_task", memory_id="mem-1")
        await handle_memory_action(
            mock_update, mock_context_with_state, callback_data, mock_core_client
        )

        mock_core_client.update_memory.assert_awaited_once()
        assert AWAITING_BUTTON_ACTION not in mock_context_with_state.user_data
        assert PENDING_LLM_CONVERSATION not in mock_context_with_state.user_data

    @pytest.mark.asyncio
    async def test_memory_action_set_reminder_confirms_and_clears_state(
        self, mock_update, mock_context_with_state, mock_core_client
    ):
        """Test that set_reminder confirms memory and clears conversation state."""
        callback_data = MemoryAction(action="set_reminder", memory_id="mem-1")
        await handle_memory_action(
            mock_update, mock_context_with_state, callback_data, mock_core_client
        )

        mock_core_client.update_memory.assert_awaited_once()
        assert AWAITING_BUTTON_ACTION not in mock_context_with_state.user_data

    @pytest.mark.asyncio
    async def test_memory_action_add_tag_confirms_and_clears_state(
        self, mock_update, mock_context_with_state, mock_core_client
    ):
        """Test that add_tag confirms memory and clears conversation state."""
        callback_data = MemoryAction(action="add_tag", memory_id="mem-1")
        await handle_memory_action(
            mock_update, mock_context_with_state, callback_data, mock_core_client
        )

        mock_core_client.update_memory.assert_awaited_once()
        assert AWAITING_BUTTON_ACTION not in mock_context_with_state.user_data

    @pytest.mark.asyncio
    async def test_memory_action_toggle_pin_clears_state(
        self, mock_update, mock_context_with_state, mock_core_client
    ):
        """Test that toggle_pin clears conversation state."""
        callback_data = MemoryAction(action="toggle_pin", memory_id="mem-1")
        await handle_memory_action(
            mock_update, mock_context_with_state, callback_data, mock_core_client
        )

        mock_core_client.update_memory.assert_awaited_once()
        assert AWAITING_BUTTON_ACTION not in mock_context_with_state.user_data

    @pytest.mark.asyncio
    async def test_confirm_delete_confirmed_clears_state(
        self, mock_update, mock_context_with_state, mock_core_client
    ):
        """Test that confirmed delete clears conversation state."""
        callback_data = ConfirmDelete(memory_id="mem-1", confirmed=True)
        await handle_confirm_delete(
            mock_update, mock_context_with_state, callback_data, mock_core_client
        )

        mock_core_client.delete_memory.assert_awaited_once()
        assert AWAITING_BUTTON_ACTION not in mock_context_with_state.user_data
        assert PENDING_LLM_CONVERSATION not in mock_context_with_state.user_data

    @pytest.mark.asyncio
    async def test_tag_confirm_confirm_all_clears_state(
        self, mock_update, mock_context_with_state, mock_core_client
    ):
        """Test that tag confirm_all clears conversation state."""
        mock_memory = MagicMock()
        mock_tag = MagicMock()
        mock_tag.tag = "work"
        mock_tag.status = "suggested"
        mock_memory.tags = [mock_tag]
        mock_core_client.get_memory.return_value = mock_memory

        callback_data = TagConfirm(memory_id="mem-1", action="confirm_all")
        await handle_tag_confirm(
            mock_update, mock_context_with_state, callback_data, mock_core_client
        )

        assert AWAITING_BUTTON_ACTION not in mock_context_with_state.user_data
        assert PENDING_LLM_CONVERSATION not in mock_context_with_state.user_data

    @pytest.mark.asyncio
    async def test_tag_confirm_edit_confirms_memory_and_clears_state(
        self, mock_update, mock_context_with_state, mock_core_client
    ):
        """Test that tag edit confirms memory and clears conversation state."""
        callback_data = TagConfirm(memory_id="mem-1", action="edit")
        await handle_tag_confirm(
            mock_update, mock_context_with_state, callback_data, mock_core_client
        )

        mock_core_client.update_memory.assert_awaited_once()
        assert AWAITING_BUTTON_ACTION not in mock_context_with_state.user_data
        assert PENDING_LLM_CONVERSATION not in mock_context_with_state.user_data
