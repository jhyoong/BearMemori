"""Message handlers for the Telegram Gateway.

This module contains handlers for text messages, image messages,
and unauthorized users.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from shared_lib.enums import MediaType
from shared_lib.schemas import MemoryCreate
from shared_lib.redis_streams import STREAM_LLM_IMAGE_TAG, publish

from tg_gateway.core_client import CoreUnavailableError
from tg_gateway.keyboards import memory_actions_keyboard
from tg_gateway.handlers import conversation
from tg_gateway.media import download_and_upload_image

logger = logging.getLogger(__name__)

# Conversation pending state keys (for checking in text handler)
PENDING_TAG_MEMORY_ID = "pending_tag_memory_id"
PENDING_TASK_MEMORY_ID = "pending_task_memory_id"
PENDING_REMINDER_MEMORY_ID = "pending_reminder_memory_id"


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages.

    This handler has two roles:
    1. Primary: Capture new text memories
    2. Secondary: Handle pending conversation actions (tag entry, custom date, custom reminder)

    When a callback handler starts a multi-step flow, it sets a key in
    context.user_data. The next text message should be routed to the
    conversation handler, not treated as a new memory.

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

    # Capture as new memory
    core_client = context.bot_data["core_client"]

    try:
        memory_data = MemoryCreate(
            owner_user_id=user.id,
            content=msg.text,
            source_chat_id=msg.chat_id,
            source_message_id=msg.message_id,
        )
        memory = await core_client.create_memory(memory_data)
    except CoreUnavailableError:
        await msg.reply_text(
            "I'm having trouble right now, please try again in a moment."
        )
        return

    # Build keyboard and reply
    keyboard = memory_actions_keyboard(memory.id, is_image=False)
    await msg.reply_text("Saved!", reply_markup=keyboard)


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
    try:
        await download_and_upload_image(
            context.bot, core_client, memory.id, photo.file_id
        )
    except Exception as e:
        logger.exception(f"Failed to download/upload image for memory {memory.id}")

    # Publish LLM tagging job (non-fatal)
    try:
        redis_client = context.bot_data["redis"]
        job_data = {
            "memory_id": memory.id,
            "file_id": photo.file_id,
            "caption": caption,
            "user_id": user.id,
            "chat_id": msg.chat_id,
        }
        await publish(redis_client, STREAM_LLM_IMAGE_TAG, job_data)
    except Exception as e:
        logger.exception(f"Failed to publish LLM tagging job for memory {memory.id}")

    # Build keyboard and reply
    keyboard = memory_actions_keyboard(memory.id, is_image=True)
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
