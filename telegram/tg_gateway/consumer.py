"""Redis consumer for Telegram notification stream."""

import asyncio
import logging
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

from tg_gateway.callback_data import TaskAction
from tg_gateway.handlers.conversation import (
    AWAITING_BUTTON_ACTION,
    PENDING_LLM_CONVERSATION,
    USER_QUEUE_COUNT,
)
from tg_gateway.keyboards import (
    general_note_keyboard,
    reminder_proposal_keyboard,
    reschedule_keyboard,
    search_results_keyboard,
    serialize_callback,
    tag_suggestion_keyboard,
    task_proposal_keyboard,
)

from shared_lib.redis_streams import (
    GROUP_TELEGRAM,
    STREAM_NOTIFY_TELEGRAM,
    ack,
    consume,
    create_consumer_group,
)

logger = logging.getLogger(__name__)

CONSUMER_NAME = "telegram-gw-1"

# Delay in seconds between consecutive messages sent to the same user.
FLOOD_CONTROL_DELAY_SECONDS = 1.0


async def run_notify_consumer(application: Application) -> None:
    """Main consumer loop for processing notifications from the Telegram stream.

    Args:
        application: The Telegram bot application instance.
    """
    logger.info("notify:telegram consumer started")

    redis = application.bot_data["redis"]

    # Create consumer group on start
    await create_consumer_group(redis, STREAM_NOTIFY_TELEGRAM, GROUP_TELEGRAM)

    last_user_id: str | None = None

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
                current_user_id = data.get("user_id")

                # Flood control: delay if same user received the previous message.
                if last_user_id is not None and current_user_id == last_user_id:
                    await asyncio.sleep(FLOOD_CONTROL_DELAY_SECONDS)

                await _dispatch_notification(application, data)
                await ack(redis, STREAM_NOTIFY_TELEGRAM, GROUP_TELEGRAM, message_id)

                last_user_id = current_user_id

        except asyncio.CancelledError:
            logger.info("notify:telegram consumer shutting down")
            break
        except Exception:
            logger.exception("Error in notify:telegram consumer, backing off")
            await asyncio.sleep(5)


