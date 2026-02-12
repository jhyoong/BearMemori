# Group 5: REST API Routers

## Goal

Implement all Core service REST API routers. At the end of this group, the Core service exposes a complete CRUD API for memories, tasks, reminders, events, search, settings, audit, LLM jobs, and backup status.

**Depends on:** Group 4 (audit + FTS5 helpers)
**Blocks:** Group 6 (scheduler), Group 8 (tests)

---

## Context

All routers follow the same pattern:
- Each router is a `fastapi.APIRouter` defined in its own file under `core/core/routers/`
- Database connection is injected via `Depends(get_db)`
- All state changes call `log_audit()` from `core/core/audit.py`
- Memories router additionally calls FTS5 sync from `core/core/search.py`
- UUIDs are generated via `uuid.uuid4()` and stored as strings
- Timestamps use ISO 8601 UTC format
- Request/response models come from `shared.schemas`

---

## Steps

### Step 5.1: Memories router

**File:** `core/core/routers/memories.py`

This is the most complex router. It manages the core entity and integrates with FTS5 and file deletion.

#### `POST /memories`
- Accept: `MemoryCreate` body
- Generate UUID for `id`
- If `media_type == "image"`: set `status = "pending"`, set `pending_expires_at = now + 7 days`
- If `media_type is None` (text): set `status = "confirmed"`
- Insert into `memories` table
- If status is `confirmed`: call `index_memory(db, memory_id)` to sync FTS5
- Call `log_audit(db, "memory", id, "created", f"user:{owner_user_id}")`
- Return: `MemoryResponse`

#### `GET /memories/{id}`
- Fetch memory by ID from `memories` table
- If not found: return 404
- Fetch tags from `memory_tags WHERE memory_id = ?`
- Return: `MemoryWithTags`

#### `PATCH /memories/{id}`
- Accept: `MemoryUpdate` body (all fields optional)
- Fetch existing memory; 404 if not found
- Build UPDATE query for only the provided fields
- Always set `updated_at = now`
- If `status` changes to `confirmed`: call `index_memory()` to sync FTS5
- If `is_pinned` changes: no FTS5 re-index needed (pin boost is at query time)
- Call `log_audit(db, "memory", id, "updated", f"user:{owner_user_id}", detail={changed_fields})`
- Return: updated `MemoryResponse`

#### `DELETE /memories/{id}`
- Fetch existing memory; 404 if not found
- Call `remove_from_index(db, memory_id)` to remove from FTS5
- If `media_local_path` exists and file is on disk: delete the file (`os.remove`)
- Delete from `memories` (cascade will delete `memory_tags`)
- Call `log_audit(db, "memory", id, "deleted", f"user:{owner_user_id}")`
- Return: 204 No Content

#### `POST /memories/{id}/tags`
- Accept: `TagAdd` body (`tags: list[str]`, `status: str = "confirmed"`)
- Fetch memory; 404 if not found
- For each tag: `INSERT OR REPLACE INTO memory_tags (memory_id, tag, status, suggested_at, confirmed_at) VALUES (...)`
  - If status is `suggested`: set `suggested_at = now`
  - If status is `confirmed`: set `confirmed_at = now`
- If memory is confirmed: call `index_memory()` to re-sync FTS5 with new tags
- Call `log_audit(db, "memory", id, "updated", actor, {"tags_added": tags})`
- Return: updated `MemoryWithTags`

#### `DELETE /memories/{id}/tags/{tag}`
- Fetch memory; 404 if not found
- Delete from `memory_tags WHERE memory_id = ? AND tag = ?`
- If memory is confirmed: call `index_memory()` to re-sync FTS5
- Call `log_audit(db, "memory", id, "updated", actor, {"tag_removed": tag})`
- Return: 204 No Content

---

### Step 5.2: Tasks router

**File:** `core/core/routers/tasks.py`

#### `POST /tasks`
- Accept: `TaskCreate` body
- Generate UUID
- Insert into `tasks` table
- Call `log_audit(db, "task", id, "created", f"user:{owner_user_id}")`
- Return: `TaskResponse`

