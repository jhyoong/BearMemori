import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from tg_gateway.callback_data import (
    ConfirmDelete,
    DueDateChoice,
    IntentConfirm,
    MemoryAction,
    ReminderTimeChoice,
    RescheduleAction,
    SearchDetail,
    TagConfirm,
    TaskAction,
)


def serialize_callback(data: object) -> str:
    """Serialize callback data object to string using JSON."""
    # Handle dataclasses by converting to dict
    if hasattr(data, "__dataclass_fields__"):
        return json.dumps(data.__dict__)
    return json.dumps(data)


def memory_actions_keyboard(
    memory_id: str, is_image: bool = False
) -> InlineKeyboardMarkup:
    """Create keyboard for memory actions.

    Args:
        memory_id: The ID of the memory.
        is_image: Whether the memory is an image (adds tag confirmation row).

    Returns:
        InlineKeyboardMarkup with memory action buttons.
    """
    keyboard = []

    # First row for image memories - tag confirmation
    if is_image:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text="Confirm Tags",
                    callback_data=serialize_callback(
                        TagConfirm(memory_id=memory_id, action="confirm_all")
                    ),
                ),
                InlineKeyboardButton(
                    text="Edit Tags",
                    callback_data=serialize_callback(
                        TagConfirm(memory_id=memory_id, action="edit")
                    ),
                ),
            ]
        )

    # Second row - Task and Remind
    keyboard.append(
        [
            InlineKeyboardButton(
                text="Task",
                callback_data=serialize_callback(
                    MemoryAction(action="set_task", memory_id=memory_id)
                ),
            ),
            InlineKeyboardButton(
                text="Remind",
                callback_data=serialize_callback(
                    MemoryAction(action="set_reminder", memory_id=memory_id)
                ),
            ),
        ]
    )

    # Third row - Tag, Pin, Delete
    keyboard.append(
        [
            InlineKeyboardButton(
                text="Tag",
                callback_data=serialize_callback(
                    MemoryAction(action="add_tag", memory_id=memory_id)
                ),
            ),
            InlineKeyboardButton(
                text="Pin",
                callback_data=serialize_callback(
                    MemoryAction(action="toggle_pin", memory_id=memory_id)
                ),
            ),
            InlineKeyboardButton(
                text="Delete",
                callback_data=serialize_callback(
                    MemoryAction(action="confirm_delete", memory_id=memory_id)
                ),
            ),
        ]
    )

    return InlineKeyboardMarkup(keyboard)


