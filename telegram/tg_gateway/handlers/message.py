"""Message handlers for the Telegram Gateway.

This module contains handlers for text messages, image messages,
and unauthorized users.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from shared_lib.enums import JobType, MediaType
from shared_lib.schemas import LLMJobCreate, MemoryCreate, QueueItem

from tg_gateway.core_client import CoreClient, CoreUnavailableError
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
            # Get metadata stored when the conversation was started
            metadata = context.user_data.get(LLM_CONVERSATION_METADATA, {})
            memory_id = metadata.get("memory_id")
            original_text = metadata.get("original_text", "")
            followup_question = metadata.get("followup_question", "")

            # Check if memory_id exists - if not, cancel and return
            if not memory_id:
                logger.error(
                    "LLM_CONVERSATION_METADATA for user %s missing memory_id",
                    user.id,
                )
                try:
                    await core_client.cancel_conversation(user.id)
                except Exception:
                    logger.exception(
                        "Failed to cancel conversation for user %s", user.id
                    )
                await msg.reply_text(
                    "Something went wrong. Please try again."
                )
                return

            # User is replying to a followup question
            conv_resp = await core_client.reply_to_conversation(
                user.id, msg.text
            )

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
            await core_client.enqueue_message(
                user.id, content=msg.text, message_timestamp=msg.date
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
        await core_client.enqueue_message(
            user.id, content=msg.text, message_timestamp=msg.date
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
    """Handle an incoming image message.

    Always downloads and uploads the image immediately to prevent loss.
    Then enqueues and either processes immediately or waits for the active
    conversation to finish.

    Args:
        update: The Telegram update.
        context: The context with bot_data and user_data.
    """
    user = update.message.from_user
    msg = update.message
    photo = msg.photo[-1]
    caption = msg.caption or ""
    core_client: CoreClient = context.bot_data["core_client"]

    try:
        await core_client.ensure_user(user.id, user.full_name)

        # 1. Create memory immediately
        try:
            memory = await core_client.create_memory(
                MemoryCreate(
                    owner_user_id=user.id,
                    content=caption,
                    media_type=MediaType.image,
                    media_file_id=photo.file_id,
                    source_chat_id=msg.chat_id,
                    source_message_id=msg.message_id,
                )
            )
        except Exception:
            logger.exception("Failed to create memory for image from user %s", user.id)
            await msg.reply_text("Something went wrong saving your image. Please try again.")
            return

        # 2. Download from Telegram and upload to Core immediately (non-fatal)
        local_path = await download_and_upload_image(
            context.bot, core_client, memory.id, photo.file_id,
        )

        # 3. Enqueue with memory_id and local_path
        await core_client.enqueue_message(
            user_id=user.id,
            content=caption,
            memory_id=memory.id,
            image_local_path=local_path,
            message_timestamp=msg.date,
        )

        # 4. Check for active conversation
        active_conv = await core_client.get_active_conversation(user.id)

        if active_conv and active_conv.state in ("processing", "awaiting_reply"):
            status = await core_client.get_queue_status(user.id)
            ahead = status.queue_length
            word = "message" if ahead == 1 else "messages"
            await msg.reply_text(f"Added to queue ({ahead} {word} ahead)")
        else:
            dequeue_resp = await core_client.dequeue_message(user.id)
            if dequeue_resp.item:
                await core_client.start_conversation(user.id, queue_item_id=dequeue_resp.item.id)
                await _process_image_queue_item(
                    core_client, user.id, dequeue_resp.item,
                )
                await msg.reply_text("Processing your image...")
            else:
                logger.warning(
                    "Dequeue returned no item for image from user %s", user.id
                )
    except CoreUnavailableError:
        await msg.reply_text(
            "I'm having trouble right now, please try again in a moment."
        )
        return


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


async def _process_image_queue_item(
    core_client: CoreClient, user_id: int, queue_item: QueueItem,
) -> None:
    """Create an image_tag LLM job for a dequeued image item.

    The image has already been downloaded and uploaded to Core at receipt time.
    The queue_item contains memory_id and image_local_path from that upload.
    """
    if not queue_item.image_local_path:
        logger.warning(
            "Skipping image tag job for memory %s: no local path (download failed at receipt)",
            queue_item.memory_id,
        )
        return

    try:
        await core_client.create_llm_job(
            LLMJobCreate(
                job_type=JobType.image_tag,
                payload={
                    "memory_id": queue_item.memory_id,
                    "image_path": queue_item.image_local_path,
                },
                user_id=user_id,
            )
        )
    except Exception:
        logger.exception("Failed to queue image tag job for memory %s", queue_item.memory_id)


async def _process_next_queue_item(
    core_client: CoreClient, user_id: int,
) -> bool:
    """Dequeue and process the next queue item. Returns True if an item was processed."""
    dequeue_resp = await core_client.dequeue_message(user_id)
    if not dequeue_resp.item:
        return False

    item = dequeue_resp.item
    await core_client.start_conversation(user_id, queue_item_id=item.id)

    if item.memory_id:
        # Image item — create image_tag LLM job
        await _process_image_queue_item(core_client, user_id, item)
    else:
        # Text item — create intent_classify LLM job
        try:
            settings = await core_client.get_settings(user_id)
            user_tz = settings.timezone
        except Exception:
            user_tz = "UTC"
        await core_client.create_llm_job(
            LLMJobCreate(
                job_type=JobType.intent_classify,
                payload={
                    "message": item.content,
                    "memory_id": None,
                    "original_timestamp": (
                        item.message_timestamp.isoformat() if item.message_timestamp else None
                    ),
                    "user_timezone": user_tz,
                },
                user_id=user_id,
            )
        )

    return True


# Export handler functions for registration in main.py
text_message_handler = handle_text
photo_message_handler = handle_image
unauthorized_handler = handle_unauthorized
