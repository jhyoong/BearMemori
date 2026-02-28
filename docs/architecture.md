# BearMemori Architecture

## Overview

BearMemori is a personal memory management system built as a set of microservices. Users capture memories, tasks, reminders, and events via Telegram. An LLM processes items asynchronously (image tagging, intent classification, event extraction). All LLM-generated content starts as `pending` -- the user must confirm before it becomes `confirmed`.

```mermaid
graph TD
    TG[Telegram Gateway] -->|HTTP| CORE[Core API - FastAPI<br>SQLite / Redis publish]
    ASST[Assistant Service] -->|HTTP| CORE
    EMAIL[Email Poller - Phase 4] -->|HTTP| CORE
    CORE -->|Redis Streams| LLM[LLM Worker<br>OpenAI API / Core API PATCH]
    LLM -->|Redis notify:telegram| TG
    CORE -->|Redis notify:telegram| TG
```

---

## Key Architectural Decisions

### 1. Core API as Single Source of Truth

All services read from and write to the Core API over HTTP. No service accesses SQLite directly except Core. This keeps data integrity centralized and allows services to evolve independently.

### 2. SQLite with WAL Mode

SQLite was chosen for simplicity (single-user system, no need for a full database server). WAL (Write-Ahead Logging) mode enables concurrent reads while writes are in progress. Foreign keys are enforced at the connection level.

### 3. Redis Streams for Async Job Queuing

Inter-service communication uses Redis Streams with consumer groups. This provides:
- Reliable delivery (messages persist until acknowledged)
- Consumer groups prevent duplicate processing
- Decoupled producers and consumers (Core publishes, LLM Worker consumes)

### 4. Pending-by-Default for LLM Output

All LLM-generated content (tags, intent classifications, extracted events) starts with `pending` status. Users must explicitly confirm before it becomes `confirmed`. This prevents LLM hallucinations from silently corrupting user data.

### 5. Two Separate Telegram Bots

The Telegram Gateway and Assistant Service each run their own bot with a separate token. The gateway handles structured interactions (commands, keyboards, conversation flows). The assistant handles free-form conversation via OpenAI tool-calling.

### 6. Token-Aware Context Management

The Assistant Service tracks token usage with `tiktoken` and automatically summarizes chat history when it exceeds 70% of the available budget. This prevents context window overflow while preserving conversation continuity.

---

## Services

### Core API (`core/core_svc/`)

FastAPI application on port 8000. Manages all domain entities via REST endpoints.

- **Database:** SQLite with aiosqlite, WAL mode, foreign keys enabled
- **Migrations:** Numbered SQL files in `core/migrations/`, applied automatically on startup via `PRAGMA user_version`
- **Audit log:** Every mutation logs entity type, entity ID, action, actor, and optional detail JSON
- **FTS5 search:** Full-text search on memory content and confirmed tags, with stop-word filtering and pin boosting

**Background scheduler** (30-second interval):
1. Fire due reminders and handle recurrence
2. Expire pending memories past their 7-day window
3. Expire suggested tags older than 7 days
4. Re-queue stale pending events (pending > 24 hours)

Each scheduler task is independently error-handled -- one failure does not cascade to others.

### Telegram Gateway (`telegram/tg_gateway/`)

Primary user interface. Receives text and photo messages, manages multi-step conversation flows, and renders inline keyboards.

- **Commands:** `/help`, `/find`, `/tasks`, `/pinned`, `/cancel`
- **Photo handling:** Downloads image, creates pending memory (7-day expiry), queues LLM tagging job
- **Text handling:** Checks for pending conversation state, otherwise queues for LLM intent classification
- **Callback handling:** 9 callback types for interactive keyboards (memory actions, due dates, reminders, tags, intents, search, tasks, delete confirmation, reschedule)
- **Redis consumer:** Listens on `notify:telegram` for LLM results, reminders, and event notifications

### LLM Worker (`llm_worker/worker/`)

Async job processor. Consumes from 5 Redis streams, calls the OpenAI API, persists results to Core API.

**Handlers:**

| Handler | Stream | Purpose |
|---|---|---|
| ImageTagHandler | `llm:image_tag` | Vision model extracts description + tags from images |
| IntentHandler | `llm:intent` | Classifies user message intent (reminder, task, search, note, ambiguous) |
| FollowupHandler | `llm:followup` | Generates clarifying question for ambiguous input |
| TaskMatchHandler | `llm:task_match` | Matches memory content against open tasks (confidence > 0.7) |
| EmailExtractHandler | `llm:email_extract` | Extracts calendar events from email content (confidence > 0.7) |

