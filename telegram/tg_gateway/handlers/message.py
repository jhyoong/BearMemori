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
    LLM_CONVERSATION_METADATA,
    PENDING_REMINDER_MEMORY_ID,
    PENDING_TAG_MEMORY_ID,
    PENDING_TASK_MEMORY_ID,
)
from tg_gateway.media import download_and_upload_image

logger = logging.getLogger(__name__)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages.

    Routing priority (checked in order):
    1. PENDING_TAG_MEMORY_ID -- route to conversation.receive_tags
    2. PENDING_TASK_MEMORY_ID -- route to conversation.receive_custom_date
    3. PENDING_REMINDER_MEMORY_ID -- route to conversation.receive_custom_reminder
    4. Core API active conversation (awaiting_reply) -- reply to conversation
    5. Core API active conversation (processing) -- enqueue message
    6. No active conversation -- enqueue, dequeue, start conversation, create LLM job

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

    core_client = context.bot_data["core_client"]

    try:
        await core_client.ensure_user(user.id, user.full_name)

        # Check for active conversation via Core API
        active_conv = await core_client.get_active_conversation(user.id)

        if active_conv and active_conv.state == "awaiting_reply":
            # User is replying to a followup question
            conv_resp = await core_client.reply_to_conversation(
                user.id, msg.text
            )

            # Get metadata stored when the conversation was started
            metadata = context.user_data.get(LLM_CONVERSATION_METADATA, {})
            memory_id = metadata.get("memory_id")
            original_text = metadata.get("original_text", "")
            followup_question = metadata.get("followup_question", "")

            if not memory_id:
                logger.error(
                    "LLM_CONVERSATION_METADATA for user %s missing memory_id",
                    user.id,
                )
                await msg.reply_text(
                    "Something went wrong. Please try again."
                )
                return

            # Build conversation history from metadata
            user_answer = msg.text.strip()
            try:
                await core_client.create_llm_job(
                    LLMJobCreate(
                        job_type=JobType.followup,
                        payload={
                            "memory_id": memory_id,
                            "message": original_text,
                            "original_timestamp": metadata.get(
                                "original_timestamp"
                            ),
                            "user_timezone": metadata.get("user_timezone"),
                            "source_chat_id": metadata.get(
                                "source_chat_id"
                            ),
                            "source_message_id": metadata.get(
                                "source_message_id"
                            ),
                            "followup_context": {
                                "followup_question": followup_question,
                                "user_answer": user_answer,
                                "conversation_history": [
                                    {
                                        "role": "user",
                                        "content": original_text,
                                    },
                                    {
                                        "role": "assistant",
                                        "content": followup_question,
                                    },
                                    {
                                        "role": "user",
                                        "content": user_answer,
                                    },
                                ],
                            },
                        },
                        user_id=user.id,
                    )
                )
                try:
                    await msg.reply_text("Processing your reply...")
                except Exception:
                    logger.exception(
                        "Failed to send feedback message to user"
                    )
            except Exception:
                logger.exception(
                    "Failed to create followup LLM job for user %s",
                    user.id,
                )
                await msg.reply_text(
                    "Failed to submit your answer. Please try again."
                )
            return

        if active_conv and active_conv.state == "processing":
            # Already processing a message -- enqueue this one
            ts = msg.date.isoformat() if msg.date else ""
            await core_client.enqueue_message(
                user.id, content=msg.text, message_timestamp=ts
            )
            queue_status = await core_client.get_queue_status(user.id)
            ahead = queue_status.queue_length
            word = "message" if ahead == 1 else "messages"
            try:
                await msg.reply_text(
                    f"Added to queue ({ahead} {word} ahead)"
                )
            except Exception:
                logger.exception(
                    "Failed to send feedback message to user"
                )
            return

        # No active conversation -- enqueue, dequeue, start, create LLM job
        ts = msg.date.isoformat() if msg.date else ""
        await core_client.enqueue_message(
            user.id, content=msg.text, message_timestamp=ts
        )
        dequeue_resp = await core_client.dequeue_message(user.id)
        item = dequeue_resp.item

        if item is None:
            logger.warning(
                "Dequeue returned no item for user %s", user.id
            )
            await msg.reply_text("Processing your message...")
            return

        await core_client.start_conversation(
            user.id, queue_item_id=item.id
        )

        # Fetch user timezone for LLM time resolution
        try:
            settings = await core_client.get_settings(user.id)
            user_tz = settings.timezone
        except Exception:
            user_tz = "UTC"

        # Try to send feedback message -- don't fail if Telegram API is down
        try:
            await msg.reply_text("Processing your message...")
        except Exception:
            logger.exception("Failed to send feedback message to user")

        await core_client.create_llm_job(
            LLMJobCreate(
                job_type=JobType.intent_classify,
                payload={
                    "message": msg.text,
                    "memory_id": None,
                    "original_timestamp": (
                        msg.date.isoformat() if msg.date else None
                    ),
                    "source_chat_id": msg.chat_id,
                    "source_message_id": msg.message_id,
                    "user_timezone": user_tz,
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
