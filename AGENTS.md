# BearMemori AGENTS.md

## Project Overview

BearMemori is a personal memory management system built with a microservice architecture. It includes:
- **core**: FastAPI-based REST API service
- **telegram**: Telegram bot gateway
- **llm_worker**: Background worker for LLM processing
- **email_poller**: Email polling service
- **shared**: Shared libraries and configuration

## Technology Stack

- **Runtime**: Python 3.12+ (some packages support 3.11)
- **Web Framework**: FastAPI
- **Database**: SQLite with aiosqlite
- **Redis**: Async Redis client for streaming and caching
- **Configuration**: Pydantic Settings
- **Testing**: pytest with pytest-asyncio

## Directory Structure

```
BearMemori/
├── core/              # Core API service (port 8000)
├── telegram/          # Telegram bot gateway
├── llm_worker/        # LLM processing worker
├── email_poller/      # Email polling service
├── shared/            # Shared libraries
└── tests/             # Integration tests
```

## Build & Install Commands

Each service uses Hatch for building:

```bash
# Install dependencies (run in each service directory)
poetry install
# or directly with pip
pip install -e .

# Build package
hatch build
```

## Running Services

```bash
# Start core service (from /Users/macminijh/projects/BearMemori)
cd core
hatch run python -m core.main

# Start with uvicorn directly
hatch run uvicorn core.main:app --host 0.0.0.0 --port 8000

# Run all services with Docker
docker-compose up --build
```

## Testing

### Run All Tests
```bash
pytest
```

### Run Single Test File
```bash
pytest tests/test_core/test_database.py
```

### Run Single Test Function
```bash
pytest tests/test_core/test_database.py::TestInitDb::test_init_db_creates_tables
```

### Run Tests with Verbose Output
```bash
pytest -v
```

### Run Tests with Coverage
```bash
pytest --cov=. --cov-report=term-missing
```

### Run Tests Matching Pattern
```bash
pytest -k "test_create_memory"
```

### Test Fixtures (in `tests/conftest.py`)
- `test_db`: Temporary SQLite database with migrations
- `mock_redis`: FakeRedis instance for testing
- `test_app`: FastAPI test client with DB and Redis
- `test_user`: Test user with ID 12345

## Code Style Guidelines

### Imports
- Group imports: standard library, third-party, first-party
- Use absolute imports: `from core.database import init_db`
- Keep imports at top of file
- Sort alphabetically within groups

### Formatting
- 4 spaces per indentation level
- Max line length: 100 characters
- Use double quotes for strings
- Use f-strings for string formatting

### Naming Conventions
- **Functions/Variables**: `snake_case` (`init_db`, `user_id`)
- **Classes**: `PascalCase` (`Settings`, `TestInitDb`)
- **Constants**: `SCREAMING_SNAKE_CASE` (`STREAM_LLM_IMAGE_TAG`)
- **Private**: `_leading_underscore` for internal use

### Type Hints
- Always use type hints for function signatures
- Use `AsyncIterator`, `dict`, `list` from `typing` for generics
- Example: `async def init_db(db_path: str) -> aiosqlite.Connection`
- Use `Optional[T]` for nullable types
- Use `Union[T1, T2]` or `T1 | T2` (Python 3.10+) for unions

### Error Handling
- Use try-except for specific exceptions
- Log exceptions with context: `logger.exception("Error message")`
- Return appropriate HTTP status codes in FastAPI endpoints
- Use `raise` for unrecoverable errors

### Database
- Always use `async with` for database operations when possible
- Commit changes explicitly with `await conn.commit()`
- Use parameterized queries to prevent SQL injection
- Check for null/None before accessing row fields

### Logging
- Use `logger = logging.getLogger(__name__)` in each module
- Log at appropriate levels: debug, info, warning, error
- Include context in log messages

### Async/Await
- Mark functions as `async def` when using await
- Use `await` for all async operations (DB, Redis, HTTP)
- Handle `asyncio.CancelledError` for task cancellation

### Configuration
- Use Pydantic Settings for configuration
- Load with `load_config()` from `shared.config`
- Environment variables override defaults
- Never hardcode sensitive values

## Docker & Deployment

### Services
- **core**: FastAPI server (port 8000)
- **redis**: Redis 7 Alpine (port 6379)
- **telegram**, **llm_worker**, **email_poller**: Background workers

### Volumes
- `db-data`: SQLite database persistence
- `image-data`: Image storage
- `redis-data`: Redis AOF persistence

### Health Checks
- Core: `GET /health` returns `{"status": "ok"}`
- Redis: `redis-cli ping`

## Git Workflow

- Feature branches: `feature/descriptive-name`
- Use atomic, well-documented commits
- Rebase before merging to keep history clean

## Common Tasks

### Add Migration
1. Create `core/migrations/NNN_description.sql` (NNN = version number)
2. Update schema version in code (currently 7)
3. Test idempotency by running migration twice

### Add New Endpoint
1. Create router file in `core/core/routers/`
2. Add router to imports in `core/core/main.py`
3. Include router with appropriate prefix
4. Add tests in `tests/test_core/test_<name>.py`

### Run Linter/Type Checker
```bash
# If using ruff (configure if installed)
ruff check .

# If using mypy (configure if installed)
mypy .
```
