# Phase 2 - Group 1: Package Setup and Configuration

## Goal

Create the Telegram Gateway Python package with all dependencies and configuration loading. This is the foundation every other Phase 2 group builds on.

**Depends on:** Phase 1 complete (shared package, Core service, Redis, Docker Compose base)
**Blocks:** All other Phase 2 groups

---

## Context

The Telegram Gateway is one of four custom services in the Life Organiser architecture. It is the user-facing Telegram bot that communicates with the Core service via REST API and with the LLM Worker via Redis Streams. The service lives at `telegram/` in the monorepo with the Python package at `telegram/tg_gateway/`.

The shared package (`shared/`) already exists from Phase 1 and provides:
- `shared.schemas` -- Pydantic models (MemoryCreate, TaskCreate, ReminderCreate, etc.)
- `shared.enums` -- MemoryStatus, TaskState, JobType, etc.
- `shared.redis_streams` -- Stream name constants, publish/consume helpers
- `shared.config` -- Config loading utilities

---

## Files to Create

### `telegram/pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "life-organiser-telegram"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "python-telegram-bot[ext]>=20.0,<23.0",
    "httpx>=0.27",
    "redis>=5.0",
    "aiofiles>=24.0",
    "life-organiser-shared",
]
```

Dependency rationale:
- `python-telegram-bot[ext]` -- v20+ async API. The `[ext]` extra includes `Application`, `ConversationHandler`, `JobQueue`, and all handler classes.
- `httpx` -- async HTTP client for calling Core REST API.
- `redis` -- async Redis client for publishing to and consuming from Redis Streams.
- `aiofiles` -- async file I/O for image handling.
- `life-organiser-shared` -- the shared package from Phase 1 (installed as editable dep in Docker).

### `telegram/tg_gateway/__init__.py`

Empty file. Package marker.

### `telegram/tg_gateway/config.py`

Telegram-specific configuration using `pydantic-settings`. Loads from environment variables.

Fields:
- `telegram_bot_token: str` -- the Telegram Bot API token (required, no default)
- `allowed_user_ids: str = ""` -- comma-separated list of allowed Telegram user IDs
- `core_api_url: str = "http://core:8000"` -- URL for the Core REST API
- `redis_url: str = "redis://redis:6379"` -- Redis connection URL

Property:
- `allowed_ids_set -> set[int]` -- parses the comma-separated `allowed_user_ids` string into a set of integers. Returns empty set if string is empty.

Use `pydantic_settings.BaseSettings` with no env prefix (env vars match field names directly).

---

## Acceptance Criteria

1. `pip install -e ./telegram` succeeds with all dependencies resolved (assuming shared package is available)
2. `from tg_gateway.config import TelegramConfig` works
3. `TelegramConfig` loads `telegram_bot_token` from `TELEGRAM_BOT_TOKEN` env var
4. `allowed_ids_set` correctly parses `"123,456"` into `{123, 456}`
5. `allowed_ids_set` returns empty set when `allowed_user_ids` is `""`