### Assistant Service (`assistant/assistant_svc/`)

Conversational AI agent using OpenAI tool-calling. Runs a separate Telegram bot.

- **7 tools:** search_memories, get_memory, list_tasks, create_task, list_reminders, create_reminder, list_events
- **Briefing:** Pre-loads upcoming tasks, unfired reminders, and previous session summary into system prompt
- **Daily digest:** Checks every 15 minutes, sends once per user per day at configured hour (respects user timezone)
- **Context management:** Token-counted chat history in Redis (24h TTL), session summaries (7-day TTL)

### Shared Library (`shared/shared_lib/`)

Foundational dependency installed by all other services. Contains no business logic.

- **config.py** -- `Settings` class via Pydantic Settings, `load_config()` function
- **enums.py** -- 9 domain enums (MemoryStatus, TaskState, JobType, etc.)
- **schemas.py** -- 30+ Pydantic models for all API contracts
- **redis_streams.py** -- `publish()`, `consume()`, `ack()`, `create_consumer_group()`, stream/group constants

### Email Poller (`email_poller/poller/`) -- Phase 4

Stub service. When implemented, will poll IMAP accounts, filter/deduplicate emails, and submit to Core API for LLM event extraction.

---

## Message Flow

### Memory Creation (Text)

```mermaid
sequenceDiagram
    participant U as User
    participant TG as Telegram Gateway
    participant C as Core API
    participant R as Redis
    participant LLM as LLM Worker

    U->>TG: Send text message
    TG->>C: POST /memories (status=confirmed)
    TG->>C: POST /llm_jobs (job_type=intent_classify)
    C->>R: Publish to llm:intent stream
    LLM->>R: Consume from llm:intent
    LLM->>LLM: Call OpenAI for classification
    LLM->>C: PATCH job result
    LLM->>R: Publish to notify:telegram
    R->>TG: Consume notification
    alt reminder intent
        TG->>U: Proposal keyboard (confirm / edit time / just a note)
    else task intent
        TG->>U: Proposal keyboard (confirm / edit / just a note)
    else search intent
        TG->>U: Search results with detail buttons
    else general_note intent
        TG->>U: Tag suggestions + task/remind buttons
    else ambiguous intent
        TG->>U: Follow-up question, awaits reply
    end
```

### Memory Creation (Image)

```mermaid
sequenceDiagram
    participant U as User
    participant TG as Telegram Gateway
    participant C as Core API
    participant R as Redis
    participant LLM as LLM Worker
    participant S as Scheduler

    U->>TG: Send photo
    TG->>TG: Download highest-res photo
    TG->>C: POST /memories (status=pending, 7-day expiry)
    TG->>C: Upload image file
    TG->>C: POST /llm_jobs (job_type=image_tag)
    C->>R: Publish to llm:image_tag stream
    LLM->>R: Consume from llm:image_tag
    LLM->>LLM: Read image, base64 encode, call vision model
    LLM->>C: POST suggested tags
    LLM->>R: Publish to notify:telegram
    R->>TG: Consume notification
    TG->>U: Tag suggestion keyboard (confirm all / edit)
    alt User confirms within 7 days
        U->>TG: Confirm tags
        TG->>C: PATCH memory status=confirmed
    else No action in 7 days
        S->>C: Expire pending memory (delete)
    end
```

### Reminder Firing

```mermaid
sequenceDiagram
    participant S as Scheduler (30s interval)
    participant DB as SQLite
    participant R as Redis
    participant TG as Telegram Gateway
    participant U as User

    S->>DB: Query reminders WHERE fired=0 AND fire_at <= NOW
    DB-->>S: Due reminders
    S->>DB: Mark reminder as fired
    opt recurrence_minutes is set
        S->>DB: Create new reminder instance (next fire time)
    end
    S->>R: Publish to notify:telegram
    R->>TG: Consume notification
    TG->>U: Deliver reminder text
```

### Event Confirmation

```mermaid
sequenceDiagram
    participant C as Core API
    participant R as Redis
    participant TG as Telegram Gateway
    participant U as User
    participant S as Scheduler

    C->>R: Event created (status=pending)
    R->>TG: Notification to confirm
    TG->>U: Event confirmation keyboard
    alt User confirms
        U->>TG: Confirm
        TG->>C: PATCH event status=confirmed
        C->>C: Auto-create linked reminder (fire_at = event_time)
    else User rejects
        U->>TG: Reject
        TG->>C: PATCH event status=rejected
    else No response after 24 hours
        S->>R: Re-queue notification (reprompt)
        R->>TG: Deliver reprompt
        TG->>U: Re-send confirmation request
    end
```

