# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BearMemori is a personal memory management system with a microservice architecture. Users capture memories, tasks, reminders, and events via a Telegram bot. An LLM (via the OpenAI API) processes items asynchronously (image tagging, intent classification). All LLM-generated content starts as `pending` status — the user must confirm before it becomes `confirmed`.

**Services (each service's Python package lives in a uniquely-named subdirectory):**
- `core/core_svc/` — FastAPI REST API (port 8000), fully implemented
- `shared/shared_lib/` — Pydantic models, enums, config, Redis stream utilities (installed as a dependency by other services)
- `telegram/tg_gateway/` — Telegram bot gateway, substantially implemented (~95%)
- `llm_worker/worker/` — LLM processing worker, fully implemented (consumer loop, all 5 handlers, clients, retry, `main.py`)
- `assistant/assistant_svc/` — Conversational AI assistant with OpenAI tool-calling, fully implemented (agent, tools, briefing, digest scheduler, Telegram interface)
- `email_poller/poller/` — Email polling service (stub, Phase 4 scope)

## Commands

All commands run from the repo root unless stated otherwise.

```bash
# Run the full stack
docker-compose up --build

# Run core service locally (from core/)
cd core && hatch run uvicorn core_svc.main:app --host 0.0.0.0 --port 8000

# Install a service's dependencies (run inside that service's directory)
pip install -e .
# or
poetry install

# Run all tests
pytest

# Run a single test file
pytest tests/test_core/test_memories.py

# Run a single test
pytest tests/test_core/test_memories.py::TestMemories::test_create_memory

# Run tests matching a pattern
pytest -k "test_create_memory"

# Run with coverage
pytest --cov=. --cov-report=term-missing

# Lint / type check (if installed)
ruff check .
mypy .
```

## Architecture

### Data Flow

```
User (Telegram) -> telegram gateway -> core API -> SQLite (aiosqlite)
                                                 -> Redis streams -> llm_worker
User (Telegram) -> assistant bot -> core API (read/write via HTTP)
                                 -> OpenAI API (tool-calling)
                                 -> Redis (chat history, session summaries)
email_poller -> core API (events endpoint)
```

The `core` service is the central source of truth. Other services communicate with it via HTTP or Redis streams.

### Database

SQLite with WAL mode, foreign keys enabled, and FTS5 for full-text search. Schema is managed via numbered migration files in `core/migrations/` (e.g., `001_initial.sql`, `007_...sql`). The migration runner tracks applied versions in `schema_version`.

**Adding a migration:**
1. Create `core/migrations/NNN_description.sql` where NNN increments from the current highest
2. Update the `SCHEMA_VERSION` constant in `core/core_svc/database.py`
3. Test idempotency (running the migration twice must not fail)

### Core API Routers (`core/core_svc/routers/`)

Each router handles one domain. The pattern is consistent across all:
- Endpoint validates request via Pydantic schema from `shared/shared_lib/schemas.py`
- DB operations use parameterized async queries via `aiosqlite`
- Writes are committed explicitly with `await conn.commit()`
- Audit log entries are written for all mutations

**Adding a new endpoint:**
1. Create `core/core_svc/routers/<name>.py`
2. Register it in `core/core_svc/main.py` with `app.include_router(...)`
3. Add tests in `tests/test_core/test_<name>.py`

### Shared Package

`shared/` must be installed before `core/` or any other service. It provides:
- `shared_lib.config` — `load_config()` returns a `Settings` instance (Pydantic Settings, env var overrides)
- `shared_lib.enums` — all enums (`MemoryStatus`, `TaskState`, `JobStatus`, etc.)
- `shared_lib.schemas` — all Pydantic request/response models
- `shared_lib.redis_streams` — Redis stream helpers for async job queuing

### LLM Job Pattern

When the core API needs LLM processing (e.g., auto-tagging an image), it inserts a row into the `llm_jobs` table with `status=pending` and a JSON payload. The `llm_worker` reads from Redis streams, calls the LLM via the OpenAI API, then PATCHes the job result back to core. The affected entity stays in `pending` status until a user action confirms it.

### LLM Worker Architecture (`llm_worker/worker/`)

Key modules:
- `consumer.py` — main async loop; reads Redis streams via consumer groups, dispatches to handlers, publishes results to `notify:telegram`, handles retries and graceful shutdown
- `handlers/` — one handler per job type (`image_tag`, `intent`, `task_match`, `followup`, `email_extract`); each inherits `BaseHandler` with `async handle(job_id, payload, user_id) → dict | None`
- `core_api_client.py` — async HTTP client (aiohttp) for calling the core REST API
- `llm_client.py` — async OpenAI-compatible client; `complete()` for text, `complete_with_image()` for vision
- `retry.py` — `RetryTracker`: in-memory per-message attempt counter with exponential backoff (`min(2^(attempts-1), 60)` seconds), max 3 retries by default
- `utils.py` — `extract_json()`: extracts JSON from LLM responses that may include markdown fences or surrounding text
- `prompts.py` — all LLM prompt strings

Stream → handler mapping (defined in `consumer.py`):
- `llm:image_tag` → `ImageTagHandler`
- `llm:intent` → `IntentHandler`
- `llm:followup` → `FollowupHandler`
- `llm:task_match` → `TaskMatchHandler`
- `llm:email_extract` → `EmailExtractHandler`

`main.py` is fully implemented: wires up config loading, Redis client, aiohttp session, `LLMClient`, `CoreAPIClient`, handler instances, signal handlers (SIGTERM/SIGINT), and calls `run_consumer()`.

### Assistant Service Architecture (`assistant/assistant_svc/`)

A conversational AI assistant that uses OpenAI tool-calling to help users interact with their BearMemori data. Runs as a separate Telegram bot with its own token.

Key modules:
- `agent.py` — core agent loop: builds system prompt with briefing, calls OpenAI with tool definitions, executes tool calls in a loop (max 10 iterations), manages summarize-and-truncate for chat history
- `briefing.py` — builds pre-loaded context for each request: upcoming tasks (NOT_DONE, 7 days), upcoming reminders (unfired, 48h), previous session summary. Trimmed to a token budget.
- `context.py` — manages chat history in Redis with token counting (tiktoken). Triggers summarization when history exceeds 70% of the chat budget. Stores session summaries (7-day TTL) and chat messages (24h TTL).
- `core_client.py` — async HTTP client (httpx) for Core API. Methods: `search_memories`, `get_memory`, `list_tasks`, `list_reminders`, `list_events`, `create_task`, `create_reminder`, `get_settings`.
- `tools/` — tool registry + 7 tool definitions (search_memories, get_memory, list_tasks, create_task, list_reminders, create_reminder, list_events). Each tool is an async function with an OpenAI function schema. `owner_user_id` is injected by the agent, not exposed in tool schemas.
- `interfaces/base.py` — abstract `BaseInterface` (send_message, start, stop). `interfaces/telegram.py` — Telegram implementation using python-telegram-bot.
- `digest.py` — daily morning briefing scheduler. Checks every 15 minutes, sends once per user per day (deduped via Redis key with 48h TTL). Respects user timezone from Core API settings.
- `config.py` — `AssistantConfig(BaseSettings)` with env var overrides. Key settings: `ASSISTANT_TELEGRAM_BOT_TOKEN`, `ASSISTANT_ALLOWED_USER_IDS` (comma-separated), `OPENAI_API_KEY`, `OPENAI_MODEL`, token budget settings.
- `main.py` — wires all components, registers SIGTERM/SIGINT handlers, starts Telegram polling and digest scheduler concurrently.

**Adding a new tool:**
1. Create or edit a file in `assistant/assistant_svc/tools/`
2. Define an async function taking `client` + keyword args (including `owner_user_id`)
3. Define an OpenAI tool schema dict (name, description, parameters — exclude `owner_user_id`)
4. Register in `assistant/assistant_svc/main.py` via `tool_registry.register()`

Redis keys used:
- `assistant:chat:{user_id}` — chat message history (JSON list, 24h TTL)
- `assistant:summary:{user_id}` — last session summary (string, 7-day TTL)
- `assistant:digest_sent:{user_id}:{date}` — digest dedup flag (48h TTL)

### Test Fixtures

`tests/conftest.py` (core tests):
- `test_db` — temporary SQLite with all migrations applied (session-scoped)
- `mock_redis` — `fakeredis.aioredis` instance (no real Redis needed)
- `test_app` — `AsyncClient` with the FastAPI app wired to `test_db` and `mock_redis`
- `test_user` — pre-inserted user with `telegram_user_id=12345`
- Also injects `llm_worker/` and `assistant/` into `sys.path` for imports

`tests/test_llm_worker/test_consumer.py` (llm_worker tests):
- Fixtures are defined in the test file itself, not in a conftest
- Uses `AsyncMock` for `CoreAPIClient` and handlers; `fakeredis.aioredis` for Redis

`tests/test_assistant/conftest.py` (assistant tests):
- `mock_redis` — `fakeredis.aioredis` instance
- Tests mock the OpenAI client and Core API client; use real `ContextManager`, `BriefingBuilder`, `ToolRegistry` where possible

## Code Conventions

- Async throughout: `async def`, `await` for all DB, Redis, and HTTP calls
- Type hints on all function signatures; use `Optional[T]`, `list[T]`, `dict[K, V]`
- Max line length: 100 characters; double quotes for strings; f-strings for formatting
- Logger per module: `logger = logging.getLogger(__name__)`
- Imports ordered: stdlib → third-party → first-party, alphabetically within groups
