# Core Service

The central REST API for BearMemori. All other services communicate with it via HTTP or Redis streams. It manages the SQLite database, handles CRUD operations for all domain entities, and triggers async LLM processing jobs.

## Running

```bash
# Locally (from core/ directory)
cd core && hatch run uvicorn core_svc.main:app --host 0.0.0.0 --port 8000

# Via Docker
docker-compose up --build
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CORE_HOST` | `0.0.0.0` | Bind address |
| `CORE_PORT` | `8000` | Bind port |
| `DATABASE_PATH` | — | Path to SQLite database file |
| `REDIS_URL` | `redis://redis:6379` | Redis connection string |
| `IMAGE_STORAGE_PATH` | — | Directory for uploaded images |

## Directory Structure

```
core/
├── pyproject.toml
├── Dockerfile
├── core_svc/
│   ├── main.py             # FastAPI app entry point
│   ├── database.py         # DB init, migrations, connection management
│   ├── audit.py            # Audit logging helper
│   ├── utils.py            # Shared utilities
│   ├── search.py           # FTS5 full-text search
│   ├── backup.py           # S3 backup (stub)
│   ├── scheduler.py        # Background housekeeping tasks
│   └── routers/
│       ├── memories.py     # Memory CRUD + tags + image upload
│       ├── tasks.py        # Task CRUD with recurrence
│       ├── reminders.py    # Reminder CRUD
│       ├── events.py       # Event CRUD with auto-reminder on confirm
│       ├── search.py       # FTS5 search endpoint
│       ├── settings.py     # User settings
│       ├── users.py        # User upsert
│       ├── llm_jobs.py     # LLM job management + Redis publish
│       ├── audit.py        # Audit log read-only
│       └── backup.py       # Backup status read-only
└── migrations/
    ├── 001_initial_schema.sql
    ├── 002_add_tasks_updated_at.sql
    ├── 003_add_reminder_fields.sql
    ├── 004_update_events_schema.sql
    ├── 005_update_user_settings_schema.sql
    ├── 006_update_llm_jobs_schema.sql
    ├── 007_create_backup_jobs.sql
    └── 008_add_fts_meta_cache.sql
```

## API Endpoints

### Health
- `GET /health` -- Returns `{"status": "ok"}`

### Users (`/users`)
- `POST /` -- Upsert user (first Telegram contact)

### Memories (`/memories`)
- `POST /` -- Create memory (text or image). Images start as `pending` with 7-day expiry.
- `GET /{id}` -- Fetch memory with tags
- `PATCH /{id}` -- Update memory fields (content, status, is_pinned)
- `DELETE /{id}` -- Delete memory (cascades to tags, FTS index, file)
- `POST /{id}/tags` -- Add tags (confirmed or suggested)
- `DELETE /{id}/tags/{tag}` -- Remove a tag
- `POST /{id}/image` -- Upload image file (multipart)

### Tasks (`/tasks`)
- `POST /` -- Create task (optionally linked to memory, with recurrence)
- `GET /` -- List tasks (filter by state, owner, due date range)
- `PATCH /{id}` -- Update task. Marking as DONE with recurrence auto-creates the next instance.
- `DELETE /{id}` -- Delete task

### Reminders (`/reminders`)
- `POST /` -- Create reminder (with optional recurrence)
- `GET /` -- List reminders (filter by fired status, upcoming only)
- `PATCH /{id}` -- Update reminder
- `DELETE /{id}` -- Delete reminder

### Events (`/events`)
- `POST /` -- Create event (starts as `pending`)
- `GET /` -- List events (filter by status, owner)
- `PATCH /{id}` -- Update event. Confirming auto-creates a linked reminder.
- `DELETE /{id}` -- Delete event

### Search (`/search`)
- `GET /?q=...&owner=...` -- FTS5 search across memories. Supports `pinned=true` filter.

### Settings (`/settings`)
- `GET /{user_id}` -- Get user settings (timezone, language)
- `PUT /{user_id}` -- Upsert user settings

### LLM Jobs (`/llm_jobs`)
- `POST /` -- Create job and publish to Redis stream
- `GET /{id}` -- Fetch job
- `GET /` -- List jobs (filter by status, type, user)
- `PATCH /{id}` -- Update job status/result

### Audit (`/audit`)
- `GET /` -- Fetch audit entries (filter by entity, action, actor)

### Backup (`/backup`)
- `GET /status/{user_id}` -- Most recent backup status

## Database

SQLite with WAL mode, foreign keys enabled, and FTS5 for full-text search. Migrations are numbered SQL files in `core/migrations/` and applied automatically on startup.

**Adding a migration:**
1. Create `core/migrations/NNN_description.sql` (increment from highest)
2. Update `SCHEMA_VERSION` in `core/core_svc/database.py`
3. Ensure idempotency (running twice must not fail)

## Background Scheduler

Runs every 30 seconds and handles:
1. Firing due reminders (publishes to `notify:telegram`, handles recurrence)
2. Expiring pending memories past their 7-day window
3. Expiring suggested tags older than 7 days
4. Re-queuing stale events (pending > 24 hours)

## Dependencies

- `fastapi>=0.110.0`
- `uvicorn[standard]>=0.27.0`
- `aiosqlite>=0.20.0`
- `redis[hiredis]>=5.0`
- `python-multipart>=0.0.9`
- `life-organiser-shared` (must be installed first)