### Assistant Conversation

```mermaid
sequenceDiagram
    participant U as User
    participant TG as Assistant Telegram Bot
    participant A as Agent
    participant R as Redis
    participant OAI as OpenAI API
    participant C as Core API

    U->>TG: Send message
    TG->>TG: Verify user_id in allowed list
    TG->>A: Forward message
    A->>R: Load chat history
    A->>C: Build briefing (tasks, reminders)
    R-->>A: Previous session summary
    opt Chat history > 70% of token budget
        A->>OAI: Summarize old history
        A->>R: Store summary, truncate history
    end
    A->>OAI: System prompt + history + message + tool definitions
    loop Tool-calling loop (max 10 iterations)
        alt OpenAI returns tool_calls
            OAI-->>A: tool_calls
            A->>C: Execute tool (e.g. search_memories, create_task)
            C-->>A: Tool result
            A->>OAI: Append results, call again
        else OpenAI returns text
            OAI-->>A: Response text
        end
    end
    A->>R: Save updated chat history (24h TTL)
    A->>TG: Send response
    TG->>U: Deliver reply
```

---

## Error Handling

### LLM Worker Retry Strategy

The worker classifies failures into two categories with distinct retry strategies:

**Invalid Response** (parsing errors, missing fields, logic bugs):
- Exponential backoff: 1s, 2s, 4s, 8s, 16s (capped)
- Max 5 attempts
- After exhaustion: mark job as `failed`, publish `llm_failure` notification, acknowledge message

**Unavailable** (connection errors, timeouts, HTTP 5xx):
- No backoff delay (retried on next consumer cycle)
- Sets `queue_paused` flag until service recovers
- Retries continuously for up to 14 days
- First occurrence: publishes `llm_failure` notification
- After 14 days: mark as `failed`, publish `llm_expiry` notification

**Failure classification:**

| Exception | Classification |
|---|---|
| LLMTimeoutError, asyncio.TimeoutError | UNAVAILABLE |
| ConnectionRefusedError, ConnectionError, OSError | UNAVAILABLE |
| HTTP status >= 500 | UNAVAILABLE |
| json.JSONDecodeError | INVALID_RESPONSE |
| ValueError (missing fields) | INVALID_RESPONSE |
| All other exceptions | INVALID_RESPONSE (default) |

### Message Staleness

The LLM Worker skips messages older than **5 minutes** (parsed from the Redis stream message ID timestamp). This prevents processing outdated jobs after worker restarts. Stale messages are acknowledged and discarded.

### Telegram Flood Control

The gateway consumer applies a **1-second delay** between consecutive messages to the same user. This prevents hitting Telegram's rate limits when multiple notifications arrive in quick succession.

### Core API Health Check

Docker Compose uses `curl -f http://localhost:8000/health` with:
- Interval: 30 seconds
- Timeout: 5 seconds
- Retries: 3
- Start period: 10 seconds

All dependent services wait for `service_healthy` before starting.

### Assistant Error Handling

- Core API connection errors raise `CoreUnavailableError`
- 404 responses raise `CoreNotFoundError`
- Tool execution errors are returned as error dicts to OpenAI (the model decides how to communicate the failure to the user)
- Token budget overflow prevented by automatic summarization at 70% threshold

---

## Data Lifecycle

### Memory Status Flow

```mermaid
stateDiagram-v2
    state "Image Upload Path" as img {
        [*] --> pending: Image uploaded
        pending --> confirmed: User confirms tags
        pending --> expired: No action in 7 days (scheduler deletes)
    }
    state "Text Message Path" as txt {
        [*] --> confirmed_text: Text sent (immediate)
    }
```

### Task State Flow

```mermaid
stateDiagram-v2
    [*] --> NOT_DONE: Created
    NOT_DONE --> DONE: User marks done
    DONE --> NOT_DONE: Recurrence (new task created)
    NOT_DONE --> deleted: User deletes
```

### Reminder Lifecycle

```mermaid
stateDiagram-v2
    [*] --> unfired: Created (fire_at in future)
    unfired --> fired: fire_at reached (scheduler notifies)
    fired --> unfired: Recurrence (new reminder created)
    unfired --> deleted: User deletes
```

### Event Status Flow

```mermaid
stateDiagram-v2
    [*] --> pending: Created
    pending --> confirmed: User confirms (auto-creates linked reminder)
    pending --> rejected: User rejects
    pending --> pending: No response in 24h (scheduler re-prompts)
```