#### `GET /tasks`
- Query params: `state` (optional), `owner_user_id` (optional), `due_before` (optional datetime), `due_after` (optional datetime), `limit` (default 50), `offset` (default 0)
- Build query with optional WHERE clauses based on provided filters
- Return: `list[TaskResponse]`

#### `PATCH /tasks/{id}`
- Accept: `TaskUpdate` body
- Fetch existing task; 404 if not found
- If `state` changes to `DONE`:
  - Set `completed_at = now`
  - If `recurrence_minutes` is set on the task:
    - Calculate new `due_at`:
      - If old `due_at` exists: `new_due_at = old_due_at + timedelta(minutes=recurrence_minutes)`
      - If old `due_at` is None: `new_due_at = now + timedelta(minutes=recurrence_minutes)`
    - Create new task: same `memory_id`, `owner_user_id`, `description`, `recurrence_minutes`, new UUID, `state = NOT_DONE`, `due_at = new_due_at`
    - Call `log_audit()` for the new task
- Call `log_audit(db, "task", id, "updated", f"user:{owner_user_id}", {changed_fields})`
- Return: `TaskResponse` (the updated original task). If a recurring task was created, include its ID in the response or return it as a separate field.

#### `DELETE /tasks/{id}`
- Fetch existing task; 404 if not found
- Delete from `tasks`
- Call `log_audit(db, "task", id, "deleted", f"user:{owner_user_id}")`
- Return: 204 No Content

---

### Step 5.3: Reminders router

**File:** `core/core/routers/reminders.py`

#### `POST /reminders`
- Accept: `ReminderCreate` body
- Generate UUID
- Insert into `reminders` table
- Call `log_audit(db, "reminder", id, "created", f"user:{owner_user_id}")`
- Return: `ReminderResponse`

#### `GET /reminders`
- Query params: `owner_user_id` (optional), `fired` (optional bool), `upcoming_only` (optional bool -- where `fire_at > now AND fired = 0`), `limit` (default 50), `offset` (default 0)
- Default sort: `ORDER BY fire_at ASC`
- Return: `list[ReminderResponse]`

#### `PATCH /reminders/{id}`
- Accept: `ReminderUpdate` body
- Fetch existing; 404 if not found
- Update provided fields
- Call `log_audit(db, "reminder", id, "updated", f"user:{owner_user_id}")`
- Return: `ReminderResponse`

#### `DELETE /reminders/{id}`
- Fetch existing; 404 if not found
- Delete from `reminders`
- Call `log_audit(db, "reminder", id, "deleted", f"user:{owner_user_id}")`
- Return: 204 No Content

---

### Step 5.4: Events router

**File:** `core/core/routers/events.py`

#### `POST /events`
- Accept: `EventCreate` body
- Generate UUID
- Set `pending_since = now`, `status = "pending"`
- Insert into `events` table
- Call `log_audit(db, "event", id, "created", f"user:{owner_user_id}")`
- Return: `EventResponse`

#### `PATCH /events/{id}`
- Accept: `EventUpdate` body
- Fetch existing; 404 if not found
- If `status` changes to `confirmed`:
  - Auto-create a reminder linked to this event's memory (if any) or the event itself:
    - `fire_at = event.event_date`
    - `owner_user_id = event.owner_user_id`
    - `memory_id = event.memory_id` (may be None for email-sourced events without a memory)
  - If `memory_id` is None, skip reminder creation (or create a memory first -- follow the simpler path: skip if no memory)
  - Store `reminder_id` on the event
  - Call `log_audit(db, "event", id, "confirmed", f"user:{owner_user_id}")`
- If `status` changes to `rejected`:
  - Call `log_audit(db, "event", id, "rejected", f"user:{owner_user_id}")`
- Return: `EventResponse`

#### `GET /events`
- Query params: `status` (optional), `owner_user_id` (optional), `limit` (default 50), `offset` (default 0)
- Return: `list[EventResponse]`

---

### Step 5.5: Search router

**File:** `core/core/routers/search.py`

#### `GET /search`
- Query params: `q` (required, search query string), `owner` (required, user_id), `pinned` (optional bool, default false)
- Call `search_memories()` from `core/core/search.py`
- Return: `list[SearchResult]` (each containing `MemoryWithTags` + `score`)
- If `q` is empty or only whitespace: return 400

