# BearMemori AGENTS.md

## Project Overview

BearMemori is a personal memory management system with microservices:
- **core**: FastAPI REST API (port 8000)
- **telegram**: Telegram bot gateway
- **llm_worker**: LLM processing worker
- **email_poller**: Email polling service
- **shared**: Shared libraries and configuration

## Technology Stack
- Runtime: Python 3.12+
- Framework: FastAPI with Uvicorn
- Database: SQLite with aiosqlite
- Cache/Queue: Redis 7 Alpine
- Testing: pytest with pytest-asyncio (auto mode)

---

## Build & Test Commands

### Install Dependencies (per service)
```bash
cd <service> && poetry install   # or pip install -e .
```

### Run Tests
```bash
pytest                           # All tests from project root
pytest tests/test_core/test_database.py  # Single file
pytest tests/test_core/test_database.py::TestInitDb::test_init_db_creates_tables  # Single test

# Options
pytest -v                                    # Verbose
pytest -k "test_create_memory"            # Pattern match
pytest --cov=core --cov-report=term-missing # Coverage
pytest --tb=short                          # Shorter traceback
pytest -x                                  # Stop on first failure
```

### Run Linter
```bash
ruff check . && ruff check . --fix
mypy .
```

---

## Running Services

```bash
# Core (from project root)
cd core && hatch run uvicorn core.main:app --host 0.0.0.0 --port 8000

# Background services
cd telegram && hatch run python -m telegram.bot
cd llm_worker && hatch run python -m llm_worker.worker
cd email_poller && hatch run python -m email_poller.poller

# Docker
docker-compose up --build
```

---

## Code Style Guidelines

### Imports
Group order: standard library, third-party, first-party. Use absolute imports, sort alphabetically within groups.

### Formatting
- 4 spaces per indentation (no tabs)
- Max line length: 100 characters
- Use double quotes for strings
- Use f-strings: `f"User {user_id} created"`

### Naming Conventions
| Type | Convention | Example |
|------|-------------|---------|
| Functions/Variables | snake_case | `init_db`, `user_id` |
| Classes | PascalCase | `Settings`, `TestInitDb` |
| Constants | SCREAMING_SNAKE | `STREAM_LLM_IMAGE_TAG` |
| Private | leading_underscore | `_internal_func` |

### Type Hints
Always use type hints: `async def init_db(db_path: str) -> aiosqlite.Connection:`. Use `Optional[T]` and `T1 | T2`.

### Error Handling
Use specific exceptions, log with `logger.exception()`, return appropriate HTTP status codes.

### Database
Use `async with aiosqlite.connect(db_path) as db:`, commit explicitly, use parameterized queries.

### Logging
Use `logger = logging.getLogger(__name__)` in each module. Include context in messages.

### Configuration
Use Pydantic Settings: `class Settings(BaseSettings)`. Load with `load_config()`. Never hardcode secrets.

---

## Test Fixtures (tests/conftest.py)

| Fixture | Description |
|----------|---------------|
| `test_db` | Temporary SQLite DB with migrations |
| `mock_redis` | FakeRedis instance |
| `test_app` | FastAPI test client with DB/Redis |
| `test_user` | Test user with ID 12345 |

---

## Common Tasks

### Add Database Migration
1. Create `core/migrations/NNN_description.sql` (NNN = version)
2. Update schema version in code (currently 7)
3. Test idempotency by running twice

### Add New Endpoint
1. Create router in `core/core/routers/`
2. Add to imports in `core/core/main.py`
3. Include router with prefix
4. Add tests in `tests/test_core/test_<name>.py`

---

## Git Workflow
```bash
git checkout -b feature/descriptive-name
git add . && git commit -m "Add feature X"
git fetch origin && git rebase origin/main
```

---

## Docker Services

| Service | Port | Health Check |
|---------|------|---------------|
| core | 8000 | `GET /health` returns `{"status": "ok"}` |
| redis | 6379 | `redis-cli ping` |

Volumes: `db-data` (SQLite), `image-data`, `redis-data` (AOF).

All services read from `.env` file.
