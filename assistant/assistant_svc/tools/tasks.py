"""Task-related tools for the assistant agent."""

import logging

logger = logging.getLogger(__name__)

LIST_TASKS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": "List the user's tasks, optionally filtered by state (NOT_DONE or DONE).",
        "parameters": {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "enum": ["NOT_DONE", "DONE"],
                    "description": "Filter by task state. If omitted, returns all tasks.",
                }
            },
        },
    },
}


async def list_tasks(
    client, *, owner_user_id: int, state: str | None = None, **kwargs
) -> list[dict]:
    """List tasks and return formatted results."""
    tasks = await client.list_tasks(owner_user_id=owner_user_id, state=state)
    return [
        {
            "id": t.id,
            "description": t.description,
            "state": t.state,
            "due_at": str(t.due_at) if t.due_at else None,
            "memory_id": t.memory_id,
        }
        for t in tasks
    ]


CREATE_TASK_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_task",
        "description": "Create a new task linked to a memory. Always confirm with the user before calling this.",
        "parameters": {
            "type": "object",
            "properties": {
                "memory_id": {
                    "type": "string",
                    "description": "The memory ID to link this task to",
                },
                "description": {
                    "type": "string",
                    "description": "What the task is",
                },
                "due_at": {
                    "type": "string",
                    "description": "Optional due date in ISO 8601 format (e.g. 2026-03-01T10:00:00)",
                },
            },
            "required": ["memory_id", "description"],
        },
    },
}


async def create_task(
    client,
    *,
    memory_id: str,
    description: str,
    owner_user_id: int,
    due_at: str | None = None,
    **kwargs,
) -> dict:
    """Create a task and return formatted result."""
    task = await client.create_task(
        memory_id=memory_id,
        owner_user_id=owner_user_id,
        description=description,
        due_at=due_at,
    )
    return {
        "id": task.id,
        "description": task.description,
        "state": task.state,
        "due_at": str(task.due_at) if task.due_at else None,
    }
