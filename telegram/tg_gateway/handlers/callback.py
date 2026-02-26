"""Callback handlers for the Telegram Gateway.

This module contains the main callback query dispatcher and handlers
for specific callback data types.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from shared_lib.schemas import (
    MemoryUpdate,
    TaskCreate,
    ReminderCreate,
    TagAdd,
    TagsAddRequest,
)
from shared_lib.enums import TaskState, MemoryStatus

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
from tg_gateway.core_client import CoreClient, CoreUnavailableError, CoreNotFoundError
from tg_gateway.handlers.conversation import (
    AWAITING_BUTTON_ACTION,
    PENDING_LLM_CONVERSATION,
    PENDING_TAG_MEMORY_ID,
    PENDING_TASK_MEMORY_ID,
    PENDING_REMINDER_MEMORY_ID,
    USER_QUEUE_COUNT,
)
from tg_gateway.keyboards import (
    due_date_keyboard,
    reminder_time_keyboard,
    delete_confirm_keyboard,
    memory_actions_keyboard,
)

logger = logging.getLogger(__name__)


def _clear_conversation_state(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear pending LLM conversation state and decrement the queue counter.

    Called by button handlers that conclude a conversation flow so that
    subsequent messages from the user are not misrouted.

    Args:
        context: The Telegram context with user_data.
    """
    context.user_data.pop(AWAITING_BUTTON_ACTION, None)
    context.user_data.pop(PENDING_LLM_CONVERSATION, None)
    count = context.user_data.get(USER_QUEUE_COUNT, 0)
    context.user_data[USER_QUEUE_COUNT] = max(0, count - 1)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main dispatcher for callback queries.

    This handler receives all callback queries and dispatches to specific
    handlers based on the callback data type.

    Args:
        update: The Telegram update.
        context: The context with bot_data and user_data.
    """
    callback_query = update.callback_query
    await callback_query.answer()  # Stop loading spinner immediately

    callback_data = callback_query.data

    # Parse callback data - try to deserialize known types
    callback_obj = _parse_callback_data(callback_data)
    if callback_obj is None:
        logger.warning(f"Unknown callback data: {callback_data[:100]}")
        return

    core_client = context.bot_data["core_client"]

    # Dispatch based on callback data type
    try:
        if isinstance(callback_obj, MemoryAction):
            await handle_memory_action(update, context, callback_obj, core_client)
        elif isinstance(callback_obj, DueDateChoice):
            await handle_due_date_choice(update, context, callback_obj, core_client)
        elif isinstance(callback_obj, ReminderTimeChoice):
            await handle_reminder_time_choice(
                update, context, callback_obj, core_client
            )
        elif isinstance(callback_obj, ConfirmDelete):
            await handle_confirm_delete(update, context, callback_obj, core_client)
        elif isinstance(callback_obj, SearchDetail):
            await handle_search_detail(update, context, callback_obj, core_client)
        elif isinstance(callback_obj, TaskAction):
            await handle_task_action(update, context, callback_obj, core_client)
        elif isinstance(callback_obj, TagConfirm):
            await handle_tag_confirm(update, context, callback_obj, core_client)
        elif isinstance(callback_obj, IntentConfirm):
            await handle_intent_confirm(update, context, callback_obj, core_client)
        elif isinstance(callback_obj, RescheduleAction):
            await handle_reschedule_action(update, context, callback_obj, core_client)
        else:
            logger.warning(f"Unhandled callback type: {type(callback_obj)}")
    except CoreUnavailableError:
        await callback_query.edit_message_text(
            "I'm having trouble reaching my backend. Please try again in a moment."
        )
    except CoreNotFoundError:
        await callback_query.edit_message_text("This item no longer exists.")
    except BadRequest as e:
        logger.exception(f"BadRequest in callback: {e}")


async def handle_invalid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handler for InvalidCallbackData (expired buttons).

    This handler is called when a user clicks on an expired callback button.
    The button data can no longer be parsed because the callback data
    has exceeded its TTL.

    Args:
        update: The Telegram update.
        context: The context (not used).
    """
    callback_query = update.callback_query
    await callback_query.answer(
        "This button has expired. Please send your message again.",
        show_alert=True,
    )


