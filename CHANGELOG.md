# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.3] - 2026-03-22

### Added

- **Webapp for memory management**: HTMX + Jinja2 + Pico CSS webapp served at `/webapp/` for browsing, editing, creating, and deleting memories
  - Memory list with search, category filter, and bulk actions (delete, clear review flag)
  - Memory detail/edit page with all fields including `needs_review`
  - Create memory form (bypasses LLM, saves directly)
  - Review queue page pre-filtered to `needs_review=True` memories with bulk approve/delete
- **Webapp auth**: Shared-secret authentication via `WEBAPP_SECRET` env var with cookie-based sessions, HMAC-verified tokens, and httponly/samesite-strict cookies
- **Review Later workflow**: `needs_review` boolean field on `MemoryRecord` and `memories` table with auto-migration for existing databases
- **Telegram "Review Later" button**: New inline keyboard button saves memories with `needs_review=True` for later refinement in the webapp
- **New API endpoints**: `PUT /memory/{id}` (update), `POST /memory/create` (direct create), `POST /memory/bulk/delete`, `POST /memory/bulk/update` with field allowlist
- **`needs_review` filter**: `GET /memory/list` accepts `needs_review` query parameter
- **Database bulk operations**: `delete_many()` on both `MemoryDatabase` and `VectorStore`, `update()` on `VectorStore`
- **`WEBAPP_SECRET` config setting**: Empty string disables webapp; any value enables it with auth

### Changed

- **LLM classification prompt**: Biased toward storing memories over requesting follow-ups; only asks for clarification when input is truly unintelligible
- **`MemoryConfirmed` event**: Now carries `needs_review` field (default `False`), passed through by `ConfirmHandler`

### Fixed

- **Bulk update field allowlist**: Only `title`, `content`, `category`, `tags`, and `needs_review` can be set via bulk update (prevents mutation of `id`, `created_at`, etc.)
- **Webapp route ordering**: Parameterized `{record_id}` routes registered after static routes (`/new`, `/bulk/*`) to prevent ambiguous matching
- **`delete_many` empty list guard**: `MemoryDatabase.delete_many([])` returns 0 instead of producing invalid SQL
- **Auth cookie `secure` flag**: `WebappAuthMiddleware` accepts `secure_cookie` parameter for HTTPS deployments
- **Test isolation**: Webapp mount tests in `test_app.py` now patch `VectorStore` (consistent with all other tests)
- **Fixture deduplication**: Removed duplicate webapp fixtures from `conftest.py` (already defined in `test_webapp.py`)

---

## [0.3.2] - 2026-03-22

### Added

- **Human-in-the-loop confirmation flow**: Inline keyboard UI for memory confirmation/discardal with callback handling
- **Pending memory auto-cleanup**: `PendingCleanupTask` automatically discards expired pending memories after TTL
- **LLM vision support**: `describe_image` method in LLM client for photo analysis
- **Memory events**: `MemoryPending`, `MemoryConfirmed`, `MemoryDiscarded` domain events
- **Edit flow handling**: Processor handles correction/edit submissions, re-extracts memory with updated content

### Changed

- **Pending TTL**: Default updated to 30 minutes with configurable cleanup interval

---

## [0.3.0] - 2026-03-22

Complete rewrite from multi-service architecture to an event-driven modular monolith. Single Python process replaces the previous Core API + Telegram Gateway + LLM Worker + Assistant + Redis stack.

### Added

- **Event-driven architecture**: Async event bus with pub/sub for loose coupling between modules
- **Memory categories**: Profile, general, event, location, task, and reminder categories with structured event fields
- **ChromaDB vector store**: Semantic search using sentence-transformers (`all-mpnet-base-v2`) embeddings
- **SQLite + FTS5**: Relational storage with full-text search on title, content, and tags
- **Human-in-the-loop (HITL) confirmation**: Pending memory store with TTL-based expiry for draft memories awaiting user confirmation
- **Triage subagent**: LLM-powered conversation evaluation for the REST API, proposes memory drafts from conversations
- **Reminder scheduler**: Polls for due events and fires notifications with recurring support
- **Follow-up manager**: Tracks multi-turn conversations until the LLM has enough context
- **Priority queue**: In-memory queue with priority system for sequential LLM processing
- **REST API**: FastAPI endpoints for triage, search, retrieval, and memory CRUD
- **Telegram interface**: Direct text and photo input with event-driven notification delivery
- **Docker support**: Multi-stage Dockerfile with `uv` for fast builds, `.dockerignore` for clean images
- **LLM response parsing**: Handles Qwen3 `<think>` blocks, markdown code fences, and loose JSON extraction
- **Robust LLM prompts**: `/no_think` directive and stronger JSON-only instructions for local LLM compatibility

### Changed

- **Architecture**: Replaced multi-service Docker Compose stack (Core API, Telegram Gateway, LLM Worker, Assistant, Redis) with a single async Python process
- **Storage**: Replaced Redis streams with in-memory event bus; kept SQLite, added ChromaDB
- **Embedding model**: Changed default from `all-MiniLM-L6-v2` to `all-mpnet-base-v2`
- **LLM client**: Now uses OpenAI-compatible API via `openai` SDK, targeting local LLM endpoints
- **Configuration**: Simplified to a single `.env` file with `pydantic-settings`
- **Dependencies**: Managed with `uv` instead of Poetry/pip

### Removed

- Redis dependency and all Redis stream infrastructure
- Separate Core API, Telegram Gateway, LLM Worker, Assistant, and Email Poller services
- Docker Compose multi-service deployment
- Migration system (single-process SQLite with auto-schema creation)
- Poetry lock files and per-service pyproject.toml files

---

## [0.1.1] - 2026-03-01

### Added

- Admin API endpoints for queue stats, health checks, stream health, and LLM health
- LLM Worker health monitoring via Redis
- Telegram /timezone command with UTC offset and IANA timezone support
- Architecture documentation with Mermaid diagrams
- Service README files

### Changed

- Refined timezone handling in conversation handlers and callback processing
- Fixed Telegram button interaction handling for image memories
- Fixed Settings model to ignore extra environment variables

### Fixed

- Memory result handling bug
- Telegram button interaction issues on images
- Timeout-related issues

---

## [0.1.0] - 2026-02-28

Initial release of BearMemori, a personal memory management system.

### Added

- Core API with FastAPI REST endpoints
- Telegram Gateway for capturing memories and managing tasks
- LLM Worker with async Redis stream consumer and 5 handlers
- Assistant Service with OpenAI tool-calling and daily digest
- SQLite with WAL mode, FTS5, and numbered migration system
- Docker Compose full-stack deployment
- Test suite with pytest and pytest-asyncio

[0.3.3]: https://github.com/jhyoong/BearMemori/releases/tag/v0.3.3
[0.3.2]: https://github.com/jhyoong/BearMemori/releases/tag/v0.3.2
[0.3.0]: https://github.com/jhyoong/BearMemori/releases/tag/v0.3.0
[0.1.1]: https://github.com/jhyoong/BearMemori/releases/tag/v0.1.1
[0.1.0]: https://github.com/jhyoong/BearMemori/releases/tag/v0.1.0
