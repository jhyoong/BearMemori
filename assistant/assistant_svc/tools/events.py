"""Event-related tools for the assistant agent."""

import logging

logger = logging.getLogger(__name__)

LIST_EVENTS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_events",
        "description": "List the user's events, optionally filtered by status (pending, confirmed, rejected).",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "confirmed", "rejected"],
                    "description": "Filter by event status. If omitted, returns all events.",
                }
            },
        },
    },
}


async def list_events(
    client, *, owner_user_id: int, status: str | None = None, **kwargs
) -> list[dict]:
    """List events and return formatted results."""
    events = await client.list_events(owner_user_id=owner_user_id, status=status)
    return [
        {
            "id": e.id,
            "description": e.description,
            "event_time": str(e.event_time),
            "status": e.status,
        }
        for e in events
    ]
