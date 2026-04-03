# AGENTS.md - BearMemori Developer Guide

This file contains guidelines for agentic coding agents working in the BearMemori repository.

## Project Overview

BearMemori is a personal memory store with LLM processing. It's an event-driven modular monolith:
- Single Python process with async event bus
- Sequential LLM processing (endpoint is bottleneck)
- Local embedding model (sentence-transformers)
- SQLite + FTS5 for structured storage, ChromaDB for vectors
- Telegram bot interface + FastAPI REST API + HTMX webapp

## Build/Lint/Test Commands

### Install Dependencies
```bash
uv sync                     # Install dependencies
uv sync --extra dev       # Install with dev dependencies
```

### Run the Application
```bash
uv run python -m bearmemori  # Run the app (via __main__.py)
```

### Run Tests
```bash
uv run pytest                    # Run all tests
uv run pytest tests/             # Run all tests in directory
uv run pytest -x               # Stop on first failure
uv run pytest -v                # Verbose output
uv run pytest -k "test_name"   # Run tests matching pattern
uv run pytest tests/test_file.py::test_function_name  # Run single test
uv run pytest tests/test_file.py::TestClass::test_method  # Run specific test method
```

### Linting and Formatting
```bash
uv run ruff check .          # Lint all files
uv run ruff check . --fix      # Auto-fix lint issues
uv run ruff format .            # Format all files
uv run ruff check bearmeori/    # Lint specific package
```

### Combined (check before committing)
```bash
uv run ruff check . && uv run ruff format . && uv run pytest
```

## Code Style Guidelines

### General Rules
- Python 3.12+ required
- Use `uv` for package management
- Follow event-driven architecture: modules communicate via events, not direct imports
- Line length: 100 characters (configured in ruff.toml)

### Imports
- Standard library first, then third-party, then local
- Use explicit relative imports for intra-package imports
- Example:
  ```python
  import logging
  from pathlib import Path
  
  from fastapi import FastAPI
  
  from bearmemori.config import Settings
  from bearmemori.events.bus import EventBus
  ```

### Type Annotations
- Use Python 3.12+ syntax (PEP 695): `def foo(x: int) -> str:`
- Use `X | None` instead of `Optional[X]`
- Use `X | Y` instead of union syntax
- Example:
  ```python
  def get(self, record_id: str) -> MemoryRecord | None:
      ...
  ```

### Naming Conventions
- Classes: `PascalCase` (e.g., `MemoryDatabase`, `EventBus`)
- Functions/methods: `snake_case` (e.g., `get_record`, `handle_input`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_TIMEOUT`)
- Private methods: prefix with underscore (e.g., `_internal_method`)
- Type variables: `PascalCase` with `T` suffix (e.g., `MemoryT`)

### Error Handling
- Use exceptions for exceptional cases, not control flow
- Raise specific exceptions with clear messages
- Example:
  ```python
  if not record_id:
      raise ValueError("record_id cannot be empty")
  ```
- Avoid bare `except:` clauses; catch specific exceptions
- Use try/except for operations that may legitimately fail (file I/O, network)

### Pydantic Models
- Use `pydantic-settings` for configuration via `.env`
- Use `model_validate_json` or `model_validate` for parsing
- Use `model_dump_json()` for serialization
- Example:
  ```python
  class Settings(BaseSettings):
      model_config = {"env_file": ".env", "extra": "ignore"}
      
      telegram_bot_token: str
      llm_base_url: str = "http://localhost:11434/v1"
  ```

### Async Code
- Use `async def` for I/O-bound operations
- Use `await` for async calls
- Mark async tests with `@pytest.mark.asyncio`
- Use `pytest-asyncio` for test async support

### Database Operations
- Use parameterized queries (no f-strings for SQL)
- Example:
  ```python
  cursor = self._conn.execute(
      "SELECT * FROM memories WHERE id = ?", (record_id,)
  )
  ```
- Use WAL mode for SQLite: `PRAGMA journal_mode=WAL`

### Event-Driven Architecture
- Define domain events in `bearmemori/events/domain.py`
- Define bus events in `bearmemori/events/types.py`
- Use EventBus for pub/sub:
  ```python
  bus.on(MyEvent, my_handler)
  await bus.emit(MyEvent(data="value"))
  ```

## Directory Structure

```
bearmemori/
  events/       # Event definitions (types.py, domain.py) and async pub/sub bus
  interfaces/   # Telegram adapter (emits/handles events)
  core/         # Queue manager, processor, follow-up manager, scheduler, triage
  llm/          # OpenAI-compatible client, response parsing
  storage/      # SQLite + FTS5, ChromaDB vectors, pending store
  api/          # FastAPI REST API (routes.py, schemas.py)
  utils/        # Shared utilities (time.py -- UTC datetime normalization)
  webapp/       # HTMX webapp (router.py, auth.py, templates/, static/)
```

## Configuration

All config via environment variables or `.env` file. Key settings:
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_USER_ID` -- Telegram auth
- `LLM_BASE_URL` / `LLM_MODEL` -- LLM endpoint and model
- `EMBEDDING_MODEL` -- sentence-transformers model (default: all-mpnet-base-v2)
- `DATABASE_PATH` -- SQLite location
- `CHROMA_PERSIST_DIR` -- ChromaDB directory
- `WEBAPP_SECRET` -- webapp auth (empty = disabled)

## Git Conventions

- Commit messages: `type: description` (feat, fix, refactor, test, docs, chore)
- Branch naming: `v{major}.{minor}.{patch}` for version branches
- Run lint before committing: `uv run ruff check . && uv run ruff format .`

## Testing Guidelines

- Place tests in `tests/` directory
- Mirror source structure: `tests/test_module.py` matches `bearmemori/module.py`
- Use pytest with pytest-asyncio for async tests
- Use httpx for API integration tests
- Test file naming: `test_*.py`
- Test function naming: `test_function_name`
- Use fixtures for common setup
- Use `monkeypatch` for environment variable testing

## Key Design Decisions

- Sequential processing only (LLM endpoint is bottleneck)
- In-memory queue with priority system (no persistence, 2-week TTL)
- Local embedding model via sentence-transformers
- ChromaDB for vector storage, SQLite + FTS5 for structured storage
- Follow-up system maintains conversation context until LLM has enough info