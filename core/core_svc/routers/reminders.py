"""Reminders router."""

import logging
import uuid
from datetime import datetime

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from core_svc.audit import log_audit
from core_svc.database import get_db
from core_svc.utils import parse_db_datetime
from shared_lib.schemas import ReminderCreate, ReminderResponse, ReminderUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reminders"])


@router.post("", response_model=ReminderResponse, status_code=status.HTTP_201_CREATED)
async def create_reminder(
    reminder: ReminderCreate,
    db: aiosqlite.Connection = Depends(get_db),
) -> ReminderResponse:
    """
    Create a new reminder.

    - Generate UUID
    - Insert into reminders table
    - Call log_audit() to log the creation
    - Return: ReminderResponse
    """
    # Generate UUID for id
    reminder_id = str(uuid.uuid4())

    # Convert fire_at to ISO format
    fire_at_str = reminder.fire_at.isoformat()
    if not fire_at_str.endswith('Z') and '+' not in fire_at_str and reminder.fire_at.tzinfo is None:
        fire_at_str += 'Z'

    # Insert into reminders table
    await db.execute(
        """
        INSERT INTO reminders (
            id, memory_id, owner_user_id, text, fire_at, recurrence_minutes
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            reminder_id,
            reminder.memory_id,
            reminder.owner_user_id,
            reminder.text,
            fire_at_str,
            reminder.recurrence_minutes,
        ),
    )
    await db.commit()

    # Log audit
    await log_audit(db, "reminder", reminder_id, "created", f"user:{reminder.owner_user_id}")

    # Fetch and return the created reminder
    cursor = await db.execute(
        "SELECT * FROM reminders WHERE id = ?",
        (reminder_id,),
    )
    row = await cursor.fetchone()

    return ReminderResponse(
        id=row["id"],
        memory_id=row["memory_id"],
        owner_user_id=row["owner_user_id"],
        text=row["text"],
        fire_at=parse_db_datetime(row["fire_at"]),
        recurrence_minutes=row["recurrence_minutes"],
        fired=bool(row["fired"]),
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )


@router.get("", response_model=list[ReminderResponse])
async def get_reminders(
    owner_user_id: int | None = None,
    fired: bool | None = None,
    upcoming_only: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[ReminderResponse]:
    """
    Get reminders with optional filters.

    Query params:
    - owner_user_id (optional): Filter by owner
    - fired (optional bool): Filter by fired status
    - upcoming_only (optional bool): Filter for unfired reminders with fire_at > now
    - limit (default 50): Maximum number of results
    - offset (default 0): Number of results to skip

    Default sort: ORDER BY fire_at ASC
    Return: list[ReminderResponse]
    """
    # Build WHERE clauses
    where_clauses = []
    query_params = []

    if owner_user_id is not None:
        where_clauses.append("owner_user_id = ?")
        query_params.append(owner_user_id)

    if fired is not None:
        where_clauses.append("fired = ?")
        query_params.append(1 if fired else 0)

    if upcoming_only:
        # upcoming_only means fire_at > now AND fired = 0
        now_str = datetime.utcnow().isoformat() + 'Z'
        where_clauses.append("fire_at > ?")
        query_params.append(now_str)
        where_clauses.append("fired = 0")

    # Build query
    query = "SELECT * FROM reminders"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY fire_at ASC LIMIT ? OFFSET ?"
    query_params.extend([limit, offset])

    # Execute query
    cursor = await db.execute(query, query_params)
    rows = await cursor.fetchall()

    # Convert to ReminderResponse objects
    reminders = [
        ReminderResponse(
            id=row["id"],
            memory_id=row["memory_id"],
            owner_user_id=row["owner_user_id"],
            text=row["text"],
            fire_at=parse_db_datetime(row["fire_at"]),
            recurrence_minutes=row["recurrence_minutes"],
            fired=bool(row["fired"]),
            created_at=parse_db_datetime(row["created_at"]),
            updated_at=parse_db_datetime(row["updated_at"]),
        )
        for row in rows
    ]

    return reminders


@router.patch("/{id}", response_model=ReminderResponse)
async def update_reminder(
    id: str,
    reminder_update: ReminderUpdate,
    db: aiosqlite.Connection = Depends(get_db),
) -> ReminderResponse:
    """
    Update a reminder by ID.

    - Fetch existing reminder; 404 if not found
    - Build UPDATE query for only the provided fields
    - Always set updated_at = now
    - Call log_audit() to log the update
    - Return: ReminderResponse
    """
    # Fetch existing reminder
    cursor = await db.execute(
        "SELECT * FROM reminders WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Reminder not found")

    # Build UPDATE query for provided fields
    update_fields = []
    update_values = []
    changed_fields = {}

    if reminder_update.text is not None:
        update_fields.append("text = ?")
        update_values.append(reminder_update.text)
        changed_fields["text"] = reminder_update.text

    if reminder_update.fire_at is not None:
        fire_at_str = reminder_update.fire_at.isoformat()
        if not fire_at_str.endswith('Z') and '+' not in fire_at_str and reminder_update.fire_at.tzinfo is None:
            fire_at_str += 'Z'
        update_fields.append("fire_at = ?")
        update_values.append(fire_at_str)
        changed_fields["fire_at"] = fire_at_str

    if reminder_update.recurrence_minutes is not None:
        update_fields.append("recurrence_minutes = ?")
        update_values.append(reminder_update.recurrence_minutes)
        changed_fields["recurrence_minutes"] = reminder_update.recurrence_minutes

    # Always set updated_at
    update_fields.append("updated_at = ?")
    updated_at = datetime.utcnow().isoformat() + 'Z'
    update_values.append(updated_at)

    # Add id to values for WHERE clause
    update_values.append(id)

    # Execute update
    if update_fields:
        sql = f"UPDATE reminders SET {', '.join(update_fields)} WHERE id = ?"
        await db.execute(sql, update_values)
        await db.commit()

    # Log audit for the update
    owner_user_id = row["owner_user_id"]
    await log_audit(
        db,
        "reminder",
        id,
        "updated",
        f"user:{owner_user_id}",
        detail=changed_fields if changed_fields else None,
    )

    # Fetch and return updated reminder
    cursor = await db.execute(
        "SELECT * FROM reminders WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    return ReminderResponse(
        id=row["id"],
        memory_id=row["memory_id"],
        owner_user_id=row["owner_user_id"],
        text=row["text"],
        fire_at=parse_db_datetime(row["fire_at"]),
        recurrence_minutes=row["recurrence_minutes"],
        fired=bool(row["fired"]),
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reminder(
    id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> None:
    """
    Delete a reminder by ID.

    - Fetch existing reminder; 404 if not found
    - Delete from reminders table
    - Call log_audit() to log the deletion
    - Return: 204 No Content
    """
    # Fetch existing reminder
    cursor = await db.execute(
        "SELECT * FROM reminders WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Reminder not found")

    owner_user_id = row["owner_user_id"]

    # Delete from database
    await db.execute("DELETE FROM reminders WHERE id = ?", (id,))
    await db.commit()

    # Log audit
    await log_audit(db, "reminder", id, "deleted", f"user:{owner_user_id}")
