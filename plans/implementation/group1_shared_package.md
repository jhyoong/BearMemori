# Group 1: Shared Package Foundation

## Goal

Create the `shared/` Python package that all services depend on. This package defines the API contracts (Pydantic schemas), enums, configuration loading, and Redis Streams helpers used across the entire system.

**Depends on:** Nothing (this is the first group)
**Blocks:** All other groups

---

## Context

The Life Organiser is a multi-service architecture with 4 custom services (Core, Telegram Gateway, LLM Worker, Email Poller) communicating via REST APIs and Redis Streams. The shared package ensures type consistency and avoids duplication across services.

The shared package is installed as an editable dependency in each service's Docker image via `pip install -e ../shared`.

---

## Steps

### Step 1.1: Create shared package structure

**Files to create:**
- `shared/pyproject.toml`
- `shared/shared/__init__.py`

**`shared/pyproject.toml` details:**
- Package name: `life-organiser-shared`
- Requires Python >= 3.12
- Dependencies: `pydantic>=2.0`, `pydantic-settings>=2.0`, `redis>=5.0`
- Use `[build-system]` with `hatchling` or `setuptools`

**`shared/shared/__init__.py`:**
- Empty file (just makes it a package)

---

### Step 1.2: Define shared enums

**File:** `shared/shared/enums.py`

Use Python's `enum.StrEnum` (available in 3.11+) for all enums. StrEnum values serialize naturally to strings in JSON.

**Enums to define:**

| Enum | Values | Used by |
|---|---|---|
| `MemoryStatus` | `confirmed`, `pending` | memories table, memory creation logic |
| `TaskState` | `NOT_DONE`, `DONE` | tasks table, task completion logic |
| `EventStatus` | `pending`, `confirmed`, `rejected` | events table, event confirmation flow |
| `EventSourceType` | `email`, `manual` | events table |
| `MediaType` | `image` | memories table (nullable field) |
| `JobType` | `image_tag`, `intent_classify`, `followup`, `task_match`, `email_extract` | llm_jobs table, Redis stream routing |
| `JobStatus` | `queued`, `processing`, `completed`, `failed` | llm_jobs table |
| `AuditAction` | `created`, `confirmed`, `deleted`, `expired`, `fired`, `updated`, `rejected`, `requeued` | audit_log table |
| `EntityType` | `memory`, `task`, `reminder`, `event`, `llm_job` | audit_log table |

---

### Step 1.3: Define shared config

**File:** `shared/shared/config.py`

Use `pydantic_settings.BaseSettings` to load environment variables with defaults.

**Config fields:**

| Field | Env var | Default | Description |
|---|---|---|---|
| `redis_url` | `REDIS_URL` | `redis://redis:6379` | Redis connection URL |
| `core_host` | `CORE_HOST` | `0.0.0.0` | Core service bind host |
| `core_port` | `CORE_PORT` | `8000` | Core service bind port |
| `database_path` | `DATABASE_PATH` | `/data/db/life_organiser.db` | SQLite DB file path |
| `image_storage_path` | `IMAGE_STORAGE_PATH` | `/data/images` | Local image storage dir |
| `core_api_url` | `CORE_API_URL` | `http://core:8000` | URL for other services to reach Core |

---

### Step 1.4: Define shared Pydantic schemas

**File:** `shared/shared/schemas.py`

All request/response models for the REST API. Every router and client imports from here.

**Memory schemas:**
- `MemoryCreate` -- fields: `owner_user_id` (int), `content` (str, optional), `media_type` (MediaType, optional), `media_file_id` (str, optional), `source_chat_id` (int, optional), `source_message_id` (int, optional)
- `MemoryUpdate` -- fields: all optional: `content`, `status` (MemoryStatus), `is_pinned` (bool), `media_local_path` (str)
- `MemoryResponse` -- fields: `id`, `owner_user_id`, `content`, `media_type`, `media_file_id`, `media_local_path`, `status`, `pending_expires_at`, `is_pinned`, `created_at`, `updated_at`
- `MemoryWithTags` -- extends MemoryResponse with `tags: list[TagResponse]`

**Tag schemas:**
- `TagAdd` -- fields: `tags` (list[str]), `status` (str, default "confirmed")
- `TagResponse` -- fields: `tag` (str), `status` (str), `suggested_at` (optional), `confirmed_at` (optional)