### Tag Status Flow

```mermaid
stateDiagram-v2
    [*] --> suggested: LLM suggests (7-day expiry)
    suggested --> confirmed: User confirms (indexed in FTS5)
    suggested --> expired: No action in 7 days (scheduler deletes)
```

---

## Important Considerations

### Security

- **User allowlisting:** Both Telegram bots restrict access via `ALLOWED_USER_IDS` environment variable. Unauthorized users receive a rejection message.
- **No direct DB access:** Only the Core API touches SQLite. All other services communicate via HTTP.
- **Parameterized queries:** All SQL uses parameterized queries to prevent injection.
- **Tool schema isolation:** The assistant's `owner_user_id` is injected server-side into tool calls, never exposed in OpenAI tool schemas. Users cannot forge ownership.

### Reliability

- **Consumer groups:** Redis consumer groups ensure each message is processed exactly once per group. Unacknowledged messages are redelivered.
- **Independent scheduler tasks:** Each housekeeping task catches its own exceptions. A failure in reminder firing does not block memory expiry.
- **Graceful shutdown:** All services register SIGTERM/SIGINT handlers and clean up connections (close Redis, HTTP clients, cancel async tasks).
- **Restart policy:** Telegram gateway and assistant use `unless-stopped` restart policy in Docker Compose.

### Persistence

- **SQLite WAL mode:** Allows concurrent reads during writes. Single-writer model fits the single-user design.
- **Redis AOF:** Redis runs with `--appendonly yes` for durability. Data survives container restarts.
- **Docker volumes:** `db-data`, `image-data`, and `redis-data` are named volumes that persist across container rebuilds.

### Token Budget Management

The assistant service reserves tokens for three purposes:
- **Briefing:** 5,000 tokens for upcoming tasks, reminders, and session summary
- **Response:** 4,000 tokens reserved for the LLM response
- **Chat history:** Remaining budget (context window minus briefing and response reserves)

When chat history exceeds 70% of its budget, the oldest half is replaced with an LLM-generated summary. The summary is stored in Redis with a 7-day TTL and injected into the next session's briefing.

### Recurrence

Tasks and reminders support recurrence via `recurrence_minutes`. When a recurring item completes (task marked DONE, reminder fired), the system automatically creates a new instance with the next occurrence time. The original is marked as completed/fired.

### FTS5 Search

Full-text search indexes memory content and confirmed tags only. The search module:
- Filters 50+ English stop words
- Wraps each remaining term in double quotes
- Joins terms with OR
- Boosts pinned memories to the top of results
- Uses a metadata cache table (`memories_fts_meta`) for safe FTS5 deletes

---

## Infrastructure

### Docker Compose Services

| Service | Image | Port | Health Check | Depends On |
|---|---|---|---|---|
| core | `core/Dockerfile` | 8000 | `curl /health` (30s interval) | redis |
| telegram | `telegram/Dockerfile` | — | — | core, redis |
| llm-worker | `llm_worker/Dockerfile` | — | — | core, redis |
| assistant | `assistant/Dockerfile` | — | — | core, redis |
| email | `email_poller/Dockerfile` | — | — | core, redis |
| redis | `redis:7-alpine` | — | `redis-cli ping` (10s interval) | — |

### Volumes

| Volume | Purpose |
|---|---|
| `db-data` | SQLite database file (`/data/db/`) |
| `image-data` | Uploaded images (`/data/images/`), shared between core and llm-worker |
| `redis-data` | Redis AOF persistence (`/data`) |

### Redis Streams

| Stream | Producer | Consumer Group | Purpose |
|---|---|---|---|
| `llm:image_tag` | Core API | `llm-worker` | Image tagging jobs |
| `llm:intent` | Core API | `llm-worker` | Intent classification jobs |
| `llm:followup` | Core API | `llm-worker` | Follow-up question jobs |
| `llm:task_match` | Core API | `llm-worker` | Task matching jobs |
| `llm:email_extract` | Core API | `llm-worker` | Email event extraction jobs |
| `notify:telegram` | LLM Worker, Scheduler | `telegram` | Notifications to users |

### Redis Keys (Non-Stream)

| Key Pattern | TTL | Service | Purpose |
|---|---|---|---|
| `assistant:chat:{user_id}` | 24h | Assistant | Chat message history |
| `assistant:summary:{user_id}` | 7 days | Assistant | Session summary |
| `assistant:digest_sent:{user_id}:{date}` | 48h | Assistant | Digest dedup flag |
