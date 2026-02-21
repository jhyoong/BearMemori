"""Events router with auto-reminder creation."""

import logging
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, status

from core_svc.audit import log_audit
from core_svc.database import get_db
from core_svc.utils import parse_db_datetime
from shared_lib.schemas import EventCreate, EventResponse, EventUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["events"])


@router.post("", response_model=EventResponse, status_code=status.HTTP_201_CREATED)
async def create_event(
    event: EventCreate,
    db: aiosqlite.Connection = Depends(get_db),
) -> EventResponse:
    """
    Create a new event.

    - Generate UUID
    - Set pending_since = now, status = "pending"
    - Insert into events table
    - Call log_audit() to log the creation
    - Return: EventResponse
    """
    # Generate UUID for id
    event_id = str(uuid.uuid4())

    # Set pending_since to now and status to pending
    pending_since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Convert event_time to ISO format
    event_time_str = event.event_time.isoformat()
    if not event_time_str.endswith('Z') and '+' not in event_time_str and event.event_time.tzinfo is None:
        event_time_str += 'Z'

    # Insert into events table
    await db.execute(
        """
        INSERT INTO events (
            id, memory_id, owner_user_id, event_time, description,
            status, source_type, source_detail, pending_since
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            event.memory_id,
            event.owner_user_id,
            event_time_str,
            event.description,
            "pending",
            event.source_type,
            event.source_detail,
            pending_since,
        ),
    )
    await db.commit()

    # Log audit
    await log_audit(db, "event", event_id, "created", f"user:{event.owner_user_id}")

    # Fetch and return the created event
    cursor = await db.execute(
        "SELECT * FROM events WHERE id = ?",
        (event_id,),
    )
    row = await cursor.fetchone()

    return EventResponse(
        id=row["id"],
        memory_id=row["memory_id"],
        owner_user_id=row["owner_user_id"],
        event_time=parse_db_datetime(row["event_time"]),
        description=row["description"],
        status=row["status"],
        source_type=row["source_type"],
        source_detail=row["source_detail"],
        reminder_id=row["reminder_id"],
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )


@router.patch("/{id}", response_model=EventResponse)
async def update_event(
    id: str,
    event_update: EventUpdate,
    db: aiosqlite.Connection = Depends(get_db),
) -> EventResponse:
    """
    Update an event by ID.

    - Fetch existing event; 404 if not found
    - Build UPDATE query for only the provided fields
    - If status changes to "confirmed":
      - Auto-create a reminder linked to this event's memory (if memory_id is not None)
      - Set fire_at = event.event_time
      - Set owner_user_id = event.owner_user_id
      - Set memory_id = event.memory_id
      - Set text = event.description
      - Store reminder_id on the event
      - Set confirmed_at = now
      - Call log_audit() for both event and reminder
    - If status changes to "rejected":
      - Call log_audit() with action "rejected"
    - Always set updated_at = now
    - Return: EventResponse
    """
    # Fetch existing event
    cursor = await db.execute(
        "SELECT * FROM events WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")

    # Build UPDATE query for provided fields
    update_fields = []
    update_values = []
    changed_fields = {}

    if event_update.event_time is not None:
        event_time_str = event_update.event_time.isoformat()
        if not event_time_str.endswith('Z') and '+' not in event_time_str and event_update.event_time.tzinfo is None:
            event_time_str += 'Z'
        update_fields.append("event_time = ?")
        update_values.append(event_time_str)
        changed_fields["event_time"] = event_time_str

    if event_update.description is not None:
        update_fields.append("description = ?")
        update_values.append(event_update.description)
        changed_fields["description"] = event_update.description

    # Handle status changes with special logic
    reminder_id = None
    if event_update.status is not None:
        old_status = row["status"]
        new_status = event_update.status

        update_fields.append("status = ?")
        update_values.append(new_status)
        changed_fields["status"] = new_status

        # If status changes to "confirmed"
        if new_status == "confirmed" and old_status != "confirmed":
            confirmed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            update_fields.append("confirmed_at = ?")
            update_values.append(confirmed_at)

            # Auto-create reminder if memory_id is not None
            memory_id = row["memory_id"]
            if memory_id is not None:
                # Generate UUID for reminder
                reminder_id = str(uuid.uuid4())

                # Use updated event_time if provided, otherwise use existing
                event_time_for_reminder = event_time_str if event_update.event_time is not None else row["event_time"]

                # Use updated description if provided, otherwise use existing
                description_for_reminder = event_update.description if event_update.description is not None else row["description"]

                # Insert reminder
                await db.execute(
                    """
                    INSERT INTO reminders (
                        id, memory_id, owner_user_id, text, fire_at, recurrence_minutes
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reminder_id,
                        memory_id,
                        row["owner_user_id"],
                        description_for_reminder,
                        event_time_for_reminder,
                        None,  # One-time reminder
                    ),
                )

                # Log audit for reminder creation
                await log_audit(db, "reminder", reminder_id, "created", f"user:{row['owner_user_id']}")

                # Store reminder_id on the event
                update_fields.append("reminder_id = ?")
                update_values.append(reminder_id)
                changed_fields["reminder_id"] = reminder_id
            else:
                logger.info(f"Skipping reminder creation for event {id}: memory_id is None")

            # Log audit for confirmation
            await log_audit(db, "event", id, "confirmed", f"user:{row['owner_user_id']}")

        # If status changes to "rejected"
        elif new_status == "rejected" and old_status != "rejected":
            # Log audit for rejection
            await log_audit(db, "event", id, "rejected", f"user:{row['owner_user_id']}")

    # Always set updated_at
    update_fields.append("updated_at = ?")
    updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    update_values.append(updated_at)

    # Add id to values for WHERE clause
    update_values.append(id)

    # Execute update
    if update_fields:
        sql = f"UPDATE events SET {', '.join(update_fields)} WHERE id = ?"
        await db.execute(sql, update_values)
        await db.commit()

    # Fetch and return updated event
    cursor = await db.execute(
        "SELECT * FROM events WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    return EventResponse(
        id=row["id"],
        memory_id=row["memory_id"],
        owner_user_id=row["owner_user_id"],
        event_time=parse_db_datetime(row["event_time"]),
        description=row["description"],
        status=row["status"],
        source_type=row["source_type"],
        source_detail=row["source_detail"],
        reminder_id=row["reminder_id"],
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event(
    id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> None:
    """Delete an event by ID. Returns 404 if not found."""
    cursor = await db.execute("SELECT owner_user_id FROM events WHERE id = ?", (id,))
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")

    await db.execute("DELETE FROM events WHERE id = ?", (id,))
    await db.commit()

    await log_audit(db, "event", id, "deleted", f"user:{row['owner_user_id']}")


@router.get("", response_model=list[EventResponse])
async def get_events(
    status: str | None = None,
    owner_user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[EventResponse]:
    """
    Get events with optional filters.

    Query params:
    - status (optional): Filter by status
    - owner_user_id (optional): Filter by owner
    - limit (default 50): Maximum number of results
    - offset (default 0): Number of results to skip

    Default sort: ORDER BY event_time DESC
    Return: list[EventResponse]
    """
    # Build WHERE clauses
    where_clauses = []
    query_params = []

    if status is not None:
        where_clauses.append("status = ?")
        query_params.append(status)

    if owner_user_id is not None:
        where_clauses.append("owner_user_id = ?")
        query_params.append(owner_user_id)

    # Build query
    query = "SELECT * FROM events"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY event_time DESC LIMIT ? OFFSET ?"
    query_params.extend([limit, offset])

    # Execute query
    cursor = await db.execute(query, query_params)
    rows = await cursor.fetchall()

    # Convert to EventResponse objects
    events = [
        EventResponse(
            id=row["id"],
            memory_id=row["memory_id"],
            owner_user_id=row["owner_user_id"],
            event_time=parse_db_datetime(row["event_time"]),
            description=row["description"],
            status=row["status"],
            source_type=row["source_type"],
            source_detail=row["source_detail"],
            reminder_id=row["reminder_id"],
            created_at=parse_db_datetime(row["created_at"]),
            updated_at=parse_db_datetime(row["updated_at"]),
        )
        for row in rows
    ]

    return events
