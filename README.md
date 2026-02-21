# BearMemori

> [!NOTE]                                                                                                                                                                                      
> An ambitious personal project for my personal use. I'm building this with the aim of storing and managing memories with the help of AI. 

A personal memory management system built with a microservice architecture. Capture memories, tasks, reminders, and events via a Telegram bot. An LLM (via the OpenAI API) processes items asynchronously (image tagging, intent classification). All LLM-generated content starts as `pending` until the user confirms it.

## Architecture

```
User (Telegram) -> Telegram Gateway -> Core API -> SQLite (aiosqlite)
                                                 -> Redis Streams -> LLM Worker
Email Poller -> Core API (events endpoint)
```

The **Core API** is the central source of truth. Other services communicate with it via HTTP or Redis streams.

### Services

Each service lives in its own directory with its own Python package:

| Service | Directory | Description | Status |
|---------|-----------|-------------|--------|
| **Core API** | `core/core_svc/` | FastAPI REST API (port 8000) | Implemented |
| **Shared Library** | `shared/shared_lib/` | Pydantic models, enums, config, Redis stream utilities | Implemented |
| **Telegram Gateway** | `telegram/tg_gateway/` | Telegram bot interface | Stub |
| **LLM Worker** | `llm_worker/worker/` | Async LLM processing via OpenAI API | Stub |
| **Email Poller** | `email_poller/poller/` | Email polling for calendar events | Stub |

### Core API Endpoints

The Core API exposes routers for: memories, tasks, reminders, events, search, settings, backup, audit, and LLM jobs.

### Database

SQLite with WAL mode, foreign keys enabled, and FTS5 for full-text search. Schema is managed via numbered migration files in `core/migrations/`. The migration runner tracks applied versions in a `schema_version` table.

### LLM Job Pattern

When the Core API needs LLM processing (e.g., auto-tagging an image), it inserts a row into the `llm_jobs` table with `status=pending` and a JSON payload. The LLM Worker reads from Redis streams, calls the LLM via the OpenAI API, then PATCHes the result back to the Core API. The affected entity stays in `pending` status until the user confirms it.

## Prerequisites

- Python 3.11+
- Docker and Docker Compose (for full stack)
- Redis (provided via Docker, or install locally)

## Getting Started

### Run the full stack with Docker

```bash
docker-compose up --build
```

This starts all services: Core API, Telegram Gateway, LLM Worker, Email Poller, and Redis.

### Run the Core API locally

Install the shared library first (required dependency):

```bash
cd shared && pip install -e .
```

Then install and run the Core API:

```bash
cd core && pip install -e .
hatch run uvicorn core_svc.main:app --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`. A health check endpoint is at `/health`.

## Testing

Tests use an in-memory SQLite database with all migrations applied and a `fakeredis` instance (no real Redis needed).

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_core/test_memories.py

# Run a single test
pytest tests/test_core/test_memories.py::TestMemories::test_create_memory

# Run tests matching a pattern
pytest -k "test_create_memory"

# Run with coverage
pytest --cov=. --cov-report=term-missing
```

## Linting and Type Checking

```bash
ruff check .
mypy .
```

## Configuration

Configuration is managed via environment variables, loaded through Pydantic Settings in `shared_lib.config`. Copy `.env.example` to `.env` (if available) and set the required values. When running with Docker Compose, the `.env` file is automatically loaded by all services.
