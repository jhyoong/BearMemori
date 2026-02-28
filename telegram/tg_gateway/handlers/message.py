"""Message handlers for the Telegram Gateway.

This module contains handlers for text messages, image messages,
and unauthorized users.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from shared_lib.enums import JobType, MediaType
from shared_lib.schemas import LLMJobCreate, MemoryCreate

from tg_gateway.core_client import CoreUnavailableError
from tg_gateway.keyboards import memory_actions_keyboard
from tg_gateway.handlers import conversation
from tg_gateway.handlers.conversation import (
    PENDING_LLM_CONVERSATION,
    PENDING_REMINDER_MEMORY_ID,
    PENDING_TAG_MEMORY_ID,
    PENDING_TASK_MEMORY_ID,
    get_queue_count,
    increment_queue,
)
from tg_gateway.media import download_and_upload_image

logger = logging.getLogger(__name__)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages.

    Routing priority (checked in order):
    1. PENDING_TAG_MEMORY_ID — route to conversation.receive_tags
    2. PENDING_TASK_MEMORY_ID — route to conversation.receive_custom_date
    3. PENDING_REMINDER_MEMORY_ID — route to conversation.receive_custom_reminder
    4. PENDING_LLM_CONVERSATION — route to conversation.receive_followup_answer
    5. AWAITING_BUTTON_ACTION (without PENDING_LLM_CONVERSATION) — fall through to queue
    6. Default — queue text for LLM intent classification

    Args:
        update: The Telegram update.
        context: The context with bot_data and user_data.
    """
    user = update.message.from_user
    msg = update.message

    # Check for pending conversation state (order matters)
    if PENDING_TAG_MEMORY_ID in context.user_data:
        await conversation.receive_tags(update, context)
        return

    if PENDING_TASK_MEMORY_ID in context.user_data:
        await conversation.receive_custom_date(update, context)
        return

    if PENDING_REMINDER_MEMORY_ID in context.user_data:
        await conversation.receive_custom_reminder(update, context)
        return

    if PENDING_LLM_CONVERSATION in context.user_data:
        await conversation.receive_followup_answer(update, context)
        return

    # If AWAITING_BUTTON_ACTION is set (but no PENDING_LLM_CONVERSATION above),
    # the user is sending new text while buttons are displayed — fall through to queue.

    # Queue text for LLM intent classification
    core_client = context.bot_data["core_client"]

    try:
        await core_client.ensure_user(user.id, user.full_name)

        # Reply based on current queue depth
        queue_count = get_queue_count(context)
        if queue_count == 0:
            await msg.reply_text("Processing...")
        else:
            await msg.reply_text("Added to queue")

        increment_queue(context)

        await core_client.create_llm_job(
            LLMJobCreate(
                job_type=JobType.intent_classify,
                payload={
                    "message": msg.text,
                    "memory_id": None,
                    "original_timestamp": msg.date.isoformat() if msg.date else None,
                    "source_chat_id": msg.chat_id,
                    "source_message_id": msg.message_id,
                },
                user_id=user.id,
            )
        )
    except CoreUnavailableError:
        await msg.reply_text(
            "I'm having trouble right now, please try again in a moment."
        )
        return


async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming image/photo messages.

    Images are stored as pending memories with a 7-day retention window.
    The handler downloads the image, uploads it to Core, and
    publishes an LLM tagging job if Redis is available.

    Args:
        update: The Telegram update.
        context: The context with bot_data and user_data.
    """
    user = update.message.from_user
    msg = update.message

    # Get the highest resolution photo
    photo = msg.photo[-1]
    caption = msg.caption or ""

    # Create memory in Core
    core_client = context.bot_data["core_client"]

    try:
        await core_client.ensure_user(user.id, user.full_name)
        memory_data = MemoryCreate(
            owner_user_id=user.id,
            content=caption,
            media_type=MediaType.image,
            media_file_id=photo.file_id,
            source_chat_id=msg.chat_id,
            source_message_id=msg.message_id,
        )
        memory = await core_client.create_memory(memory_data)
    except CoreUnavailableError:
        await msg.reply_text(
            "I'm having trouble right now, please try again in a moment."
        )
        return

    # Download and upload image (non-fatal)
    local_path = None
    try:
        local_path = await download_and_upload_image(
            context.bot, core_client, memory.id, photo.file_id
        )
    except Exception:
        logger.exception(f"Failed to download/upload image for memory {memory.id}")

    # Queue LLM tagging job via core (non-fatal); requires image_path from upload
    if local_path:
        try:
            await core_client.create_llm_job(
                LLMJobCreate(
                    job_type=JobType.image_tag,
                    payload={"memory_id": memory.id, "image_path": local_path},
                    user_id=user.id,
                )
            )
        except Exception:
            logger.exception(f"Failed to queue LLM tagging job for memory {memory.id}")

    # Build keyboard and reply; tag actions appear after LLM suggests tags
    keyboard = memory_actions_keyboard(memory.id, is_image=False)
    await msg.reply_text("Saved as pending!", reply_markup=keyboard)


async def handle_unauthorized(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle messages from unauthorized users.

    This handler replies with a message indicating the bot is private.

    Args:
        update: The Telegram update.
        context: The context (not used).
    """
    # Try to reply to the user if possible
    if update.message:
        await update.message.reply_text(
            "Sorry, I'm a private bot. You are not authorized to use me."
        )
    elif update.callback_query:
        await update.callback_query.answer(
            "Sorry, I'm a private bot. You are not authorized to use me.",
            show_alert=True,
        )


# Export handler functions for registration in main.py
text_message_handler = handle_text
photo_message_handler = handle_image
unauthorized_handler = handle_unauthorized