def _parse_callback_data(callback_data: str):
    """Parse callback data string into appropriate callback object.

    Args:
        callback_data: The callback data string from the button.

    Returns:
        A callback data object (MemoryAction, DueDateChoice, etc.) or None if parsing fails.
    """
    import json

    if not callback_data:
        return None

    try:
        data = json.loads(callback_data)
    except (json.JSONDecodeError, ValueError):
        return None

    # Determine the callback type based on the keys present
    if "action" in data and "task_id" in data:
        return TaskAction(action=data["action"], task_id=data["task_id"])
    elif "choice" in data and "memory_id" in data:
        # Could be DueDateChoice or ReminderTimeChoice
        choice = data["choice"]
        if choice in ("today", "tomorrow", "next_week", "no_date", "custom"):
            return DueDateChoice(memory_id=data["memory_id"], choice=choice)
        elif choice in ("1h", "tomorrow_9am", "custom"):
            return ReminderTimeChoice(memory_id=data["memory_id"], choice=choice)
    elif "confirmed" in data and "memory_id" in data:
        return ConfirmDelete(memory_id=data["memory_id"], confirmed=data["confirmed"])
    elif "memory_id" in data and "action" not in data:
        return SearchDetail(memory_id=data["memory_id"])
    elif "action" in data and "memory_id" in data:
        # Distinguish between MemoryAction, TagConfirm, IntentConfirm, and RescheduleAction
        # based on action value.
        # MemoryAction: set_task, set_reminder, add_tag, toggle_pin, confirm_delete
        # TagConfirm: confirm_all, edit
        # IntentConfirm: confirm_reminder, edit_reminder_time, confirm_task, edit_task, just_a_note
        # RescheduleAction: reschedule, dismiss
        action = data["action"]
        if action in ("confirm_all", "edit"):
            return TagConfirm(memory_id=data["memory_id"], action=action)
        elif action in (
            "confirm_reminder",
            "edit_reminder_time",
            "confirm_task",
            "edit_task",
            "just_a_note",
        ):
            return IntentConfirm(memory_id=data["memory_id"], action=action)
        elif action in ("reschedule", "dismiss"):
            return RescheduleAction(memory_id=data["memory_id"], action=action)
        elif action in (
            "set_task",
            "set_reminder",
            "add_tag",
            "toggle_pin",
            "confirm_delete",
        ):
            return MemoryAction(action=action, memory_id=data["memory_id"])

    return None


# Additional handler functions


async def handle_memory_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: MemoryAction,
    core_client: CoreClient,
) -> None:
    """Handle MemoryAction callbacks (set_task, set_reminder, add_tag, toggle_pin, confirm_delete).

    Args:
        update: The Telegram update.
        context: The context with user_data.
        callback_data: The parsed callback data.
        core_client: The Core API client.
    """
    callback_query = update.callback_query
    memory_id = callback_data.memory_id
    action = callback_data.action

    if action == "set_task":
        # Confirm the memory and show due date options keyboard
        await core_client.update_memory(memory_id, MemoryUpdate(status=MemoryStatus.confirmed))
        _clear_conversation_state(context)
        await callback_query.edit_message_text(
            "Select a due date for the task:",
            reply_markup=due_date_keyboard(memory_id),
        )

    elif action == "set_reminder":
        # Confirm the memory and show reminder time options keyboard
        await core_client.update_memory(memory_id, MemoryUpdate(status=MemoryStatus.confirmed))
        _clear_conversation_state(context)
        await callback_query.edit_message_text(
            "Select when to be reminded:",
            reply_markup=reminder_time_keyboard(memory_id),
        )

    elif action == "add_tag":
        # Confirm the memory and set conversation state key for message handler
        await core_client.update_memory(memory_id, MemoryUpdate(status=MemoryStatus.confirmed))
        _clear_conversation_state(context)
        context.user_data[PENDING_TAG_MEMORY_ID] = memory_id
        # Prompt user for tags (send message asking for comma-separated tags)
        await callback_query.edit_message_text(
            "Please send the tags for this memory as a comma-separated list (e.g., work, important, project)."
        )

    elif action == "toggle_pin":
        # Auto-save any suggested tags, then pin and confirm the memory
        memory = await core_client.get_memory(memory_id)
        if memory is not None:
            suggested_tags = [t.tag for t in memory.tags if t.status == "suggested"]
            if suggested_tags:
                await core_client.add_tags(
                    memory_id, TagsAddRequest(tags=suggested_tags, status="confirmed")
                )
        await core_client.update_memory(
            memory_id, MemoryUpdate(is_pinned=True, status=MemoryStatus.confirmed)
        )
        _clear_conversation_state(context)
        await callback_query.edit_message_text("Memory pinned and confirmed.")

    elif action == "confirm_delete":
        # Show delete confirmation keyboard
        # Check if the original message has a photo
        if callback_query.message.photo is not None:
            # Use edit_message_caption for photo messages
            await callback_query.edit_message_caption(
                "Are you sure you want to delete this memory?",
                reply_markup=delete_confirm_keyboard(memory_id),
            )
        else:
            # Use edit_message_text for text messages
            await callback_query.edit_message_text(
                "Are you sure you want to delete this memory?",
                reply_markup=delete_confirm_keyboard(memory_id),
            )


