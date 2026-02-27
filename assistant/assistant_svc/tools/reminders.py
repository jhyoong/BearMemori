"""Reminder-related tools for the assistant agent."""

import logging

logger = logging.getLogger(__name__)

LIST_REMINDERS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_reminders",
        "description": "List the user's reminders. By default shows only upcoming (unfired) reminders.",
        "parameters": {
            "type": "object",
            "properties": {
                "upcoming_only": {
                    "type": "boolean",
                    "description": "If true (default), only show unfired reminders.",
                }
            },
        },
    },
}


async def list_reminders(
    client, *, owner_user_id: int, upcoming_only: bool = True, **kwargs
) -> list[dict]:
    """List reminders and return formatted results."""
    reminders = await client.list_reminders(
        owner_user_id=owner_user_id, upcoming_only=upcoming_only
    )
    return [
        {
            "id": r.id,
            "text": r.text,
            "fire_at": str(r.fire_at),
            "fired": r.fired,
            "memory_id": r.memory_id,
        }
        for r in reminders
    ]


CREATE_REMINDER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_reminder",
        "description": "Create a new reminder. Always confirm with the user before calling this.",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "The memory ID to link this reminder to",
                },
                "text": {
                    "type": "string",
                    "description": "The reminder text",
                },
                "fire_at": {
                    "type": "string",
                    "description": "When to fire the reminder, in ISO 8601 format",
                },
            },
            "required": ["memory_id", "text", "fire_at"],
        },
    },
}


async def create_reminder(
    client,
    *,
    memory_id: str,
    text: str,
    fire_at: str,
    owner_user_id: int,
    **kwargs,
) -> dict:
    """Create a reminder and return formatted result."""
    reminder = await client.create_reminder(
        memory_id=memory_id,
        owner_user_id=owner_user_id,
        text=text,
        fire_at=fire_at,
    )
    return {
        "id": reminder.id,
        "text": reminder.text,
        "fire_at": str(reminder.fire_at),
    }
