# BearMemori

Personal memory store with LLM processing. Single user, homelab deployment.

## Architecture

Event-driven modular monolith. Single Python process with an async event bus (`asyncio`).

```
bearmemori/
  events/       # Event definitions (types.py, domain.py) and async pub/sub bus
  interfaces/   # Telegram adapter (emits/handles events)
  core/         # Queue manager, processor, follow-up manager, scheduler, triage
  llm/          # OpenAI-compatible client (targets local LLM endpoint), response parsing
  storage/      # SQLite + FTS5 (database.py), ChromaDB vectors (vector_store.py), pending store
  api/          # FastAPI REST API (routes.py, schemas.py)
  webapp/       # HTMX webapp (router.py, auth.py, templates/, static/)
```

Entry point: `bearmemori/app.py` wires everything together. Run via `bearmemori/__main__.py`.

## Key Design Decisions

- Sequential processing only -- LLM endpoint is the bottleneck (one input at a time)
- In-memory queue with priority system (no persistence between restarts, 2-week TTL)
- Embedding model runs locally via sentence-transformers (`all-mpnet-base-v2`)
- ChromaDB for vector storage, SQLite + FTS5 for structured storage
- LLM endpoint is OpenAI-compatible at a remote homelab server (see .env for URL)
- Follow-up system maintains conversation context until LLM has enough info

## Stack

- Python 3.12+, managed with `uv`
- FastAPI + Uvicorn (REST API)
- Jinja2 + HTMX + Pico CSS (webapp)
- python-telegram-bot (Telegram interface)
- openai SDK (LLM client, OpenAI-compatible endpoint)
- ChromaDB + sentence-transformers (vector search)
- SQLite + FTS5 (structured storage)
- pydantic-settings (config from .env)

## Development

```bash
uv sync                     # Install dependencies
uv sync --extra dev         # Install with dev dependencies
uv run python -m bearmemori # Run the app
uv run pytest               # Run tests
uv run ruff check .         # Lint
uv run ruff format .        # Format
```

## Testing

- pytest + pytest-asyncio for async tests
- httpx for API integration tests
- Tests live in `tests/` directory

## Config

All config via environment variables or `.env` file. See `bearmemori/config.py` for
all settings and defaults. Key settings:

- `LLM_BASE_URL` / `LLM_MODEL` -- LLM endpoint and model
- `EMBEDDING_MODEL` -- local sentence-transformers model (default: all-mpnet-base-v2)
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_ALLOWED_USER_ID` -- Telegram bot auth
- `DATABASE_PATH` -- SQLite database location
- `CHROMA_PERSIST_DIR` -- ChromaDB persistence directory
- `WEBAPP_SECRET` -- shared secret for webapp auth (empty = webapp disabled)

## Conventions

- Ruff for linting and formatting
- Commit messages: `type: description` (feat, fix, refactor, test, docs, chore)
- Branch naming: `v{major}.{minor}.{patch}` for version branches
- Event-driven communication between modules (no direct cross-module imports)
- Domain events defined in `events/domain.py`, bus events in `events/types.py`