async def handle_due_date_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: DueDateChoice,
    core_client: CoreClient,
) -> None:
    """Handle DueDateChoice callbacks (today, tomorrow, next_week, no_date, custom).

    This is a stub - implementation in T008.

    Args:
        update: The Telegram update.
        context: The context with user_data.
        callback_data: The parsed callback data.
        core_client: The Core API client.
    """
    from datetime import datetime, timedelta

    callback_query = update.callback_query
    memory_id = callback_data.memory_id
    choice = callback_data.choice
    user_id = update.effective_user.id

    # Handle custom date - prompt user for date entry
    if choice == "custom":
        context.user_data[PENDING_TASK_MEMORY_ID] = memory_id
        await callback_query.edit_message_text(
            "Please enter a custom due date and time (e.g., 2024-12-31 09:00):"
        )
        return

    # Calculate the due date based on choice
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    if choice == "today":
        due_at = today
    elif choice == "tomorrow":
        due_at = today + timedelta(days=1)
    elif choice == "next_week":
        due_at = today + timedelta(days=7)
    elif choice == "no_date":
        due_at = None
    else:
        logger.warning(f"Unknown due date choice: {choice}")
        return

    # Get the memory to get its content for task description
    memory = await core_client.get_memory(memory_id)
    if memory is None:
        await callback_query.edit_message_text("Memory not found.")
        return

    # Create the task description from memory content
    description = memory.content if memory.content else "Task from memory"

    # Create the task
    task_create = TaskCreate(
        memory_id=memory_id,
        owner_user_id=user_id,
        description=description,
        due_at=due_at,
    )

    await core_client.create_task(task_create)

    # Format confirmation message
    if due_at:
        due_date_str = due_at.strftime("%Y-%m-%d")
        await callback_query.edit_message_text(
            f"Task created with due date: {due_date_str}"
        )
    else:
        await callback_query.edit_message_text("Task created with no due date.")


async def handle_reminder_time_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: ReminderTimeChoice,
    core_client: CoreClient,
) -> None:
    """Handle ReminderTimeChoice callbacks (1h, tomorrow_9am, custom).

    Implementation for T009.

    Args:
        update: The Telegram update.
        context: The context with user_data.
        callback_data: The parsed callback data.
        core_client: The Core API client.
    """
    from datetime import datetime, timedelta

    callback_query = update.callback_query
    memory_id = callback_data.memory_id
    choice = callback_data.choice
    user_id = update.effective_user.id

    # Handle custom reminder time - prompt user for custom time
    if choice == "custom":
        context.user_data[PENDING_REMINDER_MEMORY_ID] = memory_id
        await callback_query.edit_message_text(
            "Please enter a custom reminder time in YYYY-MM-DD HH:MM format "
            "(e.g., 2024-12-31 14:30):"
        )
        return

    # Get the memory to get its content for reminder text
    memory = await core_client.get_memory(memory_id)
    if memory is None:
        await callback_query.edit_message_text("Memory not found.")
        return

    # Use memory content as the reminder text, or fallback
    reminder_text = memory.content if memory.content else "Reminder for your memory"

    # Calculate the reminder time based on choice
    now = datetime.now()

    if choice == "1h":
        # Reminder for 1 hour from now
        fire_at = now + timedelta(hours=1)
    elif choice == "tomorrow_9am":
        # Try to get user settings for default reminder time, fallback to 9am
        try:
            _settings = await core_client.get_settings(user_id)
            # User settings might have a default reminder time preference
            # For now, use 9am as default (could be extended to read from settings)
            default_hour = 9
            default_minute = 0
        except Exception:
            # If settings not available, use default 9am
            default_hour = 9
            default_minute = 0

        # Calculate tomorrow at 9am
        tomorrow = now.date() + timedelta(days=1)
        fire_at = datetime.combine(
            tomorrow,
            datetime.min.time().replace(hour=default_hour, minute=default_minute),
        )
    else:
        logger.warning(f"Unknown reminder time choice: {choice}")
        return

    # Create the reminder
    reminder_create = ReminderCreate(
        memory_id=memory_id,
        owner_user_id=user_id,
        text=reminder_text,
        fire_at=fire_at,
    )

    await core_client.create_reminder(reminder_create)

    # Format confirmation message
    reminder_time_str = fire_at.strftime("%Y-%m-%d %H:%M")
    await callback_query.edit_message_text(f"Reminder set for {reminder_time_str}")


