# Life Organiser — Implementation Plans

**Version 1.0 | February 2026**
**Companion to PRD v1.2**

---

## How to Read This Document

This document contains one architectural plan and four implementation plans. The architectural plan (Plan 0) defines the shared structure, conventions, and decisions that all other plans depend on. Plans 1–4 each cover a distinct service and can be built sequentially in order.

**Build order:** Plan 1 → Plan 2 → Plan 3 → Plan 4

Each plan is self-contained enough to be a buildable milestone. At the end of Plan 2, you have a fully working Telegram bot with capture, tasks, reminders, and keyword search — no LLM required. Plan 3 adds intelligence. Plan 4 adds email.

---

## Plan 0: Architecture & Project Structure

### 0.1 Goal

Establish the monorepo layout, service boundaries, communication patterns, database schema, image storage strategy, and Docker Compose configuration that all subsequent plans build on.

### 0.2 Tech Stack Decisions

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.12+ | Per preference. All services. |
| Database | SQLite (via `aiosqlite`) | Easy backups (single file copy). One DB, owned by one service. |
| Search | SQLite FTS5 | Built-in full-text search. Provides keyword fallback when LLM is down. Resolves PRD open question on search fallback. |
| Message broker | Redis Streams | Lightweight. Handles async job queues (LLM jobs, email events). Avoids shared DB. Already battle-tested for small-scale. |
| HTTP framework | FastAPI | Async, lightweight, auto-generated OpenAPI docs. Used by the Core service to expose its REST API. |
| Telegram library | `python-telegram-bot` (v20+) | Async, well-maintained, covers inline keyboards and callbacks. |
| Email | `aioimaplib` + OAuth2 | Async IMAP for Gmail and Outlook. OAuth2 via app passwords or service credentials. |
| LLM client | OpenAI Python SDK (`openai`) | Uses the OpenAI API (`/v1/chat/completions`). Supports text and vision models. |
| Containerisation | Docker + Docker Compose | One Compose file orchestrates all services. |
| Backup | `boto3` (S3) | Weekly SQLite file + image directory upload. |

### 0.3 Service Architecture

There are four custom services and one infrastructure dependency.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Docker Compose                           │
│                                                                 │
│  ┌──────────────┐    REST     ┌──────────────┐                  │
│  │   Telegram    │ ────────── │     Core      │                  │
│  │   Gateway     │            │   (API +      │                  │
│  └──────────────┘            │  Scheduler +   │                  │
│                               │   Search)     │                  │
│  ┌──────────────┐    REST     │              │                  │
│  │    Email      │ ─────┬──── └──────┬───────┘                  │
│  │    Poller     │      │            │                           │
│  └──────────────┘      │            │                           │
│                         │     Redis Streams                     │
│  ┌──────────────┐      │            │                           │
│  │  LLM Worker  │ ─────┴──── ┌──────┴───────┐                  │
│  │              │            │    Redis      │                  │
│  └──────┬───────┘            └──────────────┘                  │
│         │                                                       │
│         │ HTTP                                                  │
└─────────┼───────────────────────────────────────────────────────┘
          │
          ▼
   ┌──────────────┐
   │  OpenAI API  │  (external service)
   └──────────────┘
