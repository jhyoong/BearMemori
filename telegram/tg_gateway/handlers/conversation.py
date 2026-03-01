"""Conversation handlers for multi-step flows.

This module handles pending conversation states triggered by callback buttons.
When a callback handler starts a multi-step flow, it sets a key in context.user_data.
The next text message from the user is routed to the appropriate handler here.
"""

import logging
from datetime import datetime
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from shared_lib.enums import JobType
from shared_lib.schemas import LLMJobCreate, TagsAddRequest, TaskCreate, ReminderCreate

logger = logging.getLogger(__name__)

# Conversation pending state keys
PENDING_TAG_MEMORY_ID = "pending_tag_memory_id"
PENDING_TASK_MEMORY_ID = "pending_task_memory_id"
PENDING_REMINDER_MEMORY_ID = "pending_reminder_memory_id"
PENDING_LLM_CONVERSATION = "pending_llm_conversation"
AWAITING_BUTTON_ACTION = "awaiting_button_action"

# Queue counter key — tracks how many LLM jobs are in flight for this user
USER_QUEUE_COUNT = "user_queue_count"


# ---------------------------------------------------------------------------
# Queue counter helpers
# ---------------------------------------------------------------------------


def increment_queue(context: ContextTypes.DEFAULT_TYPE) -> int:
    """Increment the in-flight LLM job counter for the current user.

    Args:
        context: The Telegram context with user_data.

    Returns:
        The new queue count after incrementing.
    """
    count = context.user_data.get(USER_QUEUE_COUNT, 0) + 1
    context.user_data[USER_QUEUE_COUNT] = count
    return count


def decrement_queue(context: ContextTypes.DEFAULT_TYPE) -> int:
    """Decrement the in-flight LLM job counter for the current user.

    Clamps at zero so the counter never goes negative.

    Args:
        context: The Telegram context with user_data.

    Returns:
        The new queue count after decrementing (minimum 0).
    """
    count = max(0, context.user_data.get(USER_QUEUE_COUNT, 0) - 1)
    context.user_data[USER_QUEUE_COUNT] = count
    return count


def get_queue_count(context: ContextTypes.DEFAULT_TYPE) -> int:
    """Return the current in-flight LLM job count for the user.

    Args:
        context: The Telegram context with user_data.

    Returns:
        Current queue count (0 if not set).
    """
    return context.user_data.get(USER_QUEUE_COUNT, 0)


# ---------------------------------------------------------------------------
# Date/time parsing utility
# ---------------------------------------------------------------------------


def parse_datetime(text: str) -> Optional[datetime]:
    """Parse date/time strings in multiple formats.

    Returns a naive datetime (no tzinfo). The caller is responsible for
    interpreting it in the correct timezone and converting to UTC.

    Args:
        text: Date/time string to parse

    Returns:
        Naive datetime or None if parsing fails
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
            return dt
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# Conversation state handlers
# ---------------------------------------------------------------------------


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
    except Exception:
        logger.exception(f"Failed to add tags to memory {memory_id}")
        await update.message.reply_text("Failed to add tags. Please try again.")
        # Re-set the pending state so user can retry
        context.user_data[PENDING_TAG_MEMORY_ID] = memory_id


async def receive_custom_date(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle custom due date submitted by the user in a conversation flow.

    Called when the user sends text while pending_task_memory_id is set in user_data.
    Fetches the memory content from core and creates a task with that content as
    the description, using the user-supplied date as the due date.

    Args:
        update: The Telegram update.
        context: The context with user_data containing the pending memory ID.
    """
    from tg_gateway.tz_utils import to_utc, format_for_user

    user = update.message.from_user
    text = update.message.text.strip()

    # Get pending memory ID and clear the state
    memory_id = context.user_data.pop(PENDING_TASK_MEMORY_ID, None)
    if memory_id is None:
        logger.warning(f"User {user.id} sent custom date but no pending memory ID")
        await update.message.reply_text("Something went wrong. Please try again.")
        return

    # Try to parse the date using the utility function (returns naive datetime)
    due_at_naive = parse_datetime(text)

    if due_at_naive is None:
        await update.message.reply_text(
            "Could not parse the date. Please use format YYYY-MM-DD HH:MM"
            " (e.g., 2024-12-25 09:00)."
        )
        # Re-set the pending state
        context.user_data[PENDING_TASK_MEMORY_ID] = memory_id
        return

    # Get core client from bot_data
    core_client = context.bot_data["core_client"]

    # Fetch user timezone and convert to UTC
    try:
        settings = await core_client.get_settings(user.id)
        tz_name = settings.timezone
    except Exception:
        tz_name = "UTC"

    due_at = to_utc(due_at_naive, tz_name)

    # Fetch memory content to use as the task description
    description = "Task"
    try:
        memory = await core_client.get_memory(memory_id)
        if memory and memory.content:
            description = memory.content
    except Exception:
        logger.exception(f"Failed to fetch memory {memory_id} content for task description")

    # Create task with custom due date and real memory content
    task_data = TaskCreate(
        memory_id=memory_id,
        owner_user_id=user.id,
        description=description,
        due_at=due_at,
    )

    try:
        await core_client.create_task(task_data)
        await update.message.reply_text(
            f"Task created with due date: {format_for_user(due_at, tz_name)}"
        )
    except Exception:
        logger.exception(f"Failed to create task for memory {memory_id}")
        await update.message.reply_text("Failed to create task. Please try again.")


