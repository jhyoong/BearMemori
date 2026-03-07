# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-03-01

### Added

- **Admin API endpoints** (`core/core_svc/routers/admin.py`):
  - `GET /admin/queue-stats` - LLM job queue statistics (counts by status/type, oldest job age)
  - `GET /admin/health` - System health check (database and Redis connectivity)
  - `GET /admin/stream-health` - Redis stream introspection (stream lengths, pending counts, consumer info)
  - `GET /admin/llm-health` - Read LLM worker health status from Redis cache

- **LLM Worker health monitoring** (`llm_worker/worker/health_check.py`): Module for publishing health status to Redis

- **Telegram /timezone command** (`telegram/tg_gateway/handlers/command.py`):
  - View current timezone with `/timezone`
  - Set timezone using UTC offset (`/timezone +8`) or IANA name (`/timezone Asia/Tokyo`)
  - Timezone helper utilities in `telegram/tg_gateway/tz_utils.py`

- **Architecture documentation** (`docs/architecture.md`): System architecture with Mermaid diagrams, design decisions, error handling, data lifecycle

- **Service README files**: Individual documentation for core, telegram, llm_worker, assistant, email_poller, and shared services

### Changed

- **Core API**: Refined timezone handling in conversation handlers and callback processing
- **Telegram Gateway**: Fixed button interaction handling for image memories
- **Settings model**: Fixed to ignore extra environment variables
- **Linting**: Fixed all ruff lint errors, added `ruff.toml` configuration

### Fixed

- Memory result handling bug
- Telegram button interaction issues on images
- Timeout-related issues

---

## [0.1.0] - 2026-02-28

Initial release of BearMemori, a personal memory management system.

### Added

- **Core API** (`core/core_svc/`): FastAPI REST API with routers for memories, tasks, reminders, events, search, settings, backup, audit, and LLM jobs.
- **Shared Library** (`shared/shared_lib/`): Pydantic models, enums, configuration (Pydantic Settings with env var overrides), and Redis stream utilities.
- **Telegram Gateway** (`telegram/tg_gateway/`): Telegram bot for capturing memories, managing tasks and reminders, confirming LLM-generated content.
- **LLM Worker** (`llm_worker/worker/`): Async consumer that reads Redis streams and dispatches to 5 handlers (image tagging, intent classification, task matching, follow-up generation, email extraction) via the OpenAI API.
- **Assistant Service** (`assistant/assistant_svc/`): Conversational AI assistant using OpenAI tool-calling with 7 tools, chat history management with token counting, session summarization, daily digest scheduler, and briefing builder.
- **Email Poller** (`email_poller/poller/`): Stub service for future email-based event ingestion.
- **Database**: SQLite with WAL mode, foreign keys, FTS5 full-text search, and a numbered migration system (`core/migrations/`).
- **Docker Compose**: Full-stack deployment with Core API, Telegram Gateway, LLM Worker, Assistant, Email Poller, and Redis.
- **Test suite**: pytest with pytest-asyncio, fakeredis, in-memory SQLite. Tests for core API, LLM worker, and assistant service.

[0.1.1]: https://github.com/jhyoong/BearMemori/releases/tag/v0.1.1

[0.1.0]: https://github.com/jhyoong/BearMemori/releases/tag/v0.1.0
