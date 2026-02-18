"""Async background scheduler for housekeeping tasks."""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite

from core_svc.audit import log_audit
from core_svc.search import remove_from_index
from shared_lib.redis_streams import publish, STREAM_NOTIFY_TELEGRAM

logger = logging.getLogger(__name__)


async def _fire_due_reminders(db: aiosqlite.Connection, redis_client) -> None:
    """Fire reminders that are due and handle recurrence."""
    # Query for due reminders
    cursor = await db.execute(
        """
        SELECT r.*, m.content, m.owner_user_id
        FROM reminders r
        JOIN memories m ON r.memory_id = m.id
        WHERE r.fired = 0 AND r.fire_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """
    )
    due_reminders = await cursor.fetchall()

    for row in due_reminders:
        reminder = dict(row)
        reminder_id = reminder['id']
        memory_id = reminder['memory_id']
        owner_user_id = reminder['owner_user_id']
        content = reminder['content']
        fire_at = reminder['fire_at']
        recurrence_minutes = reminder['recurrence_minutes']

        # Publish notification to Redis
        notification = {
            "user_id": owner_user_id,
            "message_type": "reminder",
            "content": {
                "reminder_id": reminder_id,
                "memory_id": memory_id,
                "memory_content": content,
                "fire_at": fire_at
            }
        }
        await publish(redis_client, STREAM_NOTIFY_TELEGRAM, notification)

        # Mark as fired
        await db.execute(
            "UPDATE reminders SET fired = 1 WHERE id = ?",
            (reminder_id,)
        )

        # Handle recurrence
        if recurrence_minutes is not None:
            # Calculate next fire time
            old_fire_at = datetime.fromisoformat(fire_at.replace('Z', '+00:00'))
            next_fire_at = old_fire_at + timedelta(minutes=recurrence_minutes)
            next_fire_at_str = next_fire_at.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

            # Generate new ID for recurring reminder
            import uuid
            new_reminder_id = str(uuid.uuid4())

            # Create new reminder instance
            await db.execute(
                """
                INSERT INTO reminders (id, memory_id, owner_user_id, fire_at, recurrence_minutes, fired)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (new_reminder_id, memory_id, owner_user_id, next_fire_at_str, recurrence_minutes)
            )

            # Audit log for new recurring reminder
            await log_audit(
                db,
                "reminder",
                new_reminder_id,
                "created",
                "system:scheduler",
                {"source": "recurrence"}
            )

        # Audit log for fired reminder
        await log_audit(db, "reminder", reminder_id, "fired", "system:scheduler")

    await db.commit()


async def _expire_pending_images(db: aiosqlite.Connection) -> None:
    """Expire pending memories that have passed their expiration time."""
    # Query for expired pending memories
    cursor = await db.execute(
        """
        SELECT id, media_local_path
        FROM memories
        WHERE status = 'pending' AND pending_expires_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        """
    )
    expired_memories = await cursor.fetchall()

    for row in expired_memories:
        memory = dict(row)
        memory_id = memory['id']
        media_local_path = memory['media_local_path']

        # Defensive: remove from FTS5 index (should not be indexed, but just in case)
        await remove_from_index(db, memory_id)

        # Delete media file if it exists
        if media_local_path and os.path.exists(media_local_path):
            try:
                os.remove(media_local_path)
                logger.info(f"Deleted expired media file: {media_local_path}")
            except OSError as e:
                logger.error(f"Failed to delete media file {media_local_path}: {e}")

        # Delete memory from database (cascade deletes tags)
        await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))

        # Audit log
        await log_audit(db, "memory", memory_id, "expired", "system:scheduler")

    await db.commit()


async def _expire_suggested_tags(db: aiosqlite.Connection) -> None:
    """Delete suggested tags older than 7 days."""
    # Query for expired suggested tags
    cursor = await db.execute(
        """
        SELECT memory_id, tag
        FROM memory_tags
        WHERE status = 'suggested' AND suggested_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-7 days')
        """
    )
    expired_tags = await cursor.fetchall()

    for row in expired_tags:
        tag_data = dict(row)
        memory_id = tag_data['memory_id']
        tag = tag_data['tag']

        # Delete tag
        await db.execute(
            "DELETE FROM memory_tags WHERE memory_id = ? AND tag = ?",
            (memory_id, tag)
        )

        # Audit log
        await log_audit(
            db,
            "memory",
            memory_id,
            "expired",
            "system:scheduler",
            {"tag": tag, "reason": "suggested_tag_expiry"}
        )

    await db.commit()


async def _requeue_stale_events(db: aiosqlite.Connection, redis_client) -> None:
    """Re-queue events that have been pending for more than 24 hours."""
    # Query for stale pending events
    cursor = await db.execute(
        """
        SELECT e.*, u.telegram_user_id
        FROM events e
        JOIN users u ON e.owner_user_id = u.telegram_user_id
        WHERE e.status = 'pending' AND e.pending_since <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-24 hours')
        """
    )
    stale_events = await cursor.fetchall()

    for row in stale_events:
        event = dict(row)
        event_id = event['id']
        owner_user_id = event['owner_user_id']
        description = event['description']
        event_time = event['event_time']  # Note: renamed from event_date in migration 004

        # Publish re-prompt to Redis
        reprompt = {
            "user_id": owner_user_id,
            "message_type": "event_reprompt",
            "content": {
                "event_id": event_id,
                "description": description,
                "event_date": event_time  # Keep as "event_date" in message for compatibility
            }
        }
        await publish(redis_client, STREAM_NOTIFY_TELEGRAM, reprompt)

        # Update pending_since to current time
        await db.execute(
            "UPDATE events SET pending_since = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
            (event_id,)
        )

        # Audit log
        await log_audit(db, "event", event_id, "requeued", "system:scheduler")

    await db.commit()


async def run_scheduler(
    db: aiosqlite.Connection,
    redis_client,
    interval_seconds: int = 30
) -> None:
    """
    Run the scheduler loop, executing housekeeping tasks at regular intervals.

    This function runs forever (until cancelled) and performs four housekeeping actions:
    1. Fire due reminders
    2. Expire pending images
    3. Expire suggested tags
    4. Re-queue stale events

    Each action is isolated with its own error handling to prevent failures in one
    action from affecting others.

    Args:
        db: Database connection
        redis_client: Redis client for publishing notifications
        interval_seconds: Time to wait between scheduler ticks (default: 30)
    """
    logger.info(f"Scheduler started with {interval_seconds}s interval")

    while True:
        await asyncio.sleep(interval_seconds)

        # Action 1: Fire due reminders
        try:
            await _fire_due_reminders(db, redis_client)
        except Exception:
            logger.exception("Error firing reminders")

        # Action 2: Expire pending images
        try:
            await _expire_pending_images(db)
        except Exception:
            logger.exception("Error expiring pending images")

        # Action 3: Expire suggested tags
        try:
            await _expire_suggested_tags(db)
        except Exception:
            logger.exception("Error expiring suggested tags")

        # Action 4: Re-queue stale events
        try:
            await _requeue_stale_events(db, redis_client)
        except Exception:
            logger.exception("Error re-queuing stale events")