async def _dispatch_notification(application: Application, data: dict) -> None:
    """Dispatch a notification to the Telegram bot.

    Args:
        application: The Telegram bot application instance.
        data: The notification data to dispatch.
    """
    bot = application.bot

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
        await _handle_intent_result(application, user_id, content)

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

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        text="Yes, mark done",
                        callback_data=serialize_callback(
                            TaskAction(action="mark_done", task_id=task_id)
                        ),
                    ),
                    InlineKeyboardButton(
                        text="No",
                        callback_data=serialize_callback(
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

        message = content.get("message", "")
        text = message if message else f"LLM endpoint not reachable or responsive ({job_type})."
        await bot.send_message(chat_id=user_id, text=text)
        logger.info("Sent llm_failure to user %s: %s", user_id, text[:50])

    else:
        logger.warning("Unknown message type: %s", message_type)


async def _handle_intent_result(
    application: Application, user_id: str, content: dict
) -> None:
    """Handle an llm_intent_result notification with intent-specific routing.

    Creates or references pending memories, sends appropriate keyboards, and
    sets conversation state in application.user_data.

    Args:
        application: The Telegram bot application instance (for bot and user_data).
        user_id: Telegram user ID to send the message to.
        content: The notification content dict from the LLM worker.
    """
    bot = application.bot
    intent = content.get("intent", "")
    query = content.get("query", "")
    memory_id = content.get("memory_id", "")
    suggested_tags = content.get("suggested_tags", [])
    followup_question = content.get("followup_question", "")
    # Support both 'results' (from fixed intent handler) and 'search_results' (for backward compatibility)
    results = content.get("results") or content.get("search_results", [])

    # Access user_data for state management; default to empty dict if not present.
    uid = int(user_id)
    if uid not in application.user_data:
        application.user_data[uid] = {}
    user_data = application.user_data[uid]

    if intent == "reminder":
        resolved_time = content.get("resolved_time") or content.get(
            "extracted_datetime"
        )
        # Check whether the resolved time is stale (in the past).
        if resolved_time and _is_stale(resolved_time):
            text = f'Your reminder "{query}" had a time that has already passed. Would you like to reschedule?'
            keyboard = reschedule_keyboard(memory_id)
        else:
            dt_str = resolved_time or "unspecified time"
            text = f'Reminder: "{query}" at {dt_str}'
            keyboard = reminder_proposal_keyboard(memory_id)

        await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        user_data[AWAITING_BUTTON_ACTION] = {
            "memory_id": memory_id,
            "resolved_time": resolved_time,
            "query": query,
        }
        logger.info(
            "Sent reminder intent proposal to user %s for memory %s", user_id, memory_id
        )

    elif intent == "task":
        resolved_due_time = content.get("resolved_due_time") or content.get(
            "extracted_datetime"
        )
        # Check whether the resolved due time is stale (in the past).
        if resolved_due_time and _is_stale(resolved_due_time):
            text = f'Your task "{query}" had a due date that has already passed. Would you like to reschedule?'
            keyboard = reschedule_keyboard(memory_id)
        else:
            dt_str = resolved_due_time or "unspecified date"
            text = f'Task: "{query}" due {dt_str}'
            keyboard = task_proposal_keyboard(memory_id)

        await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        user_data[AWAITING_BUTTON_ACTION] = {
            "memory_id": memory_id,
            "resolved_due_time": resolved_due_time,
            "query": query,
        }
        logger.info(
            "Sent task intent proposal to user %s for memory %s", user_id, memory_id
        )

    elif intent == "search":
        # Build (label, memory_id) tuples for the keyboard.
        results_tuples = [
            (r.get("title", "Untitled"), r.get("memory_id", "")) for r in results
        ]

        # Show the actual keywords used for the search
        keywords = content.get("keywords", [])
        keywords_text = (
            f"Searching based on keywords: {', '.join(keywords)}\n\n"
            if keywords
            else ""
        )

        if results_tuples:
            text = f'{keywords_text}Search results for "{query}":'
            keyboard = search_results_keyboard(results_tuples)
            await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        else:
            text = f'{keywords_text}No results found for "{query}".'
            await bot.send_message(chat_id=user_id, text=text)

        # Decrement queue: search is self-contained; no button action needed.
        user_data[USER_QUEUE_COUNT] = max(0, user_data.get(USER_QUEUE_COUNT, 0) - 1)
        logger.info("Sent search results to user %s for query %s", user_id, query)

    elif intent == "general_note":
        tags_display = ", ".join(suggested_tags) if suggested_tags else "none"
        text = f"Suggested tags: {tags_display}."
        keyboard = general_note_keyboard(memory_id, suggested_tags)
        await bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)
        user_data[AWAITING_BUTTON_ACTION] = {"memory_id": memory_id}
        logger.info(
            "Sent general_note proposal to user %s for memory %s", user_id, memory_id
        )

    elif intent == "ambiguous":
        await bot.send_message(chat_id=user_id, text=followup_question)
        user_data[PENDING_LLM_CONVERSATION] = {
            "memory_id": memory_id,
            "original_text": query,
            "followup_question": followup_question,
        }
        logger.info(
            "Sent ambiguous followup question to user %s for memory %s",
            user_id,
            memory_id,
        )

    else:
        logger.warning(
            "Unknown intent type '%s' for user %s, memory %s",
            intent,
            user_id,
            memory_id,
        )
        text = f'Processed: "{query}"'
        await bot.send_message(chat_id=user_id, text=text)


def _is_stale(dt_string: str) -> bool:
    """Return True if the ISO datetime string represents a past moment.

    Args:
        dt_string: ISO 8601 datetime string (e.g. "2024-01-01T09:00:00").

    Returns:
        True if the parsed datetime is before now (UTC), False otherwise.
        Returns False on parse error so we do not wrongly flag valid datetimes.
    """
    try:
        dt = datetime.fromisoformat(dt_string)
        # If no timezone info, assume UTC.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt < datetime.now(tz=timezone.utc)
    except (ValueError, TypeError):
        logger.warning("Could not parse extracted_datetime: %s", dt_string)
        return False
