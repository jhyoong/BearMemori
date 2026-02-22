"""Conversation handlers for multi-step flows.

This module handles pending conversation states triggered by callback buttons.
When a callback handler starts a multi-step flow, it sets a key in context.user_data.
The next text message from the user is routed to the appropriate handler here.
"""

import logging
from datetime import datetime, timedelta, timezone

from telegram import Update


def parse_datetime(text: str) -> datetime | None:
    """Parse date/time strings in multiple formats.

    Args:
        text: Date/time string to parse

    Returns:
        UTC-aware datetime or None if parsing fails
    """
    formats = [
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

    return None


from telegram.ext import ContextTypes

from shared_lib.schemas import TagAdd, TagsAddRequest, TaskCreate, ReminderCreate

logger = logging.getLogger(__name__)

# Conversation pending state keys
PENDING_TAG_MEMORY_ID = "pending_tag_memory_id"
PENDING_TASK_MEMORY_ID = "pending_task_memory_id"
PENDING_REMINDER_MEMORY_ID = "pending_reminder_memory_id"


async def receive_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle tags submitted by the user in a conversation flow.

    Called when the user sends text while pending_tag_memory_id is set in user_data.
    Parses the text as comma-separated tags and adds them to the memory.

    Args:
        update: The Telegram update.
        context: The context with user_data containing the pending memory ID.
    """
    user = update.message.from_user
    text = update.message.text.strip()

    # Get pending memory ID and clear the state
    memory_id = context.user_data.pop(PENDING_TAG_MEMORY_ID, None)
    if memory_id is None:
        logger.warning(f"User {user.id} sent tags but no pending memory ID")
        await update.message.reply_text("Something went wrong. Please try again.")
        return

    # Parse comma-separated tags
    tags = [tag.strip() for tag in text.split(",") if tag.strip()]
    if not tags:
        await update.message.reply_text("Please provide at least one tag.")
        # Re-set the pending state since we need tags
        context.user_data[PENDING_TAG_MEMORY_ID] = memory_id
        return

    # Get core client from bot_data
    core_client = context.bot_data["core_client"]

    # Add tags in a single batch call
    try:
        tags_request = TagsAddRequest(tags=tags, status="confirmed")
        await core_client.add_tags(memory_id, tags_request)
        await update.message.reply_text(f"Tags added: {', '.join(tags)}")
    except Exception as e:
        logger.exception(f"Failed to add tags to memory {memory_id}")
        await update.message.reply_text("Failed to add tags. Please try again.")
        # Re-set the pending state so user can retry
        context.user_data[PENDING_TAG_MEMORY_ID] = memory_id


async def receive_custom_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle custom due date submitted by the user in a conversation flow.

    Called when the user sends text while pending_task_memory_id is set in user_data.
    Parses the text as a custom due date and creates a task.

    Args:
        update: The Telegram update.
        context: The context with user_data containing the pending memory ID.
    """
    user = update.message.from_user
    text = update.message.text.strip()

    # Get pending memory ID and clear the state
    memory_id = context.user_data.pop(PENDING_TASK_MEMORY_ID, None)
    if memory_id is None:
        logger.warning(f"User {user.id} sent custom date but no pending memory ID")
        await update.message.reply_text("Something went wrong. Please try again.")
        return

    # Try to parse the date using the utility function
    due_at = parse_datetime(text)

    if due_at is None:
        await update.message.reply_text(
            "Could not parse the date. Please use format YYYY-MM-DD HH:MM (e.g., 2024-12-25 09:00)."
        )
        # Re-set the pending state
        context.user_data[PENDING_TASK_MEMORY_ID] = memory_id
        return

    # Get core client from bot_data
    core_client = context.bot_data["core_client"]

    # Create task with custom due date
    task_data = TaskCreate(
        memory_id=memory_id,
        owner_user_id=user.id,
        description=f"Task for memory",
        due_at=due_at,
    )

    try:
        await core_client.create_task(task_data)
        await update.message.reply_text(
            f"Task created with due date: {due_at.strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as e:
        logger.exception(f"Failed to create task for memory {memory_id}")
        await update.message.reply_text("Failed to create task. Please try again.")


async def receive_custom_reminder(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle custom reminder time submitted by the user in a conversation flow.

    Called when the user sends text while pending_reminder_memory_id is set in user_data.
    Parses the text as a custom reminder time and creates a reminder.

    Args:
        update: The Telegram update.
        context: The context with user_data containing the pending memory ID.
    """
    user = update.message.from_user
    text = update.message.text.strip()

    # Get pending memory ID and clear the state
    memory_id = context.user_data.pop(PENDING_REMINDER_MEMORY_ID, None)
    if memory_id is None:
        logger.warning(f"User {user.id} sent custom reminder but no pending memory ID")
        await update.message.reply_text("Something went wrong. Please try again.")
        return

    # Try to parse the reminder time using the utility function
    remind_at = parse_datetime(text)

    if remind_at is None:
        await update.message.reply_text(
            "Could not parse the time. Please use a format like '2024-12-25 14:00'."
        )
        # Re-set the pending state
        context.user_data[PENDING_REMINDER_MEMORY_ID] = memory_id
        return

    # Get core client from bot_data
    core_client = context.bot_data["core_client"]

    # Create reminder with custom time
    reminder_data = ReminderCreate(
        memory_id=memory_id,
        owner_user_id=user.id,
        text="Custom reminder",
        fire_at=remind_at,
    )

    try:
        await core_client.create_reminder(reminder_data)
        await update.message.reply_text(
            f"Reminder set for: {remind_at.strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as e:
        logger.exception(f"Failed to create reminder for memory {memory_id}")
        await update.message.reply_text("Failed to create reminder. Please try again.")
