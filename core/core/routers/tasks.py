"""Tasks router with recurrence logic."""

import logging
import uuid
from datetime import datetime, timedelta

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Query, status

from core.audit import log_audit
from core.database import get_db
from shared.schemas import (
    TaskCreate,
    TaskResponse,
    TaskUpdate,
    TaskUpdateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tasks"])


def parse_db_datetime(dt_str: str | None) -> datetime | None:
    """Parse datetime string from database, handling both 'Z' and '+00:00' formats."""
    if not dt_str:
        return None
    # Handle edge case: string ending with both timezone offset and 'Z' (e.g., '+00:00Z')
    if '+' in dt_str and dt_str.endswith('Z'):
        dt_str = dt_str[:-1]  # Remove trailing 'Z'
    # Replace 'Z' with '+00:00' for ISO parsing
    elif dt_str.endswith('Z'):
        dt_str = dt_str.replace('Z', '+00:00')
    return datetime.fromisoformat(dt_str)


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task: TaskCreate,
    db: aiosqlite.Connection = Depends(get_db),
) -> TaskResponse:
    """
    Create a new task.

    - Generate UUID
    - Insert into tasks table
    - Call log_audit() to log the creation
    - Return: TaskResponse
    """
    # Generate UUID for id
    task_id = str(uuid.uuid4())

    # Convert due_at to ISO format if provided
    if task.due_at:
        # If due_at already has timezone info, use it as-is; otherwise append 'Z'
        due_at_str = task.due_at.isoformat()
        if not due_at_str.endswith('Z') and '+' not in due_at_str and task.due_at.tzinfo is None:
            due_at_str += 'Z'
    else:
        due_at_str = None

    # Insert into tasks table
    await db.execute(
        """
        INSERT INTO tasks (
            id, memory_id, owner_user_id, description, due_at, recurrence_minutes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            task.memory_id,
            task.owner_user_id,
            task.description,
            due_at_str,
            task.recurrence_minutes,
        ),
    )
    await db.commit()

    # Log audit
    await log_audit(db, "task", task_id, "created", f"user:{task.owner_user_id}")

    # Fetch and return the created task
    cursor = await db.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (task_id,),
    )
    row = await cursor.fetchone()

    return TaskResponse(
        id=row["id"],
        memory_id=row["memory_id"],
        owner_user_id=row["owner_user_id"],
        description=row["description"],
        state=row["state"],
        due_at=parse_db_datetime(row["due_at"]),
        recurrence_minutes=row["recurrence_minutes"],
        completed_at=parse_db_datetime(row["completed_at"]),
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )


@router.get("", response_model=list[TaskResponse])
async def get_tasks(
    state: str | None = None,
    owner_user_id: int | None = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[TaskResponse]:
    """
    Get tasks with optional filters.

    Query params:
    - state (optional): Filter by task state
    - owner_user_id (optional): Filter by owner
    - due_before (optional datetime): Filter tasks due before this time
    - due_after (optional datetime): Filter tasks due after this time
    - limit (default 50): Maximum number of results
    - offset (default 0): Number of results to skip

    Return: list[TaskResponse]
    """
    # Build WHERE clauses
    where_clauses = []
    query_params = []

    if state is not None:
        where_clauses.append("state = ?")
        query_params.append(state)

    if owner_user_id is not None:
        where_clauses.append("owner_user_id = ?")
        query_params.append(owner_user_id)

    if due_before is not None:
        where_clauses.append("due_at < ?")
        due_before_str = due_before.isoformat()
        if not due_before_str.endswith('Z') and '+' not in due_before_str and due_before.tzinfo is None:
            due_before_str += 'Z'
        query_params.append(due_before_str)

    if due_after is not None:
        where_clauses.append("due_at > ?")
        due_after_str = due_after.isoformat()
        if not due_after_str.endswith('Z') and '+' not in due_after_str and due_after.tzinfo is None:
            due_after_str += 'Z'
        query_params.append(due_after_str)

    # Build query
    query = "SELECT * FROM tasks"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    query_params.extend([limit, offset])

    # Execute query
    cursor = await db.execute(query, query_params)
    rows = await cursor.fetchall()

    # Convert to TaskResponse objects
    tasks = [
        TaskResponse(
            id=row["id"],
            memory_id=row["memory_id"],
            owner_user_id=row["owner_user_id"],
            description=row["description"],
            state=row["state"],
            due_at=parse_db_datetime(row["due_at"]),
            recurrence_minutes=row["recurrence_minutes"],
            completed_at=parse_db_datetime(row["completed_at"]),
            created_at=parse_db_datetime(row["created_at"]),
            updated_at=parse_db_datetime(row["updated_at"]),
        )
        for row in rows
    ]

    return tasks


@router.patch("/{id}", response_model=TaskUpdateResponse)
async def update_task(
    id: str,
    task_update: TaskUpdate,
    db: aiosqlite.Connection = Depends(get_db),
) -> TaskUpdateResponse:
    """
    Update a task by ID.

    - Fetch existing task; 404 if not found
    - Build UPDATE query for only the provided fields
    - Always set updated_at = now
    - If state changes to DONE:
      - Set completed_at = now
      - If recurrence_minutes is set on the task:
        - Calculate new due_at
        - Create new task with same properties but new UUID and state = NOT_DONE
        - Call log_audit() for the new task
    - Call log_audit() to log the update
    - Return: TaskUpdateResponse with the updated task and optional recurring_task_id
    """
    # Fetch existing task
    cursor = await db.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Build UPDATE query for provided fields
    update_fields = []
    update_values = []
    changed_fields = {}

    if task_update.description is not None:
        update_fields.append("description = ?")
        update_values.append(task_update.description)
        changed_fields["description"] = task_update.description

    if task_update.due_at is not None:
        due_at_str = task_update.due_at.isoformat()
        if not due_at_str.endswith('Z') and '+' not in due_at_str and task_update.due_at.tzinfo is None:
            due_at_str += 'Z'
        update_fields.append("due_at = ?")
        update_values.append(due_at_str)
        changed_fields["due_at"] = due_at_str

    if task_update.recurrence_minutes is not None:
        update_fields.append("recurrence_minutes = ?")
        update_values.append(task_update.recurrence_minutes)
        changed_fields["recurrence_minutes"] = task_update.recurrence_minutes

    # Track if state changes to DONE
    state_changed_to_done = False
    recurring_task_id = None

    if task_update.state is not None:
        update_fields.append("state = ?")
        update_values.append(task_update.state)
        changed_fields["state"] = task_update.state

        # If state changes to DONE, set completed_at
        if task_update.state == "DONE" and row["state"] != "DONE":
            state_changed_to_done = True
            completed_at = datetime.utcnow().isoformat() + 'Z'
            update_fields.append("completed_at = ?")
            update_values.append(completed_at)
            changed_fields["completed_at"] = completed_at

    # Always set updated_at
    update_fields.append("updated_at = ?")
    updated_at = datetime.utcnow().isoformat() + 'Z'
    update_values.append(updated_at)

    # Add id to values for WHERE clause
    update_values.append(id)

    # Execute update
    if update_fields:
        sql = f"UPDATE tasks SET {', '.join(update_fields)} WHERE id = ?"
        await db.execute(sql, update_values)
        await db.commit()

    # Handle recurring task creation if state changed to DONE and recurrence_minutes is set
    if state_changed_to_done and row["recurrence_minutes"]:
        # Calculate new due_at
        if row["due_at"]:
            old_due_at = parse_db_datetime(row["due_at"])
            new_due_at = old_due_at + timedelta(minutes=row["recurrence_minutes"])
        else:
            new_due_at = datetime.utcnow() + timedelta(minutes=row["recurrence_minutes"])

        # Generate new task ID
        recurring_task_id = str(uuid.uuid4())

        # Create new recurring task
        await db.execute(
            """
            INSERT INTO tasks (
                id, memory_id, owner_user_id, description, state,
                due_at, recurrence_minutes
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recurring_task_id,
                row["memory_id"],
                row["owner_user_id"],
                row["description"],
                "NOT_DONE",
                new_due_at.isoformat().replace('+00:00', 'Z') if '+00:00' in new_due_at.isoformat() else new_due_at.isoformat() + 'Z',
                row["recurrence_minutes"],
            ),
        )
        await db.commit()

        # Log audit for new recurring task
        await log_audit(
            db,
            "task",
            recurring_task_id,
            "created",
            f"user:{row['owner_user_id']}",
            detail={"reason": "recurring_task", "parent_task_id": id},
        )

    # Log audit for the update
    owner_user_id = row["owner_user_id"]
    await log_audit(
        db,
        "task",
        id,
        "updated",
        f"user:{owner_user_id}",
        detail=changed_fields if changed_fields else None,
    )

    # Fetch and return updated task
    cursor = await db.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    task_response = TaskResponse(
        id=row["id"],
        memory_id=row["memory_id"],
        owner_user_id=row["owner_user_id"],
        description=row["description"],
        state=row["state"],
        due_at=parse_db_datetime(row["due_at"]),
        recurrence_minutes=row["recurrence_minutes"],
        completed_at=parse_db_datetime(row["completed_at"]),
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )

    return TaskUpdateResponse(
        task=task_response,
        recurring_task_id=recurring_task_id,
    )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> None:
    """
    Delete a task by ID.

    - Fetch existing task; 404 if not found
    - Delete from tasks table
    - Call log_audit() to log the deletion
    - Return: 204 No Content
    """
    # Fetch existing task
    cursor = await db.execute(
        "SELECT * FROM tasks WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Task not found")

    owner_user_id = row["owner_user_id"]

    # Delete from database
    await db.execute("DELETE FROM tasks WHERE id = ?", (id,))
    await db.commit()

    # Log audit
    await log_audit(db, "task", id, "deleted", f"user:{owner_user_id}")
