# Shared Library

The foundational dependency for all BearMemori services. Provides Pydantic models, domain enums, configuration management, and Redis stream utilities. Must be installed before any other service.

## Installation

```bash
cd shared && pip install -e .
```

## Directory Structure

```
shared/
├── pyproject.toml
└── shared_lib/
    ├── __init__.py
    ├── config.py          # Settings class and load_config()
    ├── enums.py           # All domain enums
    ├── schemas.py         # All Pydantic request/response models
    └── redis_streams.py   # Redis stream helpers and constants
```

## Modules

### config.py

Centralized configuration via Pydantic Settings. All services use `load_config()` to get a `Settings` instance populated from environment variables.

Key settings: `redis_url`, `core_host`, `core_port`, `database_path`, `image_storage_path`, `core_api_url`.

### enums.py

Type-safe string enums used across all services:

| Enum | Values |
|---|---|
| `MemoryStatus` | `confirmed`, `pending` |
| `TaskState` | `NOT_DONE`, `DONE` |
| `EventStatus` | `pending`, `confirmed`, `rejected` |
| `EventSourceType` | `email`, `manual` |
| `MediaType` | `image` |
| `JobType` | `image_tag`, `intent_classify`, `followup`, `task_match`, `email_extract` |
| `JobStatus` | `queued`, `processing`, `completed`, `failed` |
| `AuditAction` | `created`, `confirmed`, `deleted`, `expired`, `fired`, `updated`, `rejected`, `requeued` |
| `EntityType` | `memory`, `task`, `reminder`, `event`, `llm_job` |

### schemas.py

30+ Pydantic models covering all API request/response contracts:

- **User:** `UserUpsert`, `UserResponse`
- **Memory:** `MemoryCreate`, `MemoryUpdate`, `MemoryResponse`, `MemoryWithTags`, `TagResponse`, `MemoryTagResponse`, `TagAdd`, `TagsAddRequest`
- **Task:** `TaskCreate`, `TaskUpdate`, `TaskResponse`, `TaskUpdateResponse`
- **Reminder:** `ReminderCreate`, `ReminderUpdate`, `ReminderResponse`
- **Event:** `EventCreate`, `EventUpdate`, `EventResponse`
- **Settings:** `UserSettingsResponse`, `UserSettingsUpdate`
- **Search:** `SearchResult`, `MemorySearchResult`
- **Audit:** `AuditLogEntry`
- **Backup:** `BackupStatus`
- **LLM Jobs:** `LLMJobCreate`, `LLMJobUpdate`, `LLMJobResponse`
- **Redis Messages:** `TelegramOutboundMessage`, `ReminderNotification`

### redis_streams.py

Async helpers for inter-service communication via Redis Streams.

**Stream constants:**
- `llm:image_tag`, `llm:intent`, `llm:followup`, `llm:task_match`, `llm:email_extract`
- `notify:telegram`

**Consumer group constants:**
- `GROUP_LLM_WORKER`, `GROUP_TELEGRAM`

**Functions:**
- `publish(redis, stream, data)` -- Publish a dict to a stream
- `create_consumer_group(redis, stream, group)` -- Create consumer group (idempotent)
- `consume(redis, stream, group, consumer, ...)` -- Read messages with blocking support
- `ack(redis, stream, group, message_id)` -- Acknowledge a processed message

## Usage

```python
from shared_lib.config import load_config
from shared_lib.enums import JobType, MemoryStatus
from shared_lib.schemas import MemoryCreate, MemoryResponse
from shared_lib.redis_streams import publish, STREAM_LLM_IMAGE_TAG

settings = load_config()
```

## Dependencies

- `pydantic>=2.0`
- `pydantic-settings>=2.0`
- `redis>=5.0`
