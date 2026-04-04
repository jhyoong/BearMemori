# BearMemori

Personal memory microservice with LLM-powered triage, semantic search, and human-in-the-loop confirmation. Designed as a drop-in replacement for [teleBearAI](https://github.com/your-repo/teleBearAI)'s memory layer.

## What It Does

BearMemori receives conversations, uses an LLM to decide if anything is worth remembering, and stores confirmed memories for later retrieval. It exposes a REST API that a chatbot (or any client) can call to:

- **Triage** conversations -- LLM evaluates whether a conversation contains memory-worthy information
- **Propose** memory drafts -- pending memories await user confirmation (human-in-the-loop)
- **Confirm or dismiss** drafts -- user decides what gets saved
- **Search** memories semantically via ChromaDB embeddings
- **Retrieve** context -- combines relevant memories with upcoming events into a block that can be injected into an LLM system prompt
- **Manage** memories -- list, get, edit, delete by ID or category
- **Webapp** -- browse, edit, create, and bulk-manage memories from a browser
- **Review Later** -- save memories that need refinement and review them later via the webapp

## Memory Categories

| Category | Description |
|----------|-------------|
| `profile` | Stable user facts (preferences, identity, relationships) |
| `general` | Non-time-bound information (recommendations, facts) |
| `event` | Time-bound commitments (appointments, deadlines) |
| `location` | Places, addresses, venues |
| `task` | Action items, to-dos |
| `reminder` | Triggered notifications with scheduling |

## Architecture

```
Client (e.g. teleBearAI bot)
  |
  v
FastAPI REST API (:8100)
  |
  +-- Triage subagent (LLM call) --> PendingStore (in-memory, TTL)
  |                                        |
  |                                   confirm / dismiss / review later
  |                                        |
  +-- SQLite (relational storage, FTS5 keyword search)
  +-- ChromaDB (vector embeddings, semantic search)
  +-- ReminderScheduler (polls for due events and fires notifications)
  +-- RecurrenceManager (expands recurring events)
  +-- Telegram interface (direct input/notification)
  +-- Webapp (/webapp/) -- HTMX + Jinja2 memory management UI
  +-- ImageStorage (uploaded media files)
```

### Storage

- **SQLite** -- relational storage with FTS5 full-text search on title, content, and tags. WAL mode for concurrent access.
- **ChromaDB** -- vector embeddings using sentence-transformers (`all-mpnet-base-v2` by default). Persisted to disk.
- **PendingStore** -- in-memory dict with TTL-based expiry for draft memories awaiting user confirmation.

### Internal Components

- **Event Bus** -- pub/sub for loose coupling between components
- **Queue Manager** -- priority queue for processing incoming messages
- **Processor** -- classify/extract pipeline for direct Telegram input
- **Triage Subagent** -- conversation-level LLM evaluation for the REST API
- **Reminder Scheduler** -- polls for due events and fires notifications
- **Recurrence Manager** -- expands recurring events into individual calendar occurrences
- **Cleanup Task** -- periodically removes expired pending memories

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/memory/triage` | POST | Evaluate conversation, propose memory draft |
| `/memory/pending` | POST | Create pending memory directly |
| `/memory/pending/{id}` | DELETE | Dismiss a pending memory |
| `/memory/confirm` | POST | Confirm pending memory to permanent storage |
| `/memory/search` | GET | Semantic search with optional category filter |
| `/memory/retrieve` | GET | Hybrid retrieval (semantic + upcoming events) |
| `/memory/list` | GET | List memories, optional category and `needs_review` filter, supports pagination (`offset`, `limit`) |
| `/memory/recent` | GET | List recently updated memories |
| `/memory/briefing` | GET | Generate a briefing with recent memories, upcoming events, and review queue summary |
| `/memory/events/upcoming` | GET | Upcoming events within day window, supports `start`/`end` params |
| `/memory/events/due` | GET | Events due for reminder delivery |
| `/memory/create` | POST | Create memory directly (bypass LLM extraction), supports `event_fields` |
| `/memory/bulk/delete` | POST | Delete multiple memories by ID list |
| `/memory/bulk/update` | POST | Bulk update fields on multiple memories |
| `/memory/{id}` | GET | Get a single memory |
| `/memory/{id}` | PUT | Update memory fields |
| `/memory/{id}` | DELETE | Delete a memory |
| `/images/{filename}` | GET | Serve a stored image file |

## Setup

### Requirements

- Python 3.12+
- An OpenAI-compatible LLM API (e.g. Ollama, vLLM, or OpenAI)
- A Telegram bot token (for the built-in Telegram interface)

### Install

```bash
git clone <repo-url> && cd BearMemori
uv pip install -e ".[dev]"
```

### Configure

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

Required settings:

| Setting | Description |
|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Your Telegram bot token from BotFather |
| `TELEGRAM_ALLOWED_USER_ID` | Your Telegram user ID (restricts access to one user) |
| `API_PORT` | HTTP API port (default: 8100) |
| `IMAGE_STORAGE_DIR` | Directory for storing uploaded images (default: data/images) |

Optional but recommended:

| Setting | Description |
|---------|-------------|
| `WEBAPP_SECRET` | Shared secret for webapp authentication (empty = webapp disabled) |

All other settings have defaults. See `.env.example` for the full list.

### Run

```bash
uv run python -m bearmemori
```

This starts:
- The FastAPI server on the configured port (default 8100, see `API_PORT`)
- The Telegram bot (polling mode)
- The reminder scheduler
- The internal processing queue
- The pending memory cleanup task

### Run with Docker

```bash
docker build -t bearmemori .
docker run -d \
  --name bearmemori \
  -p 8100:8100 \
  -v bearmemori-data:/data \
  -e TELEGRAM_BOT_TOKEN=your-token \
  -e TELEGRAM_ALLOWED_USER_ID=your-id \
  -e LLM_BASE_URL=http://your-llm-host:11434/v1 \
  bearmemori
```

The `-v bearmemori-data:/data` volume mount persists the SQLite database and ChromaDB vectors across container restarts. The container stores data at `/data` by default (`DATABASE_PATH=/data/bearmemori.db`, `CHROMA_PERSIST_DIR=/data/chroma`).

You can pass any configuration setting as an environment variable with `-e`, or mount a `.env` file:

```bash
docker run -d \
  --name bearmemori \
  -p 8100:8100 \
  -v bearmemori-data:/data \
  --env-file .env \
  bearmemori
```

**Image size note:** The image is large (~4-5 GB) because `sentence-transformers` pulls in PyTorch. If size is a concern, consider running the embedding model as a separate service and pointing to it instead.

### Enable the Webapp

The webapp provides a browser-based UI for managing memories. To enable it, set the `WEBAPP_SECRET` environment variable:

```bash
# In your .env file
WEBAPP_SECRET=your-secret-here
```

Once set, the webapp is available at `http://localhost:8100/webapp/login`. Enter the secret to log in.

**Webapp pages:**

| Page | Path | Description |
|------|------|-------------|
| Login | `/webapp/login` | Enter shared secret to authenticate |
| Memories | `/webapp/memories` | Browse all memories with search, category filter, bulk actions, and event datetime/status display |
| New Memory | `/webapp/memories/new` | Create a memory directly (no LLM processing) |
| Edit Memory | `/webapp/memories/{id}` | Edit title, content, category, tags, review flag, and event fields (datetime, status, recurrence) |
| Review Queue | `/webapp/review` | View memories marked "Review Later", approve or delete in bulk |
| Calendar | `/webapp/calendar` | View upcoming events and recurring occurrences in calendar format |

The webapp uses HTMX for interactivity -- filtering, bulk actions, and inline deletes work without full page reloads. Auth is cookie-based with httponly and samesite-strict flags.

If `WEBAPP_SECRET` is empty or unset, the webapp is not mounted and no `/webapp/` routes exist.

### Run Tests

```bash
uv run pytest -v
```

## Integration with teleBearAI

BearMemori is a drop-in replacement for teleBearAI's memory service. To switch:

1. Run BearMemori as a service (standalone or via Docker, see [Run with Docker](#run-with-docker))
2. In teleBearAI's `.env`, set:
   ```
   MEMORY_SERVICE_URL=http://localhost:8100
   ```
3. No other changes needed -- the API contract matches.

## Project Structure

```
bearmemori/
  __main__.py          # Entry point
  app.py               # Application factory and wiring
  config.py            # Settings (pydantic-settings, loaded from .env)
  api/
    routes.py          # FastAPI endpoints
    schemas.py         # Request/response models
  core/
    processor.py       # Classify/extract pipeline (Telegram input)
    triage.py          # Conversation triage subagent (API input)
    queue.py           # Priority queue manager
    followup.py        # Follow-up conversation tracking
    confirm.py         # Confirm/discard handler for pending memories
    scheduler.py       # Reminder polling scheduler
    cleanup.py         # Pending memory auto-cleanup
    recurrence.py      # Recurring event expansion (RRULE parsing)
    models.py          # QueueItem model
  events/
    bus.py             # Event bus (pub/sub)
    types.py           # Base Event class
    domain.py          # Domain event types
  interfaces/
    telegram.py        # Telegram bot handler
  llm/
    client.py          # OpenAI-compatible LLM client
    parsing.py         # JSON extraction from LLM responses
  storage/
    database.py        # SQLite + FTS5
    vector_store.py    # ChromaDB wrapper
    pending_store.py   # In-memory pending store with TTL
    models.py          # MemoryRecord, MemoryDraft, MemoryCategory, etc.
  utils/
    time.py            # UTC datetime normalization helpers
  webapp/
    auth.py            # Shared-secret auth middleware
    router.py          # Webapp routes (login, CRUD, bulk, review queue)
    templates/         # Jinja2 templates (base, memories, detail, create, review, partials)
    static/            # CSS overrides
tests/
  test_api.py          # API endpoint tests
  test_app.py          # Application factory tests
  test_cleanup.py      # Pending cleanup tests
  test_config.py       # Config loading tests
  test_config_timezone.py # Config timezone tests
  test_confirm.py      # Confirm handler tests
  test_event_bus.py    # Event bus tests
  test_followup.py     # Follow-up manager tests
  test_integration.py  # End-to-end flow tests
  test_llm_client.py   # LLM client tests
  test_models.py       # Model validation tests
  test_pending_store.py # Pending store tests
  test_processor.py    # Processor pipeline tests
  test_queue.py        # Queue manager tests
  test_routes_triage_time.py # Triage time handling tests
  test_scheduler.py    # Reminder scheduler tests
  test_storage.py      # SQLite database tests
  test_telegram.py     # Telegram interface tests
  test_triage.py       # Triage subagent tests
  test_triage_schema.py # Triage schema validation tests
  test_triage_time.py  # Triage time zone tests
  test_vector_store.py # ChromaDB vector store tests
  test_webapp.py       # Webapp route and CRUD tests
  test_webapp_auth.py  # Webapp auth middleware tests
  api/
    test_routes.py     # API route tests
  core/
    test_recurrence.py # Recurrence expansion tests
    test_scheduler_recurring.py # Scheduler recurring event tests
  storage/
    test_database_calendar.py # Calendar/database tests
```

## Version

Current version: 0.3.9

## License

TBD
