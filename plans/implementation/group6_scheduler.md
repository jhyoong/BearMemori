# Group 6: Scheduler + Backup Stub

## Goal

Implement the async background scheduler that runs inside the Core service process, handling reminder firing, expiry cleanup, and event re-queuing. Stub out the S3 backup module.

**Depends on:** Group 5 (routers -- shares audit and FTS5 logic)
**Blocks:** Group 8 (tests)

---

## Context

The scheduler is an async background task started during Core's lifespan. It runs a loop every 30 seconds, performing four housekeeping actions. Each action is independent and wrapped in its own error handling so a failure in one does not block others.

The scheduler needs:
- The database connection (from `app.state.db`)
- The Redis client (from `app.state.redis`) for publishing notifications
- The audit logger (`core.audit.log_audit`)
- The FTS5 helper (`core.search.remove_from_index`) for cleaning up expired memories

---

## Steps

### Step 6.1: Implement scheduler

**File:** `core/core/scheduler.py`

**Main function:**

```python
async def run_scheduler(db: aiosqlite.Connection, redis_client, interval_seconds: int = 30) -> None:
```

This function runs forever (until cancelled). On each tick:

1. Sleep for `interval_seconds`
2. Run each action in its own try/except block, logging errors
3. Continue to next tick regardless of individual failures

**Action 1: Fire due reminders**

```sql
SELECT r.*, m.content, m.owner_user_id
FROM reminders r
JOIN memories m ON r.memory_id = m.id
WHERE r.fired = 0 AND r.fire_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
```

For each due reminder:
1. Publish to `notify:telegram` Redis stream:
   ```json
   {
     "user_id": <owner_user_id>,
     "message_type": "reminder",
     "content": {
       "reminder_id": "<id>",
       "memory_id": "<memory_id>",
       "memory_content": "<content>",
       "fire_at": "<fire_at>"
     }
   }
   ```
   Use `shared.redis_streams.publish()` helper.
2. Mark as fired: `UPDATE reminders SET fired = 1 WHERE id = ?`
3. If `recurrence_minutes` is not None:
   - Calculate next fire time: `old_fire_at + timedelta(minutes=recurrence_minutes)`
   - Create new reminder: `INSERT INTO reminders (id, memory_id, owner_user_id, fire_at, recurrence_minutes, fired) VALUES (?, ?, ?, ?, ?, 0)`
   - Audit log: `log_audit(db, "reminder", new_id, "created", "system:scheduler", {"source": "recurrence"})`
4. Audit log: `log_audit(db, "reminder", id, "fired", "system:scheduler")`

**Action 2: Expire pending images**

```sql
SELECT id, media_local_path
FROM memories
WHERE status = 'pending' AND pending_expires_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
```

For each expired memory:
1. Call `remove_from_index(db, memory_id)` (defensive -- pending memories should not be indexed, but just in case)
2. If `media_local_path` exists on disk: delete the file
3. Delete from DB: `DELETE FROM memories WHERE id = ?` (cascade deletes tags)
4. Audit log: `log_audit(db, "memory", id, "expired", "system:scheduler")`

**Action 3: Expire suggested tags**

```sql
SELECT memory_id, tag
FROM memory_tags
WHERE status = 'suggested' AND suggested_at <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-7 days')
```

For each expired tag:
1. Delete: `DELETE FROM memory_tags WHERE memory_id = ? AND tag = ?`
2. Audit log: `log_audit(db, "memory", memory_id, "expired", "system:scheduler", {"tag": tag, "reason": "suggested_tag_expiry"})`

**Action 4: Re-queue unanswered events**

```sql
SELECT e.*, u.telegram_user_id
FROM events e
JOIN users u ON e.owner_user_id = u.telegram_user_id
WHERE e.status = 'pending' AND e.pending_since <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-24 hours')
```

For each stale event:
1. Publish re-prompt to `notify:telegram` Redis stream:
   ```json
   {
     "user_id": <owner_user_id>,
     "message_type": "event_reprompt",
     "content": {
       "event_id": "<id>",
       "description": "<description>",
       "event_date": "<event_date>"
     }
   }
   ```
2. Update: `UPDATE events SET pending_since = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?`
3. Audit log: `log_audit(db, "event", id, "requeued", "system:scheduler")`

---

### Step 6.2: Stub backup module

**File:** `core/core/backup.py`

```python
import logging

logger = logging.getLogger(__name__)

async def run_backup(db_path: str, image_dir: str, s3_bucket: str, s3_region: str) -> None:
    """S3 backup is not configured in Phase 1. This is a stub."""
    logger.info("S3 backup not configured -- skipping")
```

No backup scheduler loop is needed in Phase 1. The `GET /backup/status` endpoint (in Group 5, Step 5.9) returns `"not_configured"`.

---

### Step 6.3: Integrate scheduler into main.py

Update `core/core/main.py` lifespan to start the scheduler:

```python
from core.scheduler import run_scheduler

@asynccontextmanager
async def lifespan(app):
    # ... (db and redis init) ...

    # Start scheduler
    app.state.scheduler_task = asyncio.create_task(
        run_scheduler(app.state.db, app.state.redis)
    )

    yield

    # Stop scheduler
    app.state.scheduler_task.cancel()
    try:
        await app.state.scheduler_task
    except asyncio.CancelledError:
        pass

    # ... (db and redis cleanup) ...
```

---

## Design Notes

### Error Isolation

Each action is wrapped in its own try/except:
```python
async def run_scheduler(db, redis_client, interval_seconds=30):
    while True:
        await asyncio.sleep(interval_seconds)

        try:
            await fire_due_reminders(db, redis_client)
        except Exception:
            logger.exception("Error firing reminders")

        try:
            await expire_pending_images(db)
        except Exception:
            logger.exception("Error expiring pending images")

        # ... etc
```

### Timestamp Comparisons

All timestamps in the database are stored as ISO 8601 strings. SQLite's `strftime` function generates comparable strings. The scheduler queries use SQLite's datetime functions for comparison, not Python datetime objects.

### Graceful Shutdown

The scheduler task is cancelled via `asyncio.CancelledError`. The `run_scheduler` loop should handle this cleanly -- if it's in the middle of `asyncio.sleep()`, cancellation is immediate. If it's in the middle of a DB operation, the operation completes before cancellation is checked (since `aiosqlite` operations are not directly cancellable).

---

## Acceptance Criteria

1. Scheduler starts as a background task when Core boots
2. A reminder with `fire_at` in the past is fired on the next tick (within 30 seconds)
3. Fired reminder has `fired = 1`
4. A recurring fired reminder generates a new reminder instance with correct `fire_at`
5. A message is published to `notify:telegram` Redis stream for fired reminders
6. An expired pending image (past `pending_expires_at`) is deleted from DB and disk
7. A suggested tag older than 7 days is deleted
8. A pending event older than 24 hours has `pending_since` reset and a re-prompt published
9. An error in one action does not prevent other actions from running
10. Scheduler shuts down cleanly when Core stops
11. All scheduler actions are audit logged