async def handle_confirm_delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: ConfirmDelete,
    core_client: CoreClient,
) -> None:
    """Handle ConfirmDelete callbacks (confirmed=True/False).

    Implementation for T010.

    Args:
        update: The Telegram update.
        context: The context with bot_data.
        callback_data: The parsed callback data.
        core_client: The Core API client.
    """
    callback_query = update.callback_query
    memory_id = callback_data.memory_id
    confirmed = callback_data.confirmed

    if confirmed:
        # Delete the memory and show confirmation message
        await core_client.delete_memory(memory_id)
        _clear_conversation_state(context)
        # Check if the original message has a photo
        if callback_query.message.photo is not None:
            # Use edit_message_caption for photo messages
            await callback_query.edit_message_caption("Memory deleted")
        else:
            # Use edit_message_text for text messages
            await callback_query.edit_message_text("Memory deleted")
    else:
        # Cancel and restore the original keyboard
        # Get the memory to check if it has an image
        memory = await core_client.get_memory(memory_id)
        if memory is None:
            await callback_query.edit_message_text("Memory not found.")
            return

        # Check if memory has an image
        is_image = memory.media_type == "image"

        # Get the original message text (content)
        message_text = memory.content if memory.content else "Memory"

        # Restore the original keyboard
        # Check if the original message has a photo
        if callback_query.message.photo is not None:
            # Use edit_message_caption for photo messages
            await callback_query.edit_message_caption(
                message_text,
                reply_markup=memory_actions_keyboard(memory_id, is_image=is_image),
            )
        else:
            # Use edit_message_text for text messages
            await callback_query.edit_message_text(
                message_text,
                reply_markup=memory_actions_keyboard(memory_id, is_image=is_image),
            )


async def handle_search_detail(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: SearchDetail,
    core_client: CoreClient,
) -> None:
    """Handle SearchDetail callbacks.

    Implementation for T011a.

    Args:
        update: The Telegram update.
        context: The context with bot_data and user_data.
        callback_data: The parsed callback data.
        core_client: The Core API client.
    """

    callback_query = update.callback_query
    memory_id = callback_data.memory_id

    # Get memory by ID
    memory = await core_client.get_memory(memory_id)
    if memory is None:
        await callback_query.edit_message_text("Memory not found.")
        return

    # Check if memory has an image
    is_image = memory.media_type == "image"

    # Prepare the message text
    message_text = memory.content if memory.content else "Memory"

    # Create keyboard for actions
    reply_markup = memory_actions_keyboard(memory_id, is_image=is_image)

    # If it's an image, send the photo with the keyboard
    if is_image and memory.media_file_id:
        # Send photo using file_id
        await callback_query.message.reply_photo(
            photo=memory.media_file_id,
            caption=message_text,
            reply_markup=reply_markup,
        )
    else:
        # Send text message with keyboard
        await callback_query.edit_message_text(
            text=message_text,
            reply_markup=reply_markup,
        )


async def handle_task_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: TaskAction,
    core_client: CoreClient,
) -> None:
    """Handle TaskAction callbacks.

    Implementation for T011b.

    Args:
        update: The Telegram update.
        context: The context with user_data.
        callback_data: The parsed callback data.
        core_client: The Core API client.
    """
    from shared_lib.schemas import TaskUpdate

    callback_query = update.callback_query
    task_id = callback_data.task_id
    action = callback_data.action

    if action == "mark_done":
        # Update task to done state
        updated_task = await core_client.update_task(
            task_id, TaskUpdate(state=TaskState.DONE)
        )

        # Build response message
        message = "Task marked as done!"

        # If task has recurrence, note next instance creation
        if updated_task.recurrence_minutes:
            message += (
                f" Next instance created (recurs every "
                f"{updated_task.recurrence_minutes} min)."
            )

        await callback_query.edit_message_text(message)


