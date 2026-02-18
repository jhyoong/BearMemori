"""Tests for the background scheduler functions."""

import asyncio
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from core.scheduler import (
    _expire_pending_images,
    _expire_suggested_tags,
    _fire_due_reminders,
    _requeue_stale_events,
    run_scheduler,
)
from shared.redis_streams import STREAM_NOTIFY_TELEGRAM


def _ts_past(hours: int = 0, days: int = 0) -> str:
    """Return an ISO timestamp string representing time in the past."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours, days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _ts_future(hours: int = 0, days: int = 0) -> str:
    """Return an ISO timestamp string representing time in the future."""
    dt = datetime.now(timezone.utc) + timedelta(hours=hours, days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


async def _insert_memory(
    db,
    user_id: int,
    memory_id: str,
    status: str = "confirmed",
    pending_expires_at: str | None = None,
) -> None:
    await db.execute(
        """
        INSERT INTO memories (id, owner_user_id, content, status, pending_expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (memory_id, user_id, "test content", status, pending_expires_at),
    )
    await db.commit()


async def _insert_reminder(
    db,
    reminder_id: str,
    memory_id: str,
    user_id: int,
    fire_at: str,
    recurrence_minutes: int | None = None,
    fired: int = 0,
) -> None:
    await db.execute(
        """
        INSERT INTO reminders
            (id, memory_id, owner_user_id, text, fire_at, recurrence_minutes, fired)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (reminder_id, memory_id, user_id, "test reminder", fire_at, recurrence_minutes, fired),
    )
    await db.commit()


async def test_fire_due_reminder(test_db, mock_redis, test_user):
    """Scheduler fires a due reminder: fired=1 in DB, message published to notify:telegram."""
    memory_id = str(uuid.uuid4())
    reminder_id = str(uuid.uuid4())

    await _insert_memory(test_db, test_user, memory_id)
    await _insert_reminder(test_db, reminder_id, memory_id, test_user, _ts_past(hours=1))

    await _fire_due_reminders(test_db, mock_redis)

    async with test_db.execute(
        "SELECT fired FROM reminders WHERE id = ?", (reminder_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row["fired"] == 1

    stream_len = await mock_redis.xlen(STREAM_NOTIFY_TELEGRAM)
    assert stream_len >= 1


async def test_fire_recurring_reminder(test_db, mock_redis, test_user):
    """Recurring reminder: original fired=1, new reminder created with fire_at = old + recurrence."""
    memory_id = str(uuid.uuid4())
    reminder_id = str(uuid.uuid4())
    recurrence_minutes = 60

    await _insert_memory(test_db, test_user, memory_id)
    await _insert_reminder(
        test_db,
        reminder_id,
        memory_id,
        test_user,
        _ts_past(hours=1),
        recurrence_minutes=recurrence_minutes,
    )

    await _fire_due_reminders(test_db, mock_redis)

    async with test_db.execute(
        "SELECT fired FROM reminders WHERE id = ?", (reminder_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row["fired"] == 1

    async with test_db.execute(
        "SELECT * FROM reminders WHERE memory_id = ? AND id != ? AND fired = 0",
        (memory_id, reminder_id),
    ) as cur:
        new_row = await cur.fetchone()
    assert new_row is not None
    assert new_row["recurrence_minutes"] == recurrence_minutes


async def test_expire_pending_image(test_db, mock_redis, test_user):
    """Expired pending memory is deleted from DB; audit log has an 'expired' entry."""
    memory_id = str(uuid.uuid4())
    await _insert_memory(
        test_db,
        test_user,
        memory_id,
        status="pending",
        pending_expires_at=_ts_past(hours=1),
    )

    await _expire_pending_images(test_db)

    async with test_db.execute(
        "SELECT id FROM memories WHERE id = ?", (memory_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row is None

    async with test_db.execute(
        "SELECT action FROM audit_log WHERE entity_type = 'memory' AND entity_id = ?",
        (memory_id,),
    ) as cur:
        audit_row = await cur.fetchone()
    assert audit_row is not None
    assert audit_row["action"] == "expired"


async def test_expire_suggested_tags(test_db, mock_redis, test_user):
    """Suggested tag older than 7 days is deleted; audit log has an 'expired' entry."""
    memory_id = str(uuid.uuid4())
    tag_name = "stale-tag"
    old_suggested_at = _ts_past(days=8)

    await _insert_memory(test_db, test_user, memory_id)
    await test_db.execute(
        """
        INSERT INTO memory_tags (memory_id, tag, status, suggested_at)
        VALUES (?, ?, 'suggested', ?)
        """,
        (memory_id, tag_name, old_suggested_at),
    )
    await test_db.commit()

    await _expire_suggested_tags(test_db)

    async with test_db.execute(
        "SELECT tag FROM memory_tags WHERE memory_id = ? AND tag = ?",
        (memory_id, tag_name),
    ) as cur:
        row = await cur.fetchone()
    assert row is None

    async with test_db.execute(
        "SELECT action FROM audit_log WHERE entity_type = 'memory' AND entity_id = ? AND action = 'expired'",
        (memory_id,),
    ) as cur:
        audit_row = await cur.fetchone()
    assert audit_row is not None


async def test_requeue_stale_event(test_db, mock_redis, test_user):
    """Stale pending event: pending_since updated, message published, audit logged."""
    event_id = str(uuid.uuid4())
    old_pending_since = _ts_past(hours=25)

    await test_db.execute(
        """
        INSERT INTO events
            (id, owner_user_id, event_time, description, source_type, status, pending_since)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """,
        (event_id, test_user, _ts_future(days=1), "quarterly review", "manual", old_pending_since),
    )
    await test_db.commit()

    await _requeue_stale_events(test_db, mock_redis)

    async with test_db.execute(
        "SELECT pending_since FROM events WHERE id = ?", (event_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row["pending_since"] != old_pending_since

    stream_len = await mock_redis.xlen(STREAM_NOTIFY_TELEGRAM)
    assert stream_len >= 1

    async with test_db.execute(
        """
        SELECT action FROM audit_log
        WHERE entity_type = 'event' AND entity_id = ? AND action = 'requeued'
        """,
        (event_id,),
    ) as cur:
        audit_row = await cur.fetchone()
    assert audit_row is not None


async def test_scheduler_error_isolation(test_db, mock_redis):
    """Exception in one scheduler action does not prevent the others from running."""
    called = []

    async def fire_fails(db, redis):
        raise RuntimeError("simulated failure")

    async def expire_ok(db):
        called.append("expire_images")

    async def tags_ok(db):
        called.append("expire_tags")

    async def requeue_ok(db, redis):
        called.append("requeue")

    with (
        patch("core.scheduler._fire_due_reminders", new=fire_fails),
        patch("core.scheduler._expire_pending_images", new=expire_ok),
        patch("core.scheduler._expire_suggested_tags", new=tags_ok),
        patch("core.scheduler._requeue_stale_events", new=requeue_ok),
    ):
        task = asyncio.create_task(run_scheduler(test_db, mock_redis, interval_seconds=0))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert "expire_images" in called
    assert "expire_tags" in called
    assert "requeue" in called
