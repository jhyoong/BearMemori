"""Redis consumer for Telegram notification stream."""

import asyncio
import json
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

from tg_gateway.callback_data import TaskAction
from tg_gateway.keyboards import tag_suggestion_keyboard

from shared_lib.redis_streams import (
    GROUP_TELEGRAM,
    STREAM_NOTIFY_TELEGRAM,
    ack,
    consume,
    create_consumer_group,
)

logger = logging.getLogger(__name__)

CONSUMER_NAME = "telegram-gw-1"


async def run_notify_consumer(application: Application) -> None:
    """Main consumer loop for processing notifications from the Telegram stream.

    Args:
        application: The Telegram bot application instance.
    """
    logger.info("notify:telegram consumer started")

    redis = application.bot_data["redis"]
    bot = application.bot

    # Create consumer group on start
    await create_consumer_group(redis, STREAM_NOTIFY_TELEGRAM, GROUP_TELEGRAM)

    while True:
        try:
            messages = await consume(
                redis,
                STREAM_NOTIFY_TELEGRAM,
                GROUP_TELEGRAM,
                CONSUMER_NAME,
                count=10,
                block_ms=5000,
            )

            for message_id, data in messages:
                await _dispatch_notification(bot, data)
                await ack(redis, STREAM_NOTIFY_TELEGRAM, GROUP_TELEGRAM, message_id)

        except asyncio.CancelledError:
            logger.info("notify:telegram consumer shutting down")
            break
        except Exception:
            logger.exception("Error in notify:telegram consumer, backing off")
            await asyncio.sleep(5)


async def _dispatch_notification(bot, data: dict) -> None:
    """Dispatch a notification to the Telegram bot.

    Handles 'reminder' and 'event_reprompt' message types.

    Args:
        bot: The Telegram bot instance.
        data: The notification data to dispatch.
    """
    user_id = data.get("user_id")
    message_type = data.get("message_type")
    content = data.get("content", {})

    logger.debug(
        "Dispatching notification: user_id=%s, message_type=%s, content=%s",
        user_id,
        message_type,
        content,
    )

    if message_type == "reminder":
        memory_content = content.get("memory_content", "")
        fire_at = content.get("fire_at", "")

        if fire_at:
            text = f"Reminder ({fire_at}): {memory_content}"
        else:
            text = f"Reminder: {memory_content}"

        await bot.send_message(chat_id=user_id, text=text)
        logger.info("Sent reminder to user %s: %s", user_id, text[:50])

    elif message_type == "event_reprompt":
        description = content.get("description", "")
        event_date = content.get("event_date", "")

        text = f'Reminder: I still need your confirmation on this event: "{description}" on {event_date}.'
        await bot.send_message(chat_id=user_id, text=text)
        logger.info("Sent event_reprompt to user %s: %s", user_id, text[:50])

    elif message_type == "llm_image_tag_result":
        memory_id = content.get("memory_id", "")
        tags = content.get("tags", [])
        description = content.get("description", "")

        tags_str = ", ".join(tags)
        text = f"Tag suggestions for your image:\nDescription: {description}\nSuggested tags: {tags_str}"
        keyboard = tag_suggestion_keyboard(memory_id)

        await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        logger.info("Sent llm_image_tag_result to user %s: %s", user_id, text[:50])

    elif message_type == "llm_intent_result":
        query = content.get("query", "")
        intent = content.get("intent", "")
        results = content.get("results", [])

        # Format base message with query and intent
        if intent == "ambiguous":
            text = f'Your query "{query}" is ambiguous. Could you please clarify what you\'re looking for?'
        else:
            text = f'Query: "{query}"\nDetected intent: {intent}'

        # If results exist, add them to the message
        if results:
            result_count = len(results)
            text += f"\n\nFound {result_count} result(s):"

            # Show first few titles
            for i, result in enumerate(results[:3]):
                title = result.get("title", "Untitled")
                text += f"\n{i + 1}. {title}"

            if result_count > 3:
                text += f"\n... and {result_count - 3} more"

        await bot.send_message(chat_id=user_id, text=text)
        logger.info("Sent llm_intent_result to user %s: %s", user_id, text[:100])

    elif message_type == "llm_followup_result":
        question = content.get("question", "")

        await bot.send_message(chat_id=user_id, text=question)
        logger.info("Sent llm_followup_result to user %s: %s", user_id, question[:50])

    elif message_type == "llm_task_match_result":
        task_id = content.get("task_id", "")
        task_description = content.get("task_description", "")
        memory_id = content.get("memory_id", "")

        text = f'This looks related to your task: "{task_description}"\nMark as done?'

        # Create inline keyboard with Yes/No buttons
        # "Yes" uses TaskAction with mark_done
        # "No" uses TaskAction with cancel action

        def _serialize_callback(data: object) -> str:
            if hasattr(data, "__dataclass_fields__"):
                return json.dumps(data.__dict__)
            return json.dumps(data)

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="Yes, mark done",
                        callback_data=_serialize_callback(
                            TaskAction(action="mark_done", task_id=task_id)
                        ),
                    ),
                    InlineKeyboardButton(
                        text="No",
                        callback_data=_serialize_callback(
                            TaskAction(action="cancel", task_id=task_id)
                        ),
                    ),
                ]
            ]
        )

        await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        logger.info("Sent llm_task_match_result to user %s: %s", user_id, text[:50])

    elif message_type == "event_confirmation":
        description = content.get("description", "")
        event_date = content.get("event_date", "")

        text = f'I detected an event: "{description}" on {event_date}.\nAdd as event? [Yes] [No]'
        await bot.send_message(chat_id=user_id, text=text)
        logger.info("Sent event_confirmation to user %s: %s", user_id, text[:50])

    elif message_type == "llm_failure":
        job_type = content.get("job_type", "unknown")
        memory_id = content.get("memory_id", "")

        text = f"I couldn't process your request ({job_type}). You can add tags or details manually."
        await bot.send_message(chat_id=user_id, text=text)
        logger.info("Sent llm_failure to user %s: %s", user_id, text[:50])

    else:
        logger.warning("Unknown message type: %s", message_type)
