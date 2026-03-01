"""Command handlers for the Telegram Gateway.

This module contains the command handlers for the Telegram bot.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from tg_gateway.handlers.conversation import (
    PENDING_TAG_MEMORY_ID,
    PENDING_TASK_MEMORY_ID,
    PENDING_REMINDER_MEMORY_ID,
)
from tg_gateway.keyboards import search_results_keyboard, task_list_keyboard

logger = logging.getLogger(__name__)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display the list of available commands.

    Args:
        update: The Telegram update.
        context: The context (not used).
    """
    help_text = """Available commands:
/help - Show this help message
/find <query> - Search memories
/tasks - List your tasks
/pinned - Show pinned memories
/cancel - Cancel current action"""
    await update.message.reply_text(help_text)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all pending conversation state.

    Clears any pending tag, task, or reminder memory IDs that were set
    during conversation flows.

    Args:
        update: The Telegram update.
        context: The context with user_data containing pending state.
    """
    # Clear all pending conversation states
    context.user_data.pop(PENDING_TAG_MEMORY_ID, None)
    context.user_data.pop(PENDING_TASK_MEMORY_ID, None)
    context.user_data.pop(PENDING_REMINDER_MEMORY_ID, None)

    await update.message.reply_text("Current action cancelled.")


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Search memories using Core's FTS5 search.

    Parses the query from the command arguments, calls Core API to search,
    and displays up to 5 results with inline keyboard for details.

    Args:
        update: The Telegram update.
        context: The context with bot_data containing core_client.
    """
    # Get the query from the message text (everything after "/find ")
    message_text = update.message.text
    if not message_text:
        await update.message.reply_text("Usage: /find <search query>")
        return

    # Parse query - remove "/find" prefix
    query = message_text.strip()
    if query.lower().startswith("/find"):
        query = query[5:].strip()

    # If no query provided, show usage instructions
    if not query:
        await update.message.reply_text("Usage: /find <search query>")
        return

    # Get core_client from bot_data
    core_client = context.bot_data.get("core_client")
    if not core_client:
        await update.message.reply_text("Error: Core client not available.")
        return

    # Get user ID for ownership
    user = update.effective_user
    if not user:
        await update.message.reply_text("Error: Could not identify user.")
        return

    try:
        # Call Core API to search memories
        results = await core_client.search(query=query, owner=user.id)
    except Exception:
        logger.exception("Search failed for user %s with query '%s'", user.id, query)
        await update.message.reply_text("Search failed. Please try again.")
        return

    # Handle no results
    if not results:
        await update.message.reply_text("No results found.")
        return

    # Build keyboard with up to 5 results
    keyboard_results = []
    for result in results[:5]:
        content = result.memory.content or ""
        if content:
            label = content[:50] + "..." if len(content) > 50 else content
        else:
            tags = ", ".join(t.tag for t in result.memory.tags) if result.memory.tags else ""
            label = f"[Image: {tags}]" if tags else "[Image]"
        keyboard_results.append((label, result.memory.id))

    # Create inline keyboard with search results
    keyboard = search_results_keyboard(keyboard_results)

    # Send results with keyboard
    await update.message.reply_text(
        f"Search results for '{query}':",
        reply_markup=keyboard,
    )


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """List open tasks for the user.

    Calls Core API to get tasks with state NOT_DONE, displays up to 10 tasks
    with due dates and inline keyboard for marking tasks done.

    Args:
        update: The Telegram update.
        context: The context with bot_data containing core_client.
    """
    # Get core_client from bot_data
    core_client = context.bot_data.get("core_client")
    if not core_client:
        await update.message.reply_text("Error: Core client not available.")
        return

    # Get user ID for ownership
    user = update.effective_user
    if not user:
        await update.message.reply_text("Error: Could not identify user.")
        return

    try:
        # Call Core API to list open tasks
        tasks = await core_client.list_tasks(owner_user_id=user.id, state="NOT_DONE")
    except Exception:
        logger.exception("Failed to load tasks for user %s", user.id)
        await update.message.reply_text("Failed to load tasks. Please try again.")
        return

    # Handle no tasks
    if not tasks:
        await update.message.reply_text("No open tasks.")
        return

    # Build keyboard with up to 10 tasks
    keyboard_tasks = []
    for task in tasks[:10]:
        # Create label: description + due date if available
        label = task.description
        if task.due_at:
            label = f"{task.description} - due: {task.due_at.strftime('%Y-%m-%d')}"
        keyboard_tasks.append((label, task.id))

    # Create inline keyboard with task buttons
    keyboard = task_list_keyboard(keyboard_tasks)

    # Send tasks with keyboard
    await update.message.reply_text(
        "Your open tasks:",
        reply_markup=keyboard,
    )


