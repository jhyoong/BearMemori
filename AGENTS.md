# BearMemori AGENTS.md

## Project Overview

BearMemori is a personal memory management system with microservices:
- **core**: FastAPI REST API (port 8000)
- **telegram**: Telegram bot gateway
- **llm_worker**: LLM processing worker
- **email_poller**: Email polling service
- **assistant**: AI assistant service
- **shared**: Shared libraries and configuration

## Technology Stack
- Runtime: Python 3.12+
- Framework: FastAPI with Uvicorn
- Database: SQLite with aiosqlite
- Cache/Queue: Redis 7 Alpine
- Testing: pytest with pytest-asyncio (auto mode)
- Linting: ruff

---

## Build & Test Commands

### Install Dependencies (per service)
```bash
cd <service> && poetry install   # or pip install -e .
```

### Run All Tests
```bash
pytest                           # All tests from project root
```

### Run Tests by Service
```bash
pytest tests/test_core/          # Core service tests
pytest tests/test_telegram/      # Telegram bot tests
pytest tests/test_llm_worker/    # LLM worker tests
pytest tests/test_assistant/      # Assistant tests
```

### Run Single Test File or Function
```bash
pytest tests/test_core/test_database.py                # Single file
pytest tests/test_core/test_database.py::TestInitDb     # Single test class
pytest tests/test_core/test_database.py::TestInitDb::test_init_db_creates_tables  # Single test
```

### Useful pytest Options
```bash
pytest -v                                    # Verbose output
pytest -k "test_create_memory"            # Pattern match test names
pytest --cov=core --cov-report=term-missing # Coverage report
pytest --tb=short                          # Shorter traceback
pytest -x                                  # Stop on first failure
pytest --lf                                # Run only last failed tests
```

### Run Linter
```bash
ruff check .              # Check for issues
ruff check . --fix       # Auto-fix issues
mypy .                    # Type checking
```

---

## Code Style Guidelines

### Imports
Group order: standard library, third-party, first-party. Use absolute imports, sort alphabetically within groups.

Example:
```python
import logging
from pathlib import Path

import aiosqlite
from fastapi import APIRouter

from core.config import Settings
from core.schemas import MemoryCreate
```

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
| Test Classes | Test + PascalCase | `TestInitDb`, `TestMemorySearch` |

### Type Hints
Always use type hints for function signatures:
```python
async def init_db(db_path: str) -> aiosqlite.Connection:
    ...

def process_result(items: list[dict], limit: int | None = None) -> list[dict] | None:
    ...
```
Use `Optional[T]` for older code, `T | None` for new code.

### Error Handling
- Use specific exceptions, avoid catching generic `Exception`
- Log with `logger.exception()` for caught errors
- Return appropriate HTTP status codes in API endpoints
- Always validate input data with Pydantic models

### Database
- Use async context manager: `async with aiosqlite.connect(db_path) as db:`
- Commit explicitly after changes
- Use parameterized queries to prevent SQL injection
- Close connections properly

### Logging
- Use `logger = logging.getLogger(__name__)` in each module
- Include context in log messages: `f"User {user_id} operation failed"`
- Use appropriate levels: DEBUG, INFO, WARNING, ERROR
- Never log sensitive data (passwords, tokens)

### Configuration
- Use Pydantic Settings: `class Settings(BaseSettings)`
- Load with `load_config()` function
- Never hardcode secrets - use environment variables
- Use `.env` file for local development

---

## Test Fixtures (tests/conftest.py)

| Fixture | Description |
|----------|---------------|
| `test_db` | Temporary SQLite DB with migrations, auto-cleanup |
| `mock_redis` | FakeRedis instance for testing |
| `test_app` | FastAPI test client with DB/Redis |
| `test_user` | Test user with ID 12345 |
| `event_loop` | asyncio event loop for async tests |

### Using Fixtures
```python
async def test_create_memory(test_db, test_user):
    # test_db provides a database connection
    # test_user provides a user dict with id=12345
    ...
```

---

## Common Tasks

### Add Database Migration
1. Create `core/migrations/NNN_description.sql` (NNN = next version number)
2. Update schema version in code (currently 7)
3. Test idempotency by running migration twice

### Add New Endpoint
1. Create router in `core/core/routers/`
2. Add to imports in `core/core/main.py`
3. Include router with prefix
4. Add tests in `tests/test_core/test_<name>.py`

### Add New Service
1. Create directory `new_service/`
2. Add `pyproject.toml` with hatchling build
3. Add entry point in `__main__.py`
4. Add to docker-compose.yml
5. Create tests in `tests/test_new_service/`

### Debug Failed Test
```bash
pytest tests/test_core/test_database.py::TestInitDb::test_init_db_creates_tables -v --tb=long
```

---

## Running Services

### Development
```bash
# Core API
cd core && hatch run uvicorn core.main:app --host 0.0.0.0 --port 8000

# Background services
cd telegram && hatch run python -m telegram.bot
cd llm_worker && hatch run python -m llm_worker.worker
cd email_poller && hatch run python -m email_poller.poller
cd assistant && hatch run python -m assistant.main
```

### Docker
```bash
docker-compose up --build          # Start all services
docker-compose up --build -d     # Detached mode
docker-compose down              # Stop all services
docker-compose logs -f <service>  # View service logs
```

---

## Git Workflow
```bash
# Create feature branch
git checkout -b feature/descriptive-name

# Commit changes
git add . && git commit -m "Add feature X"

# Rebase on main
git fetch origin && git rebase origin/main

# Push and create PR
git push -u origin feature/descriptive-name
```

---

## Docker Services

| Service | Port | Health Check |
|---------|------|---------------|
| core | 8000 | `GET /health` returns `{"status": "ok"}` |
| redis | 6379 | `redis-cli ping` |

Volumes: `db-data` (SQLite), `image-data`, `redis-data` (AOF).

All services read from `.env` file.
