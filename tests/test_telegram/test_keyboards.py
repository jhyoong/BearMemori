"""Tests for keyboard builders in keyboards.py."""

import json

import pytest

from tg_gateway.callback_data import (
    ConfirmDelete,
    IntentConfirm,
    MemoryAction,
    RescheduleAction,
    TagConfirm,
)
from tg_gateway.keyboards import (
    general_note_keyboard,
    llm_failure_keyboard,
    reminder_proposal_keyboard,
    reschedule_keyboard,
    serialize_callback,
    task_proposal_keyboard,
)


class TestSerializeCallback:
    """Tests for the exported serialize_callback helper."""

    def test_serializes_dataclass(self):
        """Test that a dataclass is serialized to a JSON string via __dict__."""
        obj = IntentConfirm(memory_id="mem-1", action="confirm_reminder")
        result = serialize_callback(obj)
        parsed = json.loads(result)
        assert parsed["memory_id"] == "mem-1"
        assert parsed["action"] == "confirm_reminder"

    def test_serializes_plain_value(self):
        """Test that a plain value is serialized directly to JSON."""
        result = serialize_callback("hello")
        assert json.loads(result) == "hello"


class TestReminderProposalKeyboard:
    """Tests for reminder_proposal_keyboard."""

    def test_returns_single_row(self):
        """Keyboard has exactly one row."""
        keyboard = reminder_proposal_keyboard("mem-abc")
        assert len(keyboard.inline_keyboard) == 1

    def test_row_has_three_buttons(self):
        """The single row contains exactly three buttons."""
        keyboard = reminder_proposal_keyboard("mem-abc")
        row = keyboard.inline_keyboard[0]
        assert len(row) == 3

    def test_button_labels(self):
        """Buttons are labelled Confirm, Edit time, Just a note."""
        keyboard = reminder_proposal_keyboard("mem-abc")
        labels = [btn.text for btn in keyboard.inline_keyboard[0]]
        assert labels == ["Confirm", "Edit time", "Just a note"]

    def test_confirm_callback_data(self):
        """Confirm button carries IntentConfirm with confirm_reminder action."""
        keyboard = reminder_proposal_keyboard("mem-abc")
        data = json.loads(keyboard.inline_keyboard[0][0].callback_data)
        assert data == {"memory_id": "mem-abc", "action": "confirm_reminder"}

    def test_edit_time_callback_data(self):
        """Edit time button carries IntentConfirm with edit_reminder_time action."""
        keyboard = reminder_proposal_keyboard("mem-abc")
        data = json.loads(keyboard.inline_keyboard[0][1].callback_data)
        assert data == {"memory_id": "mem-abc", "action": "edit_reminder_time"}

    def test_just_a_note_callback_data(self):
        """Just a note button carries IntentConfirm with just_a_note action."""
        keyboard = reminder_proposal_keyboard("mem-abc")
        data = json.loads(keyboard.inline_keyboard[0][2].callback_data)
        assert data == {"memory_id": "mem-abc", "action": "just_a_note"}

    def test_memory_id_propagated(self):
        """All buttons reference the correct memory_id."""
        memory_id = "unique-id-999"
        keyboard = reminder_proposal_keyboard(memory_id)
        for btn in keyboard.inline_keyboard[0]:
            data = json.loads(btn.callback_data)
            assert data["memory_id"] == memory_id


