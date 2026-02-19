"""Conversation handlers for multi-step flows.

This module handles pending conversation states triggered by callback buttons.
When a callback handler starts a multi-step flow, it sets a key in context.user_data.
The next text message from the user is routed to the appropriate handler here.
"""

import logging
from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from shared_lib.schemas import TagAdd, TaskCreate, ReminderCreate

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

    # Add each tag
    added_tags = []
    for tag in tags:
        try:
            tag_data = TagAdd(memory_id=memory_id, tag_name=tag)
            await core_client.add_tags(memory_id, tag_data)
            added_tags.append(tag)
        except Exception as e:
            logger.exception(f"Failed to add tag '{tag}' to memory {memory_id}")

    if added_tags:
        await update.message.reply_text(f"Tags added: {', '.join(added_tags)}")
    else:
        await update.message.reply_text("Failed to add tags. Please try again.")


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

    # Try to parse the date - simple parsing for now
    # In production, you'd want more sophisticated parsing
    due_at = None
    try:
        # Try parsing as ISO format first
        due_at = datetime.fromisoformat(text)
    except ValueError:
        # Try relative dates
        text_lower = text.lower()
        if "today" in text_lower:
            due_at = datetime.now().replace(hour=23, minute=59, second=0)
        elif "tomorrow" in text_lower:
            due_at = (datetime.now() + timedelta(days=1)).replace(
                hour=9, minute=0, second=0
            )
        else:
            # Try to parse as a simple date string (e.g., "2024-12-25")
            try:
                due_at = datetime.strptime(text, "%Y-%m-%d")
            except ValueError:
                pass

    if due_at is None:
        await update.message.reply_text(
            "Could not parse the date. Please use a format like '2024-12-25' or 'today', 'tomorrow'."
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

    # Try to parse the reminder time
    remind_at = None
    try:
        # Try parsing as ISO format first
        remind_at = datetime.fromisoformat(text)
    except ValueError:
        # Try relative times
        text_lower = text.lower()
        if "1 hour" in text_lower or "1h" in text_lower:
            remind_at = datetime.now() + timedelta(hours=1)
        elif "tomorrow" in text_lower and "9am" in text_lower:
            remind_at = (datetime.now() + timedelta(days=1)).replace(
                hour=9, minute=0, second=0
            )
        else:
            # Try to parse as a simple datetime string
            try:
                remind_at = datetime.strptime(text, "%Y-%m-%d %H:%M")
            except ValueError:
                try:
                    remind_at = datetime.strptime(text, "%Y-%m-%d")
                except ValueError:
                    pass

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
        remind_at=remind_at,
    )

    try:
        await core_client.create_reminder(reminder_data)
        await update.message.reply_text(
            f"Reminder set for: {remind_at.strftime('%Y-%m-%d %H:%M')}"
        )
    except Exception as e:
        logger.exception(f"Failed to create reminder for memory {memory_id}")
        await update.message.reply_text("Failed to create reminder. Please try again.")