```

**Service responsibilities:**

| Service | Owns | Communicates via |
|---|---|---|
| **Core** | SQLite DB, image files, scheduler, search, audit log, backup | Exposes REST API. Publishes/consumes Redis Streams. |
| **Telegram Gateway** | Telegram bot connection, user session context | Calls Core REST API. Publishes to Redis (LLM jobs). |
| **LLM Worker** | Nothing persistent | Consumes Redis (LLM jobs). Calls the OpenAI API. Calls Core REST API to deliver results. |
| **Email Poller** | Nothing persistent | Calls Core REST API. Publishes to Redis (LLM jobs for email extraction). |
| **Redis** | Streams, consumer groups | Standard Redis image. Persistence enabled (AOF). |

**Why Core owns the database exclusively:** SQLite supports only one writer at a time. By routing all writes through Core's REST API, we avoid contention entirely. All other services are clients of Core.

### 0.4 Monorepo Structure

```
life-organiser/
├── docker-compose.yml
├── .env.example
├── README.md
│
├── shared/                     # Shared Python package (installed in all images)
│   ├── pyproject.toml
│   └── shared/
│       ├── __init__.py
│       ├── schemas.py          # Pydantic models (API contracts)
│       ├── enums.py            # Shared enums (MemoryStatus, TaskState, etc.)
│       ├── redis_streams.py    # Stream names, publish/consume helpers
│       └── config.py           # Shared config loading from env vars
│
├── core/                       # Core service (Docker image: life-org-core)
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── core/
│       ├── __init__.py
│       ├── main.py             # FastAPI app entrypoint
│       ├── database.py         # SQLite setup, migrations
│       ├── models.py           # SQLAlchemy/raw SQL data models
│       ├── routers/
│       │   ├── memories.py
│       │   ├── tasks.py
│       │   ├── reminders.py
│       │   ├── events.py
│       │   ├── search.py
│       │   ├── settings.py
│       │   └── audit.py
│       ├── scheduler.py        # Reminder firing, image expiry, tag expiry
│       ├── search.py           # FTS5 query builder, ranking logic
│       ├── backup.py           # S3 backup logic
│       └── audit.py            # Audit log helpers
│
├── telegram/                   # Telegram Gateway (Docker image: life-org-telegram)
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── tg_gateway/
│       ├── __init__.py
│       ├── main.py             # Bot entrypoint
│       ├── gateway.py          # Abstract gateway interface
│       ├── handlers/
│       │   ├── message.py      # Text + image capture
│       │   ├── callback.py     # Inline button presses
│       │   ├── command.py      # /find, /tasks, /pinned, etc.
│       │   └── conversation.py # Multi-step flows (tag editing, date picking)
│       ├── keyboards.py        # Inline keyboard builders
│       ├── core_client.py      # HTTP client for Core REST API
│       └── media.py            # Telegram file download helpers
│
├── llm_worker/                 # LLM Worker (Docker image: life-org-llm-worker)
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── llm_worker/
│       ├── __init__.py
│       ├── main.py             # Consumer entrypoint
│       ├── consumer.py         # Redis stream consumer loop
│       ├── llm_client.py       # OpenAI API client
│       ├── handlers/
│       │   ├── image_tag.py    # Vision model: tag + describe images
│       │   ├── intent.py       # Text model: classify search intent
│       │   ├── followup.py     # Text model: generate clarifying questions
│       │   ├── task_match.py   # Text model: match memories to open tasks
│       │   └── email_event.py  # Text model: extract events from emails
│       └── retry.py            # Exponential backoff logic
│
├── email_poller/               # Email Poller (Docker image: life-org-email)
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── email_poller/
│       ├── __init__.py
│       ├── main.py             # Poller entrypoint
│       ├── imap_client.py      # IMAP connection + fetch logic
│       ├── auth.py             # OAuth2 / app password handling
│       ├── filters.py          # Email filtering rules
│       └── poller.py           # Poll loop + dedup
│
├── scripts/                    # Dev/ops utilities
│   ├── init_db.py
│   ├── backup_now.py
│   └── restore.py
│
└── tests/
    ├── test_core/
    ├── test_telegram/
    ├── test_llm_worker/
    └── test_email/
```

### 0.5 Database Schema (SQLite)

All tables live in a single SQLite file owned by Core. FTS5 virtual tables provide keyword search.

```sql
-- Core tables