class TestTaskProposalKeyboard:
    """Tests for task_proposal_keyboard."""

    def test_returns_single_row(self):
        """Keyboard has exactly one row."""
        keyboard = task_proposal_keyboard("mem-xyz")
        assert len(keyboard.inline_keyboard) == 1

    def test_row_has_three_buttons(self):
        """The single row contains exactly three buttons."""
        keyboard = task_proposal_keyboard("mem-xyz")
        row = keyboard.inline_keyboard[0]
        assert len(row) == 3

    def test_button_labels(self):
        """Buttons are labelled Confirm, Edit, Just a note."""
        keyboard = task_proposal_keyboard("mem-xyz")
        labels = [btn.text for btn in keyboard.inline_keyboard[0]]
        assert labels == ["Confirm", "Edit", "Just a note"]

    def test_confirm_callback_data(self):
        """Confirm button carries IntentConfirm with confirm_task action."""
        keyboard = task_proposal_keyboard("mem-xyz")
        data = json.loads(keyboard.inline_keyboard[0][0].callback_data)
        assert data == {"memory_id": "mem-xyz", "action": "confirm_task"}

    def test_edit_callback_data(self):
        """Edit button carries IntentConfirm with edit_task action."""
        keyboard = task_proposal_keyboard("mem-xyz")
        data = json.loads(keyboard.inline_keyboard[0][1].callback_data)
        assert data == {"memory_id": "mem-xyz", "action": "edit_task"}

    def test_just_a_note_callback_data(self):
        """Just a note button carries IntentConfirm with just_a_note action."""
        keyboard = task_proposal_keyboard("mem-xyz")
        data = json.loads(keyboard.inline_keyboard[0][2].callback_data)
        assert data == {"memory_id": "mem-xyz", "action": "just_a_note"}

    def test_memory_id_propagated(self):
        """All buttons reference the correct memory_id."""
        memory_id = "task-mem-42"
        keyboard = task_proposal_keyboard(memory_id)
        for btn in keyboard.inline_keyboard[0]:
            data = json.loads(btn.callback_data)
            assert data["memory_id"] == memory_id


class TestGeneralNoteKeyboard:
    """Tests for general_note_keyboard."""

    def test_returns_two_rows(self):
        """Keyboard has exactly two rows."""
        keyboard = general_note_keyboard("mem-1", ["work", "health"])
        assert len(keyboard.inline_keyboard) == 2

    def test_first_row_has_two_buttons(self):
        """First row (tag confirmation) contains two buttons."""
        keyboard = general_note_keyboard("mem-1", ["work"])
        assert len(keyboard.inline_keyboard[0]) == 2

    def test_second_row_has_two_buttons(self):
        """Second row (task/remind options) contains two buttons."""
        keyboard = general_note_keyboard("mem-1", ["work"])
        assert len(keyboard.inline_keyboard[1]) == 2

    def test_first_row_labels(self):
        """First row buttons are labelled Confirm Tags and Edit Tags."""
        keyboard = general_note_keyboard("mem-1", ["work"])
        labels = [btn.text for btn in keyboard.inline_keyboard[0]]
        assert labels == ["Confirm Tags", "Edit Tags"]

    def test_second_row_labels(self):
        """Second row buttons are labelled Make Task and Set Reminder."""
        keyboard = general_note_keyboard("mem-1", ["work"])
        labels = [btn.text for btn in keyboard.inline_keyboard[1]]
        assert labels == ["Make Task", "Set Reminder"]

    def test_confirm_tags_callback_data(self):
        """Confirm Tags button carries TagConfirm with confirm_all action."""
        keyboard = general_note_keyboard("mem-1", [])
        data = json.loads(keyboard.inline_keyboard[0][0].callback_data)
        assert data == {"memory_id": "mem-1", "action": "confirm_all"}

    def test_edit_tags_callback_data(self):
        """Edit Tags button carries TagConfirm with edit action."""
        keyboard = general_note_keyboard("mem-1", [])
        data = json.loads(keyboard.inline_keyboard[0][1].callback_data)
        assert data == {"memory_id": "mem-1", "action": "edit"}

    def test_make_task_callback_data(self):
        """Make Task button carries MemoryAction with set_task action."""
        keyboard = general_note_keyboard("mem-1", [])
        data = json.loads(keyboard.inline_keyboard[1][0].callback_data)
        assert data == {"action": "set_task", "memory_id": "mem-1"}

    def test_set_reminder_callback_data(self):
        """Set Reminder button carries MemoryAction with set_reminder action."""
        keyboard = general_note_keyboard("mem-1", [])
        data = json.loads(keyboard.inline_keyboard[1][1].callback_data)
        assert data == {"action": "set_reminder", "memory_id": "mem-1"}

    def test_works_with_empty_tags(self):
        """Keyboard is valid even with an empty suggested_tags list."""
        keyboard = general_note_keyboard("mem-1", [])
        assert len(keyboard.inline_keyboard) == 2

    def test_memory_id_propagated_to_all_rows(self):
        """All buttons in both rows reference the correct memory_id."""
        memory_id = "note-mem-77"
        keyboard = general_note_keyboard(memory_id, ["tag1"])
        for row in keyboard.inline_keyboard:
            for btn in row:
                data = json.loads(btn.callback_data)
                assert data["memory_id"] == memory_id