async def handle_tag_confirm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: TagConfirm,
    core_client: CoreClient,
) -> None:
    """Handle TagConfirm callbacks.

    Implementation for T011c.

    Args:
        update: The Telegram update.
        context: The context with user_data.
        callback_data: The parsed callback data.
        core_client: The Core API client.
    """
    from shared_lib.schemas import MemoryUpdate
    from shared_lib.enums import MemoryStatus

    callback_query = update.callback_query
    memory_id = callback_data.memory_id
    action = callback_data.action

    if action == "confirm_all":
        # Get the memory to get suggested tags
        memory = await core_client.get_memory(memory_id)
        if memory is None:
            await callback_query.edit_message_text("Memory not found.")
            return

        # Get suggested tags (tags with status "suggested")
        suggested_tags = [t.tag for t in memory.tags if t.status == "suggested"]

        # Confirm all suggested tags in a single batch call
        if suggested_tags:
            await core_client.add_tags(
                memory_id, TagsAddRequest(tags=suggested_tags, status="confirmed")
            )

        # Update memory status to confirmed
        await core_client.update_memory(
            memory_id, MemoryUpdate(status=MemoryStatus.confirmed)
        )

        _clear_conversation_state(context)
        tags_str = ", ".join(suggested_tags) if suggested_tags else "all tags"
        await callback_query.edit_message_text(f"Tags confirmed: {tags_str}")

    elif action == "edit":
        # Confirm the memory and set conversation state key for message handler
        await core_client.update_memory(
            memory_id, MemoryUpdate(status=MemoryStatus.confirmed)
        )
        _clear_conversation_state(context)
        context.user_data[PENDING_TAG_MEMORY_ID] = memory_id
        # Prompt user for comma-separated tag input
        await callback_query.edit_message_text(
            "Please send the tags for this memory as a comma-separated list (e.g., work, important, project)."
        )


async def handle_intent_confirm(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: IntentConfirm,
    core_client: CoreClient,
) -> None:
    """Handle IntentConfirm callbacks.

    Confirms the memory and routes to the appropriate follow-up flow depending
    on the action chosen by the user.

    Actions:
        confirm_reminder: Confirm memory, show reminder time keyboard.
        edit_reminder_time: Confirm memory, show reminder time keyboard.
        confirm_task: Confirm memory, show due date keyboard.
        edit_task: Confirm memory, show due date keyboard.
        just_a_note: Confirm memory, acknowledge as a note.

    Args:
        update: The Telegram update.
        context: The context with user_data.
        callback_data: The parsed callback data.
        core_client: The Core API client.
    """
    callback_query = update.callback_query
    memory_id = callback_data.memory_id
    action = callback_data.action

    # All actions confirm the memory first
    await core_client.update_memory(memory_id, MemoryUpdate(status=MemoryStatus.confirmed))
    _clear_conversation_state(context)

    if action == "confirm_reminder":
        await callback_query.edit_message_text(
            "Select when to be reminded:",
            reply_markup=reminder_time_keyboard(memory_id),
        )

    elif action == "edit_reminder_time":
        await callback_query.edit_message_text(
            "Select a new reminder time:",
            reply_markup=reminder_time_keyboard(memory_id),
        )

    elif action == "confirm_task":
        await callback_query.edit_message_text(
            "Select a due date for the task:",
            reply_markup=due_date_keyboard(memory_id),
        )

    elif action == "edit_task":
        await callback_query.edit_message_text(
            "Select a due date:",
            reply_markup=due_date_keyboard(memory_id),
        )

    elif action == "just_a_note":
        await callback_query.edit_message_text(
            "Kept as a note.",
            reply_markup=memory_actions_keyboard(memory_id),
        )

    else:
        logger.warning(f"Unknown IntentConfirm action: {action}")


async def handle_reschedule_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    callback_data: RescheduleAction,
    core_client: CoreClient,
) -> None:
    """Handle RescheduleAction callbacks.

    Confirms the memory and either prompts for a new reminder time or dismisses.

    Actions:
        reschedule: Confirm memory, prompt user for a new date/time using the
                    existing receive_custom_reminder flow.
        dismiss: Confirm memory, dismiss without rescheduling.

    Args:
        update: The Telegram update.
        context: The context with user_data.
        callback_data: The parsed callback data.
        core_client: The Core API client.
    """
    callback_query = update.callback_query
    memory_id = callback_data.memory_id
    action = callback_data.action

    # All actions confirm the memory first
    await core_client.update_memory(memory_id, MemoryUpdate(status=MemoryStatus.confirmed))
    _clear_conversation_state(context)

    if action == "reschedule":
        # Reuse the existing receive_custom_reminder flow
        context.user_data[PENDING_REMINDER_MEMORY_ID] = memory_id
        await callback_query.edit_message_text(
            "Please enter a new date/time (e.g., 2024-12-31 14:30):"
        )

    elif action == "dismiss":
        await callback_query.edit_message_text("Dismissed.")

    else:
        logger.warning(f"Unknown RescheduleAction action: {action}")


# Export handler functions for registration in main.py
general_callback_handler = handle_callback
invalid_callback_handler = handle_invalid