CREATE TABLE users (
    telegram_user_id  INTEGER PRIMARY KEY,
    display_name      TEXT NOT NULL,
    is_allowed        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE user_settings (
    telegram_user_id      INTEGER PRIMARY KEY REFERENCES users(telegram_user_id),
    default_reminder_time TEXT NOT NULL DEFAULT '09:00',   -- HH:MM format
    timezone              TEXT NOT NULL DEFAULT 'Asia/Singapore'
);

CREATE TABLE memories (
    id                  TEXT PRIMARY KEY,    -- UUID
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    source_chat_id      INTEGER,
    source_message_id   INTEGER,
    content             TEXT,                -- message text or caption
    media_type          TEXT,                -- NULL, 'image'
    media_file_id       TEXT,                -- Telegram file_id
    media_local_path    TEXT,                -- local filesystem path to downloaded image
    status              TEXT NOT NULL DEFAULT 'confirmed',  -- 'confirmed' | 'pending'
    pending_expires_at  TEXT,                -- ISO datetime, NULL for text memories
    is_pinned           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE memory_tags (
    memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'confirmed',  -- 'confirmed' | 'suggested'
    suggested_at TEXT,
    confirmed_at TEXT,
    PRIMARY KEY (memory_id, tag)
);

CREATE TABLE tasks (
    id                  TEXT PRIMARY KEY,    -- UUID
    memory_id           TEXT NOT NULL REFERENCES memories(id),
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    description         TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'NOT_DONE',  -- 'NOT_DONE' | 'DONE'
    due_at              TEXT,                -- ISO datetime, nullable
    recurrence_minutes  INTEGER,             -- nullable
    completed_at        TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE reminders (
    id                  TEXT PRIMARY KEY,    -- UUID
    memory_id           TEXT NOT NULL REFERENCES memories(id),
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    fire_at             TEXT NOT NULL,       -- ISO datetime
    recurrence_minutes  INTEGER,             -- nullable
    fired               INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE events (
    id                  TEXT PRIMARY KEY,    -- UUID
    memory_id           TEXT REFERENCES memories(id),  -- nullable (email-sourced may not have one yet)
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    description         TEXT NOT NULL,
    event_date          TEXT NOT NULL,       -- ISO datetime
    source_type         TEXT NOT NULL,       -- 'email' | 'manual'
    source_ref          TEXT,                -- email message-id or similar
    status              TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'confirmed' | 'rejected'
    pending_since       TEXT,
    reminder_id         TEXT REFERENCES reminders(id),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,       -- 'memory' | 'task' | 'reminder' | 'event' | 'llm_job'
    entity_id   TEXT NOT NULL,
    action      TEXT NOT NULL,       -- 'created' | 'confirmed' | 'deleted' | 'expired' | 'fired' | etc.
    actor       TEXT NOT NULL,       -- 'user:<id>' | 'system:scheduler' | 'system:llm_worker'
    detail      TEXT,                -- JSON blob for extra context
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE llm_jobs (
    id              TEXT PRIMARY KEY,    -- UUID
    job_type        TEXT NOT NULL,       -- 'image_tag' | 'intent_classify' | 'followup' | 'task_match' | 'email_extract'
    payload         TEXT NOT NULL,       -- JSON
    status          TEXT NOT NULL DEFAULT 'queued', -- 'queued' | 'processing' | 'completed' | 'failed'
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 5,
    result          TEXT,                -- JSON, nullable
    error           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- FTS5 index for keyword search (confirmed memories only, kept in sync via triggers)
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    tags,
    content='memories',
    content_rowid='rowid'
);

-- Indexes
CREATE INDEX idx_memories_owner ON memories(owner_user_id);
CREATE INDEX idx_memories_status ON memories(status);
CREATE INDEX idx_memories_pending_expires ON memories(pending_expires_at) WHERE pending_expires_at IS NOT NULL;
CREATE INDEX idx_tasks_state ON tasks(state);
CREATE INDEX idx_tasks_owner ON tasks(owner_user_id);
CREATE INDEX idx_reminders_fire ON reminders(fire_at) WHERE fired = 0;
CREATE INDEX idx_events_status ON events(status);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
```

### 0.6 Image Storage Strategy

Images are handled in three tiers:

1. **Telegram `file_id`** — stored in `memories.media_file_id` at ingest. Used for fast re-sending via Telegram API (no re-upload needed).
2. **Local filesystem** — image bytes downloaded asynchronously after capture and stored at a configured path (e.g., `/data/images/<memory_id>.jpg`). Path stored in `memories.media_local_path`. This is the durable copy.
3. **S3 backup** — the `/data/images/` directory is included in the weekly S3 backup alongside the SQLite file.

The download from Telegram to local filesystem is triggered by the Telegram Gateway after capture. It calls a Core endpoint to register the local path once complete. If download fails, it retries. The `file_id` remains the fallback for serving images back through Telegram.

For hard deletes, Core removes both the database record and the local image file.

### 0.7 Redis Streams Design

All async communication flows through Redis Streams. Each stream represents a job type.

| Stream name | Producer | Consumer | Purpose |
|---|---|---|---|
| `llm:image_tag` | Telegram Gateway | LLM Worker | Image tagging requests |
| `llm:intent` | Telegram Gateway | LLM Worker | Search intent classification |
| `llm:followup` | Telegram Gateway | LLM Worker | Clarifying question generation |
| `llm:task_match` | Telegram Gateway | LLM Worker | Task completion suggestions |
| `llm:email_extract` | Email Poller | LLM Worker | Email event extraction |
| `notify:telegram` | Core (scheduler), LLM Worker | Telegram Gateway | Outbound messages (reminders, LLM results, follow-ups) |

Each consumer uses a Redis consumer group for reliable delivery. If a consumer crashes, unacknowledged messages are re-delivered on restart.

### 0.8 Inter-Service Communication Patterns

**Synchronous (REST):** Used when the caller needs an immediate response.

Examples: Telegram Gateway creates a memory via `POST /memories`, fetches search results via `GET /search`, marks a task done via `PATCH /tasks/{id}`.

**Asynchronous (Redis Streams):** Used when the result is not needed immediately or the work is long-running.

Examples: Image tagging (may take seconds), email extraction, sending outbound Telegram messages from non-Telegram services.

### 0.9 Configuration & Environment Variables

All configuration is via environment variables, documented in `.env.example`.

```env
# Core
CORE_HOST=0.0.0.0
CORE_PORT=8000
DATABASE_PATH=/data/db/life_organiser.db
IMAGE_STORAGE_PATH=/data/images
S3_BUCKET=life-organiser-backup
S3_REGION=ap-southeast-1
BACKUP_SCHEDULE_CRON=0 3 * * 0    # Weekly Sunday 3am

# Redis
REDIS_URL=redis://redis:6379

# Telegram
TELEGRAM_BOT_TOKEN=<token>
ALLOWED_USER_IDS=123456,789012     # Comma-separated allowlist
CORE_API_URL=http://core:8000

# LLM Worker
LLM_BASE_URL=https://api.openai.com/v1
LLM_VISION_MODEL=gpt-4o-mini
LLM_TEXT_MODEL=gpt-4o-mini
LLM_API_KEY=sk-your-openai-api-key-here
LLM_MAX_RETRIES=5

# Email
EMAIL_POLL_INTERVAL_SECONDS=300    # 5 minutes
GMAIL_IMAP_HOST=imap.gmail.com
OUTLOOK_IMAP_HOST=outlook.office365.com
EMAIL_ACCOUNTS=<JSON array of account configs>
```

### 0.10 Docker Compose Outline

```yaml
services:
  core:
    build: ./core
    volumes:
      - db-data:/data/db
      - image-data:/data/images
    ports:
      - "8000:8000"
    depends_on:
      - redis
    env_file: .env

  telegram:
    build: ./telegram
    depends_on:
      - core
      - redis
    env_file: .env

  llm-worker:
    build: ./llm_worker
    depends_on:
      - core
      - redis
    env_file: .env

  email:
    build: ./email_poller
    depends_on:
      - core
      - redis
    env_file: .env

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    volumes:
      - redis-data:/data

volumes:
  db-data:
  image-data:
  redis-data:
```

### 0.11 Shared Package

The `shared/` package is installed as an editable dependency in each service's Docker image. It contains:

- **`schemas.py`** — Pydantic models defining the API contracts between services (e.g., `MemoryCreate`, `TaskUpdate`, `LLMJobPayload`, `TelegramOutboundMessage`). All services import from here, ensuring type consistency.
- **`enums.py`** — Shared enums: `MemoryStatus`, `TaskState`, `JobType`, `AuditAction`, etc.
- **`redis_streams.py`** — Stream name constants and helper functions for publishing and consuming.
- **`config.py`** — Shared config loading utilities.

### 0.12 Decisions Resolving PRD Open Questions

| PRD Open Question | Decision |
|---|---|
| Search fallback when LLM is down | SQLite FTS5 provides keyword search that works without the LLM. LLM adds intent classification and disambiguation on top. When LLM is down, `/find` falls back to direct FTS5 keyword search. |
| Tech stack | Python, FastAPI, SQLite, Redis, Docker. See section 0.2. |
| Email implementation details | IMAP polling with OAuth2/app passwords. Gmail and Outlook. 5-minute poll interval. See Plan 4. |

---

## Plan 1: Core Service

### 1.1 Goal

Build the central service that owns all persistent state. At the end of this plan, Core exposes a complete REST API for memories, tasks, reminders, events, search, and settings — tested with `curl` or a simple script. No Telegram yet.

### 1.2 Features

**Database setup and migrations**
- Initialise SQLite database with the schema from Plan 0.
- Simple migration approach: a `migrations/` directory with numbered SQL files. Core checks a `schema_version` pragma on startup and applies pending migrations.

**REST API: Memories**
- `POST /memories` — create a memory (text or image). Auto-sets `status` to `confirmed` for text, `pending` for images. Sets `pending_expires_at` for images.
- `GET /memories/{id}` — fetch a single memory with its tags.
- `PATCH /memories/{id}` — update fields (pin, confirm status, etc.).
- `DELETE /memories/{id}` — hard delete. Removes DB record, local image file, and FTS5 entry. Audit logged.
- `POST /memories/{id}/tags` — add or confirm tags.
- `DELETE /memories/{id}/tags/{tag}` — remove a tag.

**REST API: Tasks**
- `POST /tasks` — create a task from a memory.
- `GET /tasks` — list tasks with filters (state, owner, due date range).
- `PATCH /tasks/{id}` — update task (mark done, change due date). On marking done: if `recurrence_minutes` is set, auto-create next task instance. All deterministic.
- `DELETE /tasks/{id}` — hard delete.

**REST API: Reminders**
- `POST /reminders` — create a reminder linked to a memory.
- `GET /reminders` — list upcoming reminders.
- `PATCH /reminders/{id}` — update (e.g., change fire time).
- `DELETE /reminders/{id}` — cancel and delete.

**REST API: Events**
- `POST /events` — create a pending event (from email extraction).
- `PATCH /events/{id}` — confirm or reject. On confirm: auto-create a linked reminder.
- `GET /events` — list events with status filter.

**REST API: Search**
- `GET /search?q=<query>&owner=<user_id>&pinned=<bool>` — queries the FTS5 index. Returns results ranked by relevance with pin boost. Only searches confirmed memories. Returns memory data with associated tags and linked tasks/reminders.

**REST API: Settings**
- `GET /settings/{user_id}` — fetch user settings.
- `PATCH /settings/{user_id}` — update settings (default reminder time, timezone).

**Scheduler (runs inside Core process)**
- An async background loop that runs every 30 seconds.
- **Reminder firing:** queries `reminders` for unfired reminders where `fire_at <= now`. Publishes a message to `notify:telegram` Redis stream. Marks reminder as fired. If recurring, creates next reminder instance.
- **Pending image expiry:** queries `memories` for pending images where `pending_expires_at <= now`. Hard deletes them. Audit logged.
- **Suggested tag expiry:** queries `memory_tags` for suggested tags older than 7 days. Deletes them. Audit logged.
- **Event re-queue:** queries `events` for pending events where `pending_since` is older than 24 hours. Publishes a re-prompt to `notify:telegram`. Resets `pending_since`. Audit logged.

**Audit logging**
- Every state transition writes to `audit_log` with entity type, entity ID, action, actor, and optional JSON detail.
- Exposed via `GET /audit?entity_type=&entity_id=` for debugging.

**Backup**
- A scheduled job (configurable cron, default weekly) that:
  1. Creates a SQLite backup using the `.backup` API (safe while DB is in use).
  2. Tars the image directory.
  3. Uploads both to S3.
  4. Records `last_backup_at` in a metadata table.
- `GET /backup/status` — returns last backup timestamp.

**FTS5 sync**
- On memory create/update/delete, Core updates the FTS5 index. Tags for a memory are concatenated into the `tags` column of the FTS5 table. Only confirmed memories with confirmed tags are indexed.

### 1.3 Acceptance Criteria

1. All CRUD endpoints work and return correct responses.
2. Creating a text memory sets status to `confirmed`. Creating an image memory sets status to `pending` with `pending_expires_at` = created_at + 7 days.
3. Marking a recurring task as done auto-creates the next instance with the correct due date.
4. Scheduler fires reminders and publishes to Redis.
5. Scheduler deletes expired pending images and suggested tags.
6. FTS5 search returns relevant results and boosts pinned items.
7. Hard delete removes DB record, image file, and FTS5 entry.
8. Audit log records all state transitions.
9. S3 backup completes and `GET /backup/status` returns a valid timestamp.

---

## Plan 2: Telegram Gateway

### 2.1 Goal

Build the Telegram bot that serves as the user interface. At the end of this plan, users can send messages and images, interact with inline buttons, search, manage tasks, and receive reminders — all through Telegram. This is the first user-facing milestone.

### 2.2 Features

**Bot setup and security**
- Long-polling based Telegram bot (no webhook needed for personal server).
- User allowlisting: only `ALLOWED_USER_IDS` can interact. Unknown users get a polite rejection.
- Bot registers handlers for text, images, commands, and callback queries.

**Gateway abstraction layer**
- Define an abstract `Gateway` interface in `gateway.py` with methods like `send_message`, `send_image`, `send_inline_keyboard`, `answer_callback`. The Telegram implementation fulfils this interface. Future platforms would implement the same interface.

**Text message capture**
- On receiving a text message: call `POST /memories` on Core with `media_type=null`, `status=confirmed`.
- Reply with inline keyboard: `[Task] [Remind] [Tag] [Pin] [Delete]`.

**Image capture**
- On receiving an image (photo or document): download the file via Telegram API, call `POST /memories` on Core with `media_type=image`, `status=pending`, include the `file_id`.
- Async: download image bytes and store locally via a Core endpoint.
- Reply with inline keyboard: `[Confirm Tags] [Edit Tags] [Task] [Remind] [Pin] [Delete]`.
- If LLM is available, also publish an `llm:image_tag` job to Redis.

**Inline keyboard callbacks**
- **Task:** prompt for an optional due date (offer quick options: today, tomorrow, next week, custom). Call `POST /tasks`.
- **Remind:** prompt for a reminder time (offer quick options: 1 hour, tomorrow 9am, custom). Call `POST /reminders`.
- **Tag:** if tags were suggested by LLM, show confirm/edit flow. Also allow manual tag entry.
- **Pin:** call `PATCH /memories/{id}` to set `is_pinned=true`. For pending images, this confirms the memory.
- **Delete:** call `DELETE /memories/{id}`. Confirm first with a "Are you sure?" prompt.

**Commands**
- `/find <query>` — call `GET /search` on Core. Display top 3-5 results as a numbered list with brief snippets. Each result gets a `[Show details]` inline button. "Show details" re-sends the full record including the image (via `file_id` or local file).
- `/tasks` — call `GET /tasks?state=NOT_DONE` on Core. Display as a list with `[Mark Done]` buttons.
- `/pinned` — call `GET /search?pinned=true` on Core.
- `/help` — display available commands.

**Outbound message consumer**
- A background task listens on the `notify:telegram` Redis stream.
- Handles: reminder notifications, LLM results (tag suggestions, intent classification responses, follow-up questions, task match suggestions), event confirmation prompts.
- Each message type has a tailored Telegram message format with appropriate inline keyboards.

**Multi-step conversation flows**
- Tag editing: user taps "Edit Tags" → bot asks for new tags → user replies → tags saved.
- Custom date picking: user taps "Custom" for a due date or reminder → bot asks for date/time → user replies → parsed and saved.
- These use `python-telegram-bot`'s `ConversationHandler` for state management.

**Error handling**
- If Core is unreachable, reply with a user-friendly message ("I'm having trouble right now, please try again in a moment").
- If a callback button press is for an expired or deleted memory, reply with "This item no longer exists".

### 2.3 Acceptance Criteria

1. Sending a text message in DM creates a confirmed memory and shows inline buttons.
2. Sending an image creates a pending memory and shows inline buttons.
3. Tapping "Task" prompts for a due date and creates a task.
4. Tapping "Remind" prompts for a time and creates a reminder.
5. Tapping "Pin" pins the memory (and confirms pending images).
6. Tapping "Delete" prompts confirmation, then hard deletes.
7. `/find butter` returns relevant results with "Show details" buttons.
8. `/tasks` lists open tasks with "Mark Done" buttons.
9. Marking a recurring task as done shows the newly created next instance.
10. Reminders arrive in Telegram at the scheduled time.
11. LLM tag suggestions arrive as a follow-up message with confirm/edit buttons.
12. Non-allowlisted users are rejected.

---

## Plan 3: LLM Worker

### 3.1 Goal

Build the LLM integration layer. At the end of this plan, the system can tag images, classify search intent, generate follow-up questions, suggest task completions, and extract events from emails — all via the OpenAI API.

### 3.2 Features

**Redis stream consumer**
- A long-running async process that listens on all `llm:*` Redis streams using consumer groups.
- Processes one job at a time per stream (configurable concurrency if needed later).
- On receiving a job: update status to `processing` in Core (`PATCH /llm-jobs/{id}`), process, then update to `completed` or `failed`.

**OpenAI API client**
- Uses the OpenAI Python SDK (`openai`) for `/v1/chat/completions`.
- Supports both vision and text models.
- Handles timeouts, connection errors, and API failures.
- Model names are configurable via env vars (`LLM_VISION_MODEL`, `LLM_TEXT_MODEL`).

**Image tagging handler (`llm:image_tag`)**
- Input: memory ID, image path or file_id.
- Process: fetch image bytes (from local path or via Core), send to vision model with a structured prompt asking for tags, optional description, optional location.
- Output: publish result to `notify:telegram` with suggested tags for user confirmation. Save suggested tags via `POST /memories/{id}/tags` with `status=suggested`.
- Prompt design: instruct the model to return JSON with `tags`, `description`, and `location` fields. Parse the response. If parsing fails, retry with a simpler prompt.

**Intent classification handler (`llm:intent`)**
- Input: query text, user ID.
- Process: send to text model with a prompt classifying intent as one of `task_query`, `event_query`, `memory_query`, or `ambiguous`.
- Output: return classification to Telegram Gateway (via `notify:telegram` or a dedicated response stream). Telegram Gateway then routes the search accordingly.

**Follow-up question handler (`llm:followup`)**
- Input: original query, empty/ambiguous result set context.
- Process: send to text model asking it to generate a clarifying question.
- Output: publish the question to `notify:telegram` for delivery to the user.

**Task completion matching handler (`llm:task_match`)**
- Input: new memory content/caption, list of open task descriptions.
- Process: send to text model asking if the new memory relates to any open task.
- Output: if a match is found with sufficient confidence, publish a suggestion to `notify:telegram` with "Mark as DONE? [Yes] [No]" buttons.

**Email event extraction handler (`llm:email_extract`)**
- Input: email subject, body text.
- Process: send to text model with a prompt asking for candidate events (date, description, confidence).
- Output: for each candidate, call `POST /events` on Core with status `pending`, then publish to `notify:telegram` for user confirmation.

**Retry and backoff**
- Failed jobs stay on the queue and are retried with exponential backoff (1s, 2s, 4s, 8s, 16s, etc.).
- After `max_attempts` (default 5) failures, mark job as `failed` in Core, publish a notification to the user ("I couldn't generate tags for your image — you can add them manually").
- Retry state is tracked in the `llm_jobs` table via Core's API.

**Queue persistence**
- Redis Streams with consumer groups guarantee that unacknowledged messages survive worker restarts.
- The `llm_jobs` table in Core provides a secondary record for audit and status tracking.

### 3.3 Prompt Design Notes

Prompts should be kept in separate text files or constants for easy iteration. Key design principles:

- Always request structured JSON output.
- Include examples in the prompt (few-shot) for consistent formatting.
- For image tagging, instruct the model to distinguish between confident and uncertain tags.
- For intent classification, provide clear definitions and examples of each intent category.
- Keep prompts minimal and concise for consistent results.

### 3.4 Acceptance Criteria

1. Sending an image triggers a tagging job. Tags appear as a follow-up message in Telegram within a reasonable time.
2. Using `/find` with a natural language query triggers intent classification and routes correctly.
3. An ambiguous query produces a clarifying follow-up question.
4. Sending an image related to an open task triggers a task completion suggestion.
5. If the LLM API is unreachable, jobs queue up and are processed when it comes back.
6. After 5 failed attempts, the user is notified and the job is marked failed.
7. Worker restarts do not lose queued jobs.

---

## Plan 4: Email Poller

### 4.1 Goal

Build the email integration. At the end of this plan, the system periodically checks configured email accounts, extracts candidate events, and sends them to the user for confirmation via Telegram.

### 4.2 Features

**IMAP client**
- Async IMAP client supporting Gmail (`imap.gmail.com:993`) and Outlook (`outlook.office365.com:993`).
- Connects via SSL/TLS.
- Authentication: OAuth2 for Gmail (via app passwords or service account), OAuth2 for Outlook (via app passwords). Configuration is per-account in the `EMAIL_ACCOUNTS` env var (JSON array).

**Account configuration**
- Each account specifies: provider (gmail/outlook), email address, auth credentials, and optional folder to monitor (default: INBOX).
- Multiple accounts are supported.

**Poll loop**
- Runs on a configurable interval (default: 5 minutes).
- On each poll: connect to IMAP, fetch unseen messages since last poll, process each message, mark as seen (or track seen UIDs locally to avoid IMAP flag side-effects).
- Stores last-seen UID per account to avoid reprocessing.

**Email filtering**
- Configurable filters to ignore certain senders, subjects, or labels (e.g., skip newsletters, promotions).
- Default: process all unseen INBOX messages.

**Email processing pipeline**
1. Fetch email subject and plain-text body (strip HTML if needed using a simple parser).
2. Publish to `llm:email_extract` Redis stream with subject and body.
3. LLM Worker extracts candidate events and creates them via Core API.
4. Core scheduler handles the 24-hour pending/re-queue cycle (already implemented in Plan 1).

**Deduplication**
- Track processed email UIDs (or Message-IDs) to avoid re-extracting the same email.
- Store in a local SQLite or a simple JSON file within the container (not in Core's DB, since this is email-poller-specific state). Alternatively, store in Redis.

**Error handling**
- IMAP connection failures: log and retry on next poll interval.
- Authentication failures: log a clear error and notify the user via `notify:telegram` ("Email polling failed for <account> — please check credentials").
- Individual email processing failures: log, skip, continue with next email.

### 4.3 Authentication Setup Notes

**Gmail:**
- Option A: App password (simpler — requires 2FA enabled, then generate an app-specific password).
- Option B: OAuth2 with a Google Cloud project (more robust, but more setup).
- Recommendation: start with app passwords for personal use.

**Outlook:**
- Option A: App password (if available on the account).
- Option B: OAuth2 via Azure AD app registration.
- Recommendation: start with app passwords.

Document the setup steps in `email_poller/README.md`.

### 4.4 Acceptance Criteria

1. Poller connects to a configured Gmail account and fetches new emails.
2. Poller connects to a configured Outlook account and fetches new emails.
3. New emails are sent to the LLM worker for event extraction.
4. Extracted events appear in Telegram as confirmation prompts.
5. Confirming an event creates it with a linked reminder.
6. Rejecting an event discards it (audit logged).
7. Unanswered events are re-prompted after 24 hours (handled by Core scheduler).
8. Same email is not processed twice.
9. Connection failures are handled gracefully without crashing the service.

---

## Appendix A: Build Order and Milestones

| Phase | Plans | What works at the end |
|---|---|---|
| **Phase 1** | Plan 0 + Plan 1 | Project scaffolded. Core API running. DB initialised. Scheduler ticking. All endpoints testable via curl. |
| **Phase 2** | Plan 2 | Full Telegram bot. Capture, tasks, reminders, search all work. Keyword search via FTS5. No LLM needed. Reminders fire. This is a usable product. |
| **Phase 3** | Plan 3 | LLM enhances everything. Image tagging, smart search, follow-up questions, task matching. Graceful degradation when the LLM API is down. |
| **Phase 4** | Plan 4 | Email integration. Events extracted from Gmail/Outlook. Confirmation flow via Telegram. |

## Appendix B: Cross-Cutting Concerns

**Logging:** All services use Python's `logging` module with structured JSON output. Log level configurable via env var.

**Health checks:** Each service exposes a `GET /health` endpoint (or prints a heartbeat log). Docker Compose health checks use these.

**Graceful shutdown:** All services handle `SIGTERM` cleanly — finish in-progress work, close connections, then exit.

**Testing strategy:** Each service has unit tests for core logic and integration tests that use a test SQLite database and mock Redis. End-to-end tests (manual or scripted) cover the full flow from Telegram message to stored memory.

**Local development:** `docker compose up` starts everything. For iterating on a single service, run it locally with `CORE_API_URL=http://localhost:8000` and point at a shared dev Redis instance.