async def receive_custom_reminder(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle custom reminder time submitted by the user in a conversation flow.

    Called when the user sends text while pending_reminder_memory_id is set in user_data.
    Fetches the memory content from core and uses it as the reminder text.

    Args:
        update: The Telegram update.
        context: The context with user_data containing the pending memory ID.
    """
    from tg_gateway.tz_utils import to_utc, format_for_user

    user = update.message.from_user
    text = update.message.text.strip()

    # Get pending memory ID and clear the state
    memory_id = context.user_data.pop(PENDING_REMINDER_MEMORY_ID, None)
    if memory_id is None:
        logger.warning(f"User {user.id} sent custom reminder but no pending memory ID")
        await update.message.reply_text("Something went wrong. Please try again.")
        return

    # Try to parse the reminder time using the utility function (returns naive datetime)
    remind_at_naive = parse_datetime(text)

    if remind_at_naive is None:
        await update.message.reply_text(
            "Could not parse the time. Please use a format like '2024-12-25 14:00'."
        )
        # Re-set the pending state
        context.user_data[PENDING_REMINDER_MEMORY_ID] = memory_id
        return

    # Get core client from bot_data
    core_client = context.bot_data["core_client"]

    # Fetch user timezone and convert to UTC
    try:
        settings = await core_client.get_settings(user.id)
        tz_name = settings.timezone
    except Exception:
        tz_name = "UTC"

    remind_at = to_utc(remind_at_naive, tz_name)

    # Fetch memory content to use as the reminder text
    reminder_text = "Reminder"
    try:
        memory = await core_client.get_memory(memory_id)
        if memory and memory.content:
            reminder_text = memory.content
    except Exception:
        logger.exception(f"Failed to fetch memory {memory_id} content for reminder text")

    # Create reminder with custom time and real memory content
    reminder_data = ReminderCreate(
        memory_id=memory_id,
        owner_user_id=user.id,
        text=reminder_text,
        fire_at=remind_at,
    )

    try:
        await core_client.create_reminder(reminder_data)
        await update.message.reply_text(
            f"Reminder set for: {format_for_user(remind_at, tz_name)}"
        )
    except Exception:
        logger.exception(f"Failed to create reminder for memory {memory_id}")
        await update.message.reply_text("Failed to create reminder. Please try again.")


async def receive_followup_answer(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle the user's reply to an LLM follow-up question.

    Called when the user sends text while PENDING_LLM_CONVERSATION is set in
    user_data. Extracts the original message, the LLM's question, and the
    associated memory_id from context, then creates a new followup LLM job
    with the user's answer included in the payload.

    Expected context.user_data[PENDING_LLM_CONVERSATION] structure:
        {
            "memory_id": str,
            "original_text": str,
            "followup_question": str,
        }

    Args:
        update: The Telegram update.
        context: The context with user_data containing the pending conversation state.
    """
    user = update.message.from_user
    user_answer = update.message.text.strip()

    # Pop the pending conversation state
    pending = context.user_data.pop(PENDING_LLM_CONVERSATION, None)
    if pending is None:
        logger.warning(
            f"User {user.id} sent followup answer but no pending LLM conversation state"
        )
        await update.message.reply_text("Something went wrong. Please try again.")
        return

    memory_id = pending.get("memory_id")
    original_text = pending.get("original_text", "")
    followup_question = pending.get("followup_question", "")

    if not memory_id:
        logger.error(f"PENDING_LLM_CONVERSATION for user {user.id} missing memory_id")
        await update.message.reply_text("Something went wrong. Please try again.")
        return

    # Get core client from bot_data
    core_client = context.bot_data["core_client"]

    # Re-submit as an intent_classify job with followup_context so the
    # IntentHandler uses RECLASSIFY_PROMPT with the full conversation history.
    try:
        await core_client.create_llm_job(
            LLMJobCreate(
                job_type=JobType.intent_classify,
                payload={
                    "message": original_text,
                    "memory_id": memory_id,
                    "followup_context": {
                        "followup_question": followup_question,
                        "user_answer": user_answer,
                    },
                },
                user_id=user.id,
            )
        )
        from tg_gateway.handlers.message import _get_submission_feedback

        feedback_message = await _get_submission_feedback(context)
        await update.message.reply_text(feedback_message)
    except Exception:
        logger.exception(
            f"Failed to create followup LLM job for memory {memory_id}, user {user.id}"
        )
        await update.message.reply_text(
            "Failed to submit your answer. Please try again."
        )
        # Re-set the pending state so the user can retry
        context.user_data[PENDING_LLM_CONVERSATION] = pending