class TestRescheduleKeyboard:
    """Tests for reschedule_keyboard."""

    def test_returns_single_row(self):
        """Keyboard has exactly one row."""
        keyboard = reschedule_keyboard("mem-rem-1")
        assert len(keyboard.inline_keyboard) == 1

    def test_row_has_two_buttons(self):
        """The single row contains exactly two buttons."""
        keyboard = reschedule_keyboard("mem-rem-1")
        assert len(keyboard.inline_keyboard[0]) == 2

    def test_button_labels(self):
        """Buttons are labelled Reschedule and Dismiss."""
        keyboard = reschedule_keyboard("mem-rem-1")
        labels = [btn.text for btn in keyboard.inline_keyboard[0]]
        assert labels == ["Reschedule", "Dismiss"]

    def test_reschedule_callback_data(self):
        """Reschedule button carries RescheduleAction with reschedule action."""
        keyboard = reschedule_keyboard("mem-rem-1")
        data = json.loads(keyboard.inline_keyboard[0][0].callback_data)
        assert data == {"memory_id": "mem-rem-1", "action": "reschedule"}

    def test_dismiss_callback_data(self):
        """Dismiss button carries RescheduleAction with dismiss action."""
        keyboard = reschedule_keyboard("mem-rem-1")
        data = json.loads(keyboard.inline_keyboard[0][1].callback_data)
        assert data == {"memory_id": "mem-rem-1", "action": "dismiss"}

    def test_memory_id_propagated(self):
        """Both buttons reference the correct memory_id."""
        memory_id = "reschedule-id-88"
        keyboard = reschedule_keyboard(memory_id)
        for btn in keyboard.inline_keyboard[0]:
            data = json.loads(btn.callback_data)
            assert data["memory_id"] == memory_id


class TestLLMFailureKeyboard:
    """Tests for llm_failure_keyboard."""

    def test_returns_single_row(self):
        """Keyboard has exactly one row."""
        keyboard = llm_failure_keyboard("mem-fail-1")
        assert len(keyboard.inline_keyboard) == 1

    def test_row_has_two_buttons(self):
        """The single row contains exactly two buttons."""
        keyboard = llm_failure_keyboard("mem-fail-1")
        assert len(keyboard.inline_keyboard[0]) == 2

    def test_button_labels(self):
        """Buttons are labelled Edit Tags and Delete."""
        keyboard = llm_failure_keyboard("mem-fail-1")
        labels = [btn.text for btn in keyboard.inline_keyboard[0]]
        assert labels == ["Edit Tags", "Delete"]

    def test_edit_tags_callback_data(self):
        """Edit Tags button carries TagConfirm with edit action."""
        keyboard = llm_failure_keyboard("mem-fail-1")
        data = json.loads(keyboard.inline_keyboard[0][0].callback_data)
        assert data == {"memory_id": "mem-fail-1", "action": "edit"}

    def test_delete_callback_data(self):
        """Delete button carries MemoryAction with confirm_delete action."""
        keyboard = llm_failure_keyboard("mem-fail-1")
        data = json.loads(keyboard.inline_keyboard[0][1].callback_data)
        assert data == {"action": "confirm_delete", "memory_id": "mem-fail-1"}

    def test_memory_id_propagated(self):
        """Both buttons reference the correct memory_id."""
        memory_id = "llm-fail-id-777"
        keyboard = llm_failure_keyboard(memory_id)
        for btn in keyboard.inline_keyboard[0]:
            data = json.loads(btn.callback_data)
            assert data["memory_id"] == memory_id
