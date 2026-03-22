# BearMemori

Personal memory microservice with LLM-powered triage, semantic search, and human-in-the-loop confirmation. Designed as a drop-in replacement for [teleBearAI](https://github.com/your-repo/teleBearAI)'s memory layer.

## What It Does

BearMemori receives conversations, uses an LLM to decide if anything is worth remembering, and stores confirmed memories for later retrieval. It exposes a REST API that a chatbot (or any client) can call to:

- **Triage** conversations -- LLM evaluates whether a conversation contains memory-worthy information
- **Propose** memory drafts -- pending memories await user confirmation (human-in-the-loop)
- **Confirm or dismiss** drafts -- user decides what gets saved
- **Search** memories semantically via ChromaDB embeddings
- **Retrieve** context -- combines relevant memories with upcoming events into a block that can be injected into an LLM system prompt
- **Manage** memories -- list, get, delete by ID or category

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
  |                                   confirm / dismiss
  |                                        |
  +-- SQLite (relational storage, FTS5 keyword search)
  +-- ChromaDB (vector embeddings, semantic search)
  +-- ReminderScheduler (polls for due events)
  +-- Telegram interface (direct input/notification)
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

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/memory/triage` | POST | Evaluate conversation, propose memory draft |
| `/memory/pending` | POST | Create pending memory directly |
| `/memory/pending/{id}` | DELETE | Dismiss a pending memory |
| `/memory/confirm` | POST | Confirm pending memory to permanent storage |
| `/memory/search` | POST | Semantic search with optional category filter |
| `/memory/retrieve` | GET | Hybrid retrieval (semantic + upcoming events) |
| `/memory/list` | GET | List memories, optional category filter |
| `/memory/events/upcoming` | GET | Upcoming events within day window |
| `/memory/{id}` | GET | Get a single memory |
| `/memory/{id}` | DELETE | Delete a memory |

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

All other settings have defaults. See `.env.example` for the full list.

### Run

```bash
uv run python -m bearmemori
```

This starts:
- The FastAPI server on the configured port (default 8100)
- The Telegram bot (polling mode)
- The reminder scheduler
- The internal processing queue

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
    scheduler.py       # Reminder polling scheduler
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
tests/
  test_api.py          # API endpoint tests
  test_app.py          # Application factory tests
  test_config.py       # Config loading tests
  test_event_bus.py    # Event bus tests
  test_followup.py     # Follow-up manager tests
  test_integration.py  # End-to-end flow tests
  test_llm_client.py   # LLM client tests
  test_models.py       # Model validation tests
  test_pending_store.py # Pending store tests
  test_processor.py    # Processor pipeline tests
  test_queue.py        # Queue manager tests
  test_scheduler.py    # Reminder scheduler tests
  test_storage.py      # SQLite database tests
  test_telegram.py     # Telegram interface tests
  test_triage.py       # Triage subagent tests
  test_vector_store.py # ChromaDB vector store tests
```

## License

TBD