---

### Step 5.6: Settings router

**File:** `core/core/routers/settings.py`

#### `GET /settings/{user_id}`
- Fetch from `user_settings WHERE telegram_user_id = ?`
- If not found: return defaults (`default_reminder_time = "09:00"`, `timezone = "Asia/Singapore"`)
- Upsert pattern: if user does not exist in `users` table, create them with `display_name = "User {user_id}"`, `is_allowed = 0`
- Return: `UserSettingsResponse`

#### `PATCH /settings/{user_id}`
- Accept: `UserSettingsUpdate` body
- Upsert into `user_settings`: INSERT OR REPLACE with provided + existing values
- If user does not exist in `users`, create them first
- Return: `UserSettingsResponse`

---

### Step 5.7: Audit router

**File:** `core/core/routers/audit.py`

#### `GET /audit`
- Query params: `entity_type` (optional), `entity_id` (optional), `action` (optional), `actor` (optional), `limit` (default 50), `offset` (default 0)
- Build query with optional WHERE clauses
- Order by `created_at DESC`
- Parse `detail` from JSON string to dict for each entry
- Return: `list[AuditLogEntry]`

---

### Step 5.8: LLM Jobs router

**File:** `core/core/routers/llm_jobs.py`

#### `POST /llm-jobs`
- Accept: `LLMJobCreate` body
- Generate UUID
- Serialize `payload` to JSON string
- Insert into `llm_jobs` table
- Call `log_audit(db, "llm_job", id, "created", "system")`
- Return: `LLMJobResponse`

#### `GET /llm-jobs/{id}`
- Fetch by ID; 404 if not found
- Parse `payload` and `result` from JSON strings to dicts
- Return: `LLMJobResponse`

#### `PATCH /llm-jobs/{id}`
- Accept: `LLMJobUpdate` body
- Fetch existing; 404 if not found
- Update provided fields. Set `updated_at = now`
- If `result` provided, serialize to JSON string
- Call `log_audit(db, "llm_job", id, "updated", "system", {changed_fields})`
- Return: `LLMJobResponse`

---

### Step 5.9: Backup status endpoint

**File:** `core/core/routers/backup.py`

#### `GET /backup/status`
- Query: `SELECT value FROM backup_metadata WHERE key = 'last_backup_at'`
- If found: return `BackupStatus(last_backup_at=value, status="ok")`
- If not found: return `BackupStatus(last_backup_at=None, status="not_configured")`

---

## Router Registration

After all routers are created, update `core/core/main.py` to include them:

```python
from core.routers import memories, tasks, reminders, events, search, settings, audit, llm_jobs, backup

app.include_router(memories.router, prefix="/memories", tags=["memories"])
app.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
app.include_router(reminders.router, prefix="/reminders", tags=["reminders"])
app.include_router(events.router, prefix="/events", tags=["events"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(settings.router, prefix="/settings", tags=["settings"])
app.include_router(audit.router, prefix="/audit", tags=["audit"])
app.include_router(llm_jobs.router, prefix="/llm-jobs", tags=["llm-jobs"])
app.include_router(backup.router, prefix="/backup", tags=["backup"])
```

---

## Acceptance Criteria

1. `POST /memories` with text content creates a confirmed memory
2. `POST /memories` with `media_type=image` creates a pending memory with `pending_expires_at` set to 7 days from now
3. `GET /memories/{id}` returns the memory with its tags
4. `PATCH /memories/{id}` updates fields and logs audit
5. `DELETE /memories/{id}` removes DB record, FTS5 entry, and local image file
6. Tag add/remove works and re-syncs FTS5
7. `POST /tasks` creates a task linked to a memory
8. Marking a recurring task as DONE auto-creates the next instance with correct due_at
9. `POST /reminders` creates a reminder
10. Confirming an event auto-creates a linked reminder
11. `GET /search?q=keyword&owner=123` returns matching confirmed memories with pin boost
12. Settings GET returns defaults for new users
13. Audit log endpoint returns entries with filters
14. LLM jobs CRUD works correctly
15. All endpoints return appropriate error codes (404, 400, etc.)