def due_date_keyboard(memory_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for due date selection.

    Args:
        memory_id: The ID of the memory.

    Returns:
        InlineKeyboardMarkup with due date options.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="Today",
                callback_data=serialize_callback(
                    DueDateChoice(memory_id=memory_id, choice="today")
                ),
            ),
            InlineKeyboardButton(
                text="Tomorrow",
                callback_data=serialize_callback(
                    DueDateChoice(memory_id=memory_id, choice="tomorrow")
                ),
            ),
            InlineKeyboardButton(
                text="Next Week",
                callback_data=serialize_callback(
                    DueDateChoice(memory_id=memory_id, choice="next_week")
                ),
            ),
        ],
        [
            InlineKeyboardButton(
                text="No Date",
                callback_data=serialize_callback(
                    DueDateChoice(memory_id=memory_id, choice="no_date")
                ),
            ),
            InlineKeyboardButton(
                text="Custom",
                callback_data=serialize_callback(
                    DueDateChoice(memory_id=memory_id, choice="custom_task")
                ),
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def reminder_time_keyboard(memory_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for reminder time selection.

    Args:
        memory_id: The ID of the memory.

    Returns:
        InlineKeyboardMarkup with reminder time options.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="1 Hour",
                callback_data=serialize_callback(
                    ReminderTimeChoice(memory_id=memory_id, choice="1h")
                ),
            ),
            InlineKeyboardButton(
                text="Tomorrow 9am",
                callback_data=serialize_callback(
                    ReminderTimeChoice(memory_id=memory_id, choice="tomorrow_9am")
                ),
            ),
        ],
        [
            InlineKeyboardButton(
                text="Custom",
                callback_data=serialize_callback(
                    ReminderTimeChoice(memory_id=memory_id, choice="custom")
                ),
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def delete_confirm_keyboard(memory_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for delete confirmation.

    Args:
        memory_id: The ID of the memory.

    Returns:
        InlineKeyboardMarkup with confirm/cancel buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="Yes, delete",
                callback_data=serialize_callback(
                    ConfirmDelete(memory_id=memory_id, confirmed=True)
                ),
            ),
            InlineKeyboardButton(
                text="No, cancel",
                callback_data=serialize_callback(
                    ConfirmDelete(memory_id=memory_id, confirmed=False)
                ),
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def search_results_keyboard(results: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Create keyboard for search results.

    Args:
        results: List of tuples containing (label, memory_id).

    Returns:
        InlineKeyboardMarkup with search result buttons.
    """
    keyboard = []

    for label, memory_id in results:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=serialize_callback(SearchDetail(memory_id=memory_id)),
                ),
            ]
        )

    return InlineKeyboardMarkup(keyboard)


def task_list_keyboard(tasks: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Create keyboard for task list.

    Args:
        tasks: List of tuples containing (label, task_id).

    Returns:
        InlineKeyboardMarkup with task buttons.
    """
    keyboard = []

    for label, task_id in tasks:
        keyboard.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=serialize_callback(
                        TaskAction(action="mark_done", task_id=task_id)
                    ),
                ),
            ]
        )

    return InlineKeyboardMarkup(keyboard)


def tag_suggestion_keyboard(memory_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for tag suggestions.

    Args:
        memory_id: The ID of the memory.

    Returns:
        InlineKeyboardMarkup with confirm/edit tag buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="Confirm Tags",
                callback_data=serialize_callback(
                    TagConfirm(memory_id=memory_id, action="confirm_all")
                ),
            ),
            InlineKeyboardButton(
                text="Edit Tags",
                callback_data=serialize_callback(
                    TagConfirm(memory_id=memory_id, action="edit")
                ),
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def reminder_proposal_keyboard(memory_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for reminder intent proposal.

    Args:
        memory_id: The ID of the memory.

    Returns:
        InlineKeyboardMarkup with confirm/edit time/just a note buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="Confirm",
                callback_data=serialize_callback(
                    IntentConfirm(memory_id=memory_id, action="confirm_reminder")
                ),
            ),
            InlineKeyboardButton(
                text="Edit time",
                callback_data=serialize_callback(
                    IntentConfirm(memory_id=memory_id, action="edit_reminder_time")
                ),
            ),
            InlineKeyboardButton(
                text="Just a note",
                callback_data=serialize_callback(
                    IntentConfirm(memory_id=memory_id, action="just_a_note")
                ),
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def task_proposal_keyboard(memory_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for task intent proposal.

    Args:
        memory_id: The ID of the memory.

    Returns:
        InlineKeyboardMarkup with confirm/edit/just a note buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="Confirm",
                callback_data=serialize_callback(
                    IntentConfirm(memory_id=memory_id, action="confirm_task")
                ),
            ),
            InlineKeyboardButton(
                text="Edit",
                callback_data=serialize_callback(
                    IntentConfirm(memory_id=memory_id, action="edit_task")
                ),
            ),
            InlineKeyboardButton(
                text="Just a note",
                callback_data=serialize_callback(
                    IntentConfirm(memory_id=memory_id, action="just_a_note")
                ),
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def general_note_keyboard(
    memory_id: str, suggested_tags: list[str]
) -> InlineKeyboardMarkup:
    """Create keyboard for a general note with tag suggestions and action options.

    Args:
        memory_id: The ID of the memory.
        suggested_tags: List of suggested tag strings.

    Returns:
        InlineKeyboardMarkup with tag confirm/edit row and task/remind row.
    """
    keyboard = []

    # First row - tag confirmation
    keyboard.append(
        [
            InlineKeyboardButton(
                text="Confirm Tags",
                callback_data=serialize_callback(
                    TagConfirm(memory_id=memory_id, action="confirm_all")
                ),
            ),
            InlineKeyboardButton(
                text="Edit Tags",
                callback_data=serialize_callback(
                    TagConfirm(memory_id=memory_id, action="edit")
                ),
            ),
        ]
    )

    # Second row - task and reminder options
    keyboard.append(
        [
            InlineKeyboardButton(
                text="Make Task",
                callback_data=serialize_callback(
                    MemoryAction(action="set_task", memory_id=memory_id)
                ),
            ),
            InlineKeyboardButton(
                text="Set Reminder",
                callback_data=serialize_callback(
                    MemoryAction(action="set_reminder", memory_id=memory_id)
                ),
            ),
        ]
    )

    return InlineKeyboardMarkup(keyboard)


def reschedule_keyboard(memory_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for rescheduling a reminder.

    Args:
        memory_id: The ID of the memory.

    Returns:
        InlineKeyboardMarkup with reschedule/dismiss buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="Reschedule",
                callback_data=serialize_callback(
                    RescheduleAction(memory_id=memory_id, action="reschedule")
                ),
            ),
            InlineKeyboardButton(
                text="Dismiss",
                callback_data=serialize_callback(
                    RescheduleAction(memory_id=memory_id, action="dismiss")
                ),
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def llm_failure_keyboard(memory_id: str) -> InlineKeyboardMarkup:
    """Create keyboard for LLM failure recovery.

    Args:
        memory_id: The ID of the memory.

    Returns:
        InlineKeyboardMarkup with edit tags and delete buttons.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="Edit Tags",
                callback_data=serialize_callback(
                    TagConfirm(memory_id=memory_id, action="edit")
                ),
            ),
            InlineKeyboardButton(
                text="Delete",
                callback_data=serialize_callback(
                    MemoryAction(action="confirm_delete", memory_id=memory_id)
                ),
            ),
        ],
    ]

    return InlineKeyboardMarkup(keyboard)
