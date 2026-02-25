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
    handle_memory_action,
    handle_due_date_choice,
    handle_reminder_time_choice,
    handle_confirm_delete,
    handle_search_detail,
    handle_task_action,
    handle_tag_confirm,
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
        context.bot_data = {"core_client": MagicMock()}
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
        core_client = MagicMock()
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
        return context

    @pytest.mark.asyncio
    async def test_intent_confirm_is_recognized(self, mock_update, mock_context):
        """Test that IntentConfirm callback data is recognized and does not fall through."""
        mock_update.callback_query.data = '{"memory_id": "123", "action": "confirm_task"}'

        with patch("tg_gateway.handlers.callback.logger") as mock_logger:
            await handle_callback(mock_update, mock_context)
            # Should log a warning about unimplemented handler, not "Unknown callback data"
            warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
            assert any("IntentConfirm" in c for c in warning_calls)
            assert not any("Unknown callback data" in c for c in warning_calls)

    @pytest.mark.asyncio
    async def test_reschedule_action_is_recognized(self, mock_update, mock_context):
        """Test that RescheduleAction callback data is recognized and does not fall through."""
        mock_update.callback_query.data = '{"memory_id": "123", "action": "reschedule"}'

        with patch("tg_gateway.handlers.callback.logger") as mock_logger:
            await handle_callback(mock_update, mock_context)
            warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
            assert any("RescheduleAction" in c for c in warning_calls)
            assert not any("Unknown callback data" in c for c in warning_calls)