**Task schemas:**
- `TaskCreate` -- fields: `memory_id` (str), `owner_user_id` (int), `description` (str), `due_at` (datetime, optional), `recurrence_minutes` (int, optional)
- `TaskUpdate` -- fields: all optional: `state` (TaskState), `description`, `due_at`, `recurrence_minutes`
- `TaskResponse` -- all fields from the tasks table

**Reminder schemas:**
- `ReminderCreate` -- fields: `memory_id` (str), `owner_user_id` (int), `fire_at` (datetime), `recurrence_minutes` (int, optional)
- `ReminderUpdate` -- fields: optional `fire_at`, `recurrence_minutes`
- `ReminderResponse` -- all fields from the reminders table

**Event schemas:**
- `EventCreate` -- fields: `owner_user_id` (int), `description` (str), `event_date` (datetime), `source_type` (EventSourceType), `source_ref` (str, optional), `memory_id` (str, optional)
- `EventUpdate` -- fields: optional `status` (EventStatus), `description`, `event_date`
- `EventResponse` -- all fields from the events table

**Settings schemas:**
- `UserSettingsResponse` -- fields: `telegram_user_id` (int), `default_reminder_time` (str), `timezone` (str)
- `UserSettingsUpdate` -- fields: optional `default_reminder_time`, `timezone`

**Search schemas:**
- `SearchResult` -- fields: `memory` (MemoryWithTags), `score` (float)

**Audit schemas:**
- `AuditLogEntry` -- fields: `id` (int), `entity_type`, `entity_id`, `action`, `actor`, `detail` (dict, optional), `created_at`

**Backup schemas:**
- `BackupStatus` -- fields: `last_backup_at` (datetime, optional), `status` (str)

**LLM Job schemas:**
- `LLMJobCreate` -- fields: `job_type` (JobType), `payload` (dict)
- `LLMJobUpdate` -- fields: optional `status` (JobStatus), `result` (dict), `error` (str), `attempts` (int)
- `LLMJobResponse` -- all fields from the llm_jobs table

**Redis message schemas:**
- `TelegramOutboundMessage` -- fields: `user_id` (int), `message_type` (str), `content` (dict)
- `ReminderNotification` -- fields: `user_id` (int), `reminder_id` (str), `memory_id` (str), `memory_content` (str, optional)

**Notes:**
- Use `datetime` for all timestamp fields
- Use `model_config = ConfigDict(from_attributes=True)` where needed for ORM-style usage
- All optional fields should use `None` as default

---

### Step 1.5: Define Redis Streams helpers

**File:** `shared/shared/redis_streams.py`

**Stream name constants:**
```
STREAM_LLM_IMAGE_TAG = "llm:image_tag"
STREAM_LLM_INTENT = "llm:intent"
STREAM_LLM_FOLLOWUP = "llm:followup"
STREAM_LLM_TASK_MATCH = "llm:task_match"
STREAM_LLM_EMAIL_EXTRACT = "llm:email_extract"
STREAM_NOTIFY_TELEGRAM = "notify:telegram"
```

**Consumer group name constants:**
```
GROUP_LLM_WORKER = "llm-worker-group"
GROUP_TELEGRAM = "telegram-group"
```

**Async helper functions:**

- `async def publish(redis_client, stream_name: str, data: dict) -> str`
  - Serializes `data` to JSON, calls `XADD`, returns the message ID

- `async def create_consumer_group(redis_client, stream_name: str, group_name: str) -> None`
  - Calls `XGROUP CREATE` with `mkstream=True`
  - Catches and ignores "BUSYGROUP" error (group already exists)

- `async def consume(redis_client, stream_name: str, group_name: str, consumer_name: str, count: int = 1, block_ms: int = 5000) -> list`
  - Calls `XREADGROUP`, returns list of (message_id, data) tuples
  - `data` values are deserialized from JSON

- `async def ack(redis_client, stream_name: str, group_name: str, message_id: str) -> None`
  - Calls `XACK`

---

## Acceptance Criteria

1. `shared/` is a valid Python package that can be installed via `pip install -e ./shared`
2. All enums are importable: `from shared.enums import MemoryStatus, TaskState, ...`
3. All schemas are importable: `from shared.schemas import MemoryCreate, TaskResponse, ...`
4. Config loads from environment variables with sensible defaults
5. Redis helpers can publish and consume messages (testable with a real or mock Redis)
