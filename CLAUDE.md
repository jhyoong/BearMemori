# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BearMemori is a personal memory management system with a microservice architecture. Users capture memories, tasks, reminders, and events via a Telegram bot. An LLM (via the OpenAI API) processes items asynchronously (image tagging, intent classification). All LLM-generated content starts as `pending` status — the user must confirm before it becomes `confirmed`.

**Services (each service's Python package lives in a uniquely-named subdirectory):**
- `core/core_svc/` — FastAPI REST API (port 8000), fully implemented
- `shared/shared_lib/` — Pydantic models, enums, config, Redis stream utilities (installed as a dependency by other services)
- `telegram/tg_gateway/` — Telegram bot gateway, substantially implemented (~95%)
- `llm_worker/worker/` — LLM processing worker, fully implemented (consumer loop, all 5 handlers, clients, retry, `main.py`)
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

### Test Fixtures

`tests/conftest.py` (core tests):
- `test_db` — temporary SQLite with all migrations applied (session-scoped)
- `mock_redis` — `fakeredis.aioredis` instance (no real Redis needed)
- `test_app` — `AsyncClient` with the FastAPI app wired to `test_db` and `mock_redis`
- `test_user` — pre-inserted user with `telegram_user_id=12345`

`tests/test_llm_worker/test_consumer.py` (llm_worker tests):
- Fixtures are defined in the test file itself, not in a conftest
- Uses `AsyncMock` for `CoreAPIClient` and handlers; `fakeredis.aioredis` for Redis
- `tests/conftest.py` injects `llm_worker/` into `sys.path` so `from worker.xxx` imports work

## Code Conventions

- Async throughout: `async def`, `await` for all DB, Redis, and HTTP calls
- Type hints on all function signatures; use `Optional[T]`, `list[T]`, `dict[K, V]`
- Max line length: 100 characters; double quotes for strings; f-strings for formatting
- Logger per module: `logger = logging.getLogger(__name__)`
- Imports ordered: stdlib → third-party → first-party, alphabetically within groups