async def pinned_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show pinned memories for the user.

    Calls Core API to get pinned memories, displays up to 10 results
    with inline keyboard for details.

    Args:
        update: The Telegram update.
        context: The context with bot_data containing core_client.
    """
    # Get core_client from bot_data
    core_client = context.bot_data.get("core_client")
    if not core_client:
        await update.message.reply_text("Error: Core client not available.")
        return

    # Get user ID for ownership
    user = update.effective_user
    if not user:
        await update.message.reply_text("Error: Could not identify user.")
        return

    try:
        # Call Core API to get pinned memories (empty query)
        results = await core_client.search(query="", owner=user.id, pinned=True)
    except Exception:
        logger.exception("Failed to load pinned memories for user %s", user.id)
        await update.message.reply_text(
            "Failed to load pinned memories. Please try again."
        )
        return

    # Handle no results
    if not results:
        await update.message.reply_text("No pinned memories.")
        return

    # Build keyboard with up to 10 results
    keyboard_results = []
    for result in results[:10]:
        content = result.memory.content or ""
        if content:
            label = content[:50] + "..." if len(content) > 50 else content
        else:
            tags = ", ".join(t.tag for t in result.memory.tags) if result.memory.tags else ""
            label = f"[Image: {tags}]" if tags else "[Image]"
        keyboard_results.append((label, result.memory.id))

    # Create inline keyboard with search results
    keyboard = search_results_keyboard(keyboard_results)

    # Send results with keyboard
    await update.message.reply_text(
        "Your pinned memories:",
        reply_markup=keyboard,
    )


async def queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display queue statistics for admins.

    Shows LLM job queue stats including pending, processing, and queued counts.
    This command is admin-only.

    Args:
        update: The Telegram update.
        context: The context with bot_data containing core_client.
    """
    # Get core_client from bot_data
    core_client = context.bot_data.get("core_client")
    if not core_client:
        await update.message.reply_text("Error: Core client not available.")
        return

    try:
        # Call Core API to get queue stats and health data
        stats = await core_client.get_queue_stats()
    except Exception:
        logger.exception("Failed to get queue stats")
        await update.message.reply_text(
            "Failed to get queue statistics. Please try again."
        )
        return

    # Fetch stream health and LLM health (non-critical, don't fail the command)
    stream_health = None
    llm_health = None
    try:
        stream_health = await core_client.get_stream_health()
    except Exception:
        logger.warning("Failed to get stream health for /queue command")
    try:
        llm_health = await core_client.get_llm_health()
    except Exception:
        logger.warning("Failed to get LLM health for /queue command")

    # Format the response
    by_status = stats.get("by_status", {})
    by_type = stats.get("by_type", {})

    response = """*Queue Statistics*
Pending: `{total_pending}`
Processing: `{processing}`
Confirmed: `{confirmed}`
Failed: `{failed}`
Cancelled: `{cancelled}`

*By Type*
{type_stats}

Oldest queued: {oldest_age} seconds
""".format(
        total_pending=by_status.get("queued", 0),
        processing=by_status.get("processing", 0),
        confirmed=by_status.get("confirmed", 0),
        failed=by_status.get("failed", 0),
        cancelled=by_status.get("cancelled", 0),
        type_stats="\n".join(
            f"{k}: {v}" for k, v in sorted(by_type.items())
        ) or "None",
        oldest_age=stats.get("oldest_queued_age_seconds", "N/A"),
    )

    # Append stream health info if available
    if stream_health:
        streams = stream_health.get("streams", {})
        if streams:
            response += "\n*Stream Health*\n"
            for name, info in streams.items():
                length = info.get("length", 0)
                response += f"{name}: `{length}` msgs\n"

    # Append LLM health info if available
    if llm_health:
        llm_status = llm_health.get("status", "unknown")
        status_label = "Healthy" if llm_status == "healthy" else "Unhealthy"
        consecutive = llm_health.get("consecutive_failures", 0)
        last_check = llm_health.get("last_check", "N/A")
        response += f"\n*LLM Health*\n"
        response += f"Status: {status_label}\n"
        response += f"Consecutive failures: `{consecutive}`\n"
        response += f"Last check: {last_check}\n"

    await update.message.reply_text(response, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display user's pending messages count and LLM health status.

    Shows the user's current queue position and overall LLM system health.
    Available to all users.

    Args:
        update: The Telegram update.
        context: The context with bot_data containing core_client.
    """
    # Get core_client from bot_data
    core_client = context.bot_data.get("core_client")
    if not core_client:
        await update.message.reply_text("Error: Core client not available.")
        return

    # Get user ID
    user = update.effective_user
    if not user:
        await update.message.reply_text("Error: Could not identify user.")
        return

    try:
        # Call Core API to get queue stats
        stats = await core_client.get_queue_stats()
        # Call LLM-specific health endpoint
        health = await core_client.get_llm_health()
    except Exception:
        logger.exception("Failed to get status info for user %s", user.id)
        await update.message.reply_text(
            "Failed to get status information. Please try again."
        )
        return

    # Get user's pending count from by_status
    by_status = stats.get("by_status", {})
    pending_count = by_status.get("queued", 0)

    # Get health status
    health_status = health.get("status", "unknown")
    health_msg = "Healthy" if health_status == "healthy" else "Unhealthy"
    consecutive = health.get("consecutive_failures", 0)

    response = """*Your Status*
Pending messages: `{pending}`

*LLM System Health*
{health_status}
Consecutive failures: `{consecutive}`""".format(
        pending=pending_count,
        health_status=health_msg,
        consecutive=consecutive,
    )

    await update.message.reply_text(response, parse_mode="Markdown")
