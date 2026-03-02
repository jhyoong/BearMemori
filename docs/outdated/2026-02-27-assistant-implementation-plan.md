# BearMemori Assistant Service Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a conversational assistant service that uses OpenAI tool-calling to help users interact with their BearMemori data (memories, tasks, reminders, events), with context-aware briefings and summarize-and-truncate chat history management.

**Architecture:** A new service (`assistant/assistant_svc/`) in the monorepo. It has a Core API HTTP client, an OpenAI-powered agent with tool-calling, a context manager for chat history, a briefing builder, an abstract interface layer (Telegram first), and a daily digest scheduler. All chat state lives in Redis.

**Tech Stack:** Python 3.12, openai SDK, httpx, redis, python-telegram-bot, pydantic-settings, tiktoken (for token counting), pytest + pytest-asyncio + fakeredis for tests.

**Design doc:** `docs/plans/2026-02-27-assistant-service-design.md`

---

## Task 1: Project Scaffolding and Config

Set up the assistant service directory structure, packaging, config, and Dockerfile.

**Files:**
- Create: `assistant/assistant_svc/__init__.py`
- Create: `assistant/assistant_svc/config.py`
- Create: `assistant/pyproject.toml`
- Create: `assistant/Dockerfile`
- Modify: `docker-compose.yml` (add assistant service)
- Test: `tests/test_assistant/test_config.py`

**Step 1: Create directory structure**

```bash
mkdir -p assistant/assistant_svc/tools
mkdir -p assistant/assistant_svc/interfaces
mkdir -p tests/test_assistant
```

Create empty `__init__.py` files:
- `assistant/assistant_svc/__init__.py`
- `assistant/assistant_svc/tools/__init__.py`
- `assistant/assistant_svc/interfaces/__init__.py`
- `tests/test_assistant/__init__.py`

**Step 2: Create `assistant/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "life-organiser-assistant"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "openai>=1.0.0",
    "httpx>=0.27",
    "redis[hiredis]>=5.0.0",
    "pydantic-settings>=2.0.0",
    "tiktoken>=0.7.0",
    "python-telegram-bot[ext]>=20.0,<23.0",
    "life-organiser-shared",
]
```

**Step 3: Create `assistant/assistant_svc/config.py`**

```python
"""Configuration for the assistant service."""

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class AssistantConfig(BaseSettings):
    """Assistant service settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    core_api_url: str = "http://core:8000"
    redis_url: str = "redis://redis:6379"
    openai_api_key: str = "not-needed"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    assistant_telegram_bot_token: str = ""
    allowed_user_ids: str = ""
    context_window_tokens: int = 128000
    briefing_budget_tokens: int = 5000
    response_reserve_tokens: int = 4000
    session_timeout_seconds: int = 1800
    digest_default_hour: int = 8


def load_config() -> AssistantConfig:
    """Load and return assistant configuration."""
    return AssistantConfig()
```

**Step 4: Write the test for config**

```python
# tests/test_assistant/test_config.py
"""Tests for assistant service configuration."""

import os
import pytest
from assistant_svc.config import AssistantConfig, load_config


def test_config_defaults():
    """Config loads with default values."""
    config = AssistantConfig(
        _env_file=None,
        openai_api_key="test-key",
        assistant_telegram_bot_token="test-token",
    )
    assert config.core_api_url == "http://core:8000"
    assert config.redis_url == "redis://redis:6379"
    assert config.context_window_tokens == 128000
    assert config.briefing_budget_tokens == 5000
    assert config.session_timeout_seconds == 1800


def test_config_env_override(monkeypatch):
    """Config values can be overridden by environment variables."""
    monkeypatch.setenv("CORE_API_URL", "http://localhost:9000")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ASSISTANT_TELEGRAM_BOT_TOKEN", "test-token")
    config = AssistantConfig(_env_file=None)
    assert config.core_api_url == "http://localhost:9000"
    assert config.openai_model == "gpt-4o-mini"
```

**Step 5: Run test to verify it passes**

```bash
cd /path/to/BearMemori
pip install -e shared/ && pip install -e assistant/
pytest tests/test_assistant/test_config.py -v
```

Expected: PASS

**Step 6: Create `assistant/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/
COPY assistant/ /app/assistant/
RUN pip install --no-cache-dir -e /app/assistant/
CMD ["python", "-m", "assistant_svc.main"]
```

**Step 7: Add assistant to `docker-compose.yml`**

Add the following service block after the `email` service:

```yaml
  assistant:
    build:
      context: .
      dockerfile: assistant/Dockerfile
    depends_on:
      core:
        condition: service_healthy
      redis:
        condition: service_healthy
    env_file: .env
    restart: unless-stopped
```

**Step 8: Commit**

```bash
git add assistant/ tests/test_assistant/ docker-compose.yml
git commit -m "feat(assistant): scaffold service with config and packaging"
```

---

## Task 2: Core API Client

Build the HTTP client the assistant uses to talk to the Core API. This is a subset of the existing `tg_gateway/core_client.py` pattern, with additions for list queries with filters.

**Files:**
- Create: `assistant/assistant_svc/core_client.py`
- Test: `tests/test_assistant/test_core_client.py`

**Reference:** `telegram/tg_gateway/core_client.py` -- follow the same `httpx.AsyncClient` pattern with `CoreClientError`, `CoreUnavailableError`, `CoreNotFoundError`.

**Step 1: Write the failing test**

```python
# tests/test_assistant/test_core_client.py
"""Tests for assistant Core API client."""

import json
import pytest
import pytest_asyncio
import httpx
from httpx import Response, Request

from assistant_svc.core_client import AssistantCoreClient, CoreClientError


@pytest_asyncio.fixture
async def mock_transport():
    """A transport that records requests and returns canned responses."""
    class MockTransport(httpx.AsyncBaseTransport):
        def __init__(self):
            self.requests: list[httpx.Request] = []
            self.responses: dict[str, Response] = {}

        def set_response(self, method_path: str, status: int, json_data):
            """Register a canned response for METHOD /path."""
            self.responses[method_path] = (status, json_data)

        async def handle_async_request(self, request: httpx.Request) -> Response:
            self.requests.append(request)
            key = f"{request.method} {request.url.path}"
            # Also try with query string
            if key not in self.responses:
                key_with_query = f"{request.method} {request.url.path}?{request.url.query.decode()}"
                if key_with_query in self.responses:
                    key = key_with_query
            if key in self.responses:
                status, data = self.responses[key]
                return Response(status, json=data, request=request)
            return Response(404, json={"detail": "not found"}, request=request)

    return MockTransport()


@pytest_asyncio.fixture
async def client(mock_transport):
    """AssistantCoreClient with mock transport."""
    http = httpx.AsyncClient(transport=mock_transport, base_url="http://test")
    c = AssistantCoreClient.__new__(AssistantCoreClient)
    c._client = http
    yield c
    await http.aclose()


@pytest.mark.asyncio
async def test_search_memories(client, mock_transport):
    """search_memories calls GET /search with correct params."""
    mock_transport.set_response(
        "GET /search",
        200,
        [{"memory": {"id": "m1", "owner_user_id": 1, "content": "test",
          "media_type": None, "media_file_id": None, "media_local_path": None,
          "status": "confirmed", "pending_expires_at": None, "is_pinned": False,
          "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
          "tags": []}, "score": 1.0}],
    )
    results = await client.search_memories(query="test", owner_user_id=1)
    assert len(results) == 1
    assert results[0].memory.id == "m1"


@pytest.mark.asyncio
async def test_list_tasks(client, mock_transport):
    """list_tasks calls GET /tasks with owner filter."""
    mock_transport.set_response(
        "GET /tasks",
        200,
        [{"id": "t1", "memory_id": "m1", "owner_user_id": 1,
          "description": "Buy milk", "state": "NOT_DONE", "due_at": None,
          "recurrence_minutes": None, "completed_at": None,
          "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}],
    )
    tasks = await client.list_tasks(owner_user_id=1)
    assert len(tasks) == 1
    assert tasks[0].description == "Buy milk"


@pytest.mark.asyncio
async def test_list_reminders(client, mock_transport):
    """list_reminders calls GET /reminders with filters."""
    mock_transport.set_response(
        "GET /reminders",
        200,
        [{"id": "r1", "memory_id": "m1", "owner_user_id": 1,
          "text": "Call dentist", "fire_at": "2026-03-01T09:00:00",
          "recurrence_minutes": None, "fired": False,
          "created_at": "2026-01-01T00:00:00", "updated_at": None}],
    )
    reminders = await client.list_reminders(owner_user_id=1, upcoming_only=True)
    assert len(reminders) == 1
    assert reminders[0].text == "Call dentist"


@pytest.mark.asyncio
async def test_create_task(client, mock_transport):
    """create_task calls POST /tasks."""
    mock_transport.set_response(
        "POST /tasks",
        200,
        {"id": "t1", "memory_id": "m1", "owner_user_id": 1,
         "description": "Buy milk", "state": "NOT_DONE", "due_at": None,
         "recurrence_minutes": None, "completed_at": None,
         "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"},
    )
    task = await client.create_task(
        memory_id="m1", owner_user_id=1, description="Buy milk"
    )
    assert task.id == "t1"


@pytest.mark.asyncio
async def test_create_reminder(client, mock_transport):
    """create_reminder calls POST /reminders."""
    mock_transport.set_response(
        "POST /reminders",
        200,
        {"id": "r1", "memory_id": "m1", "owner_user_id": 1,
         "text": "Call dentist", "fire_at": "2026-03-01T09:00:00",
         "recurrence_minutes": None, "fired": False,
         "created_at": "2026-01-01T00:00:00", "updated_at": None},
    )
    reminder = await client.create_reminder(
        memory_id="m1", owner_user_id=1, text="Call dentist",
        fire_at="2026-03-01T09:00:00"
    )
    assert reminder.id == "r1"


@pytest.mark.asyncio
async def test_list_events(client, mock_transport):
    """list_events calls GET /events with filters."""
    mock_transport.set_response(
        "GET /events",
        200,
        [{"id": "e1", "memory_id": None, "owner_user_id": 1,
          "event_time": "2026-03-01T10:00:00", "description": "Meeting",
          "status": "confirmed", "source_type": "manual", "source_detail": None,
          "reminder_id": None,
          "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}],
    )
    events = await client.list_events(owner_user_id=1)
    assert len(events) == 1
    assert events[0].description == "Meeting"


@pytest.mark.asyncio
async def test_get_memory(client, mock_transport):
    """get_memory calls GET /memories/{id}."""
    mock_transport.set_response(
        "GET /memories/m1",
        200,
        {"id": "m1", "owner_user_id": 1, "content": "Hello world",
         "media_type": None, "media_file_id": None, "media_local_path": None,
         "status": "confirmed", "pending_expires_at": None, "is_pinned": False,
         "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
         "tags": []},
    )
    mem = await client.get_memory("m1")
    assert mem is not None
    assert mem.content == "Hello world"


@pytest.mark.asyncio
async def test_get_memory_not_found(client, mock_transport):
    """get_memory returns None on 404."""
    result = await client.get_memory("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_get_settings(client, mock_transport):
    """get_settings calls GET /settings/{user_id}."""
    mock_transport.set_response(
        "GET /settings/1",
        200,
        {"user_id": 1, "timezone": "Europe/London", "language": "en",
         "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"},
    )
    settings = await client.get_settings(1)
    assert settings.timezone == "Europe/London"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_assistant/test_core_client.py -v
```

Expected: FAIL -- `AssistantCoreClient` does not exist.

**Step 3: Implement `assistant/assistant_svc/core_client.py`**

Follow the pattern from `telegram/tg_gateway/core_client.py`. Methods needed:

- `search_memories(query, owner_user_id) -> list[MemorySearchResult]`
- `get_memory(memory_id) -> MemoryWithTags | None`
- `list_tasks(owner_user_id, state=None) -> list[TaskResponse]`
- `list_reminders(owner_user_id, fired=None, upcoming_only=None) -> list[ReminderResponse]`
- `list_events(owner_user_id, status=None) -> list[EventResponse]`
- `create_task(memory_id, owner_user_id, description, due_at=None) -> TaskResponse`
- `create_reminder(memory_id, owner_user_id, text, fire_at) -> ReminderResponse`
- `get_settings(user_id) -> UserSettingsResponse`
- `close()`

Each method uses `self._client` (httpx.AsyncClient), catches `ConnectError` and `TimeoutException`, raises `CoreClientError` / `CoreUnavailableError` / `CoreNotFoundError`.

Import models from `shared_lib.schemas`.

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_assistant/test_core_client.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add assistant/assistant_svc/core_client.py tests/test_assistant/test_core_client.py
git commit -m "feat(assistant): add Core API client with tests"
```

---

## Task 3: Tool Registry and Tool Definitions

Build the tool registry that maps tool names to functions and OpenAI tool schemas. Implement all 7 initial tools.

**Files:**
- Create: `assistant/assistant_svc/tools/__init__.py` (registry)
- Create: `assistant/assistant_svc/tools/memories.py`
- Create: `assistant/assistant_svc/tools/tasks.py`
- Create: `assistant/assistant_svc/tools/reminders.py`
- Create: `assistant/assistant_svc/tools/events.py`
- Test: `tests/test_assistant/test_tools.py`

**Step 1: Write the failing tests**

```python
# tests/test_assistant/test_tools.py
"""Tests for assistant tool registry and tool functions."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from assistant_svc.tools import ToolRegistry


@pytest.fixture
def registry():
    """Empty tool registry."""
    return ToolRegistry()


def test_register_and_list(registry):
    """Can register a tool and list it."""
    async def dummy(client, **kwargs):
        return "ok"

    schema = {
        "type": "function",
        "function": {
            "name": "dummy",
            "description": "A dummy tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }
    registry.register("dummy", dummy, schema)
    assert "dummy" in registry.tool_names()
    assert registry.get_schema("dummy") == schema
    assert registry.get_function("dummy") is dummy


def test_get_all_schemas(registry):
    """get_all_schemas returns list of all registered schemas."""
    async def f1(client, **kwargs):
        return "a"
    async def f2(client, **kwargs):
        return "b"

    s1 = {"type": "function", "function": {"name": "f1", "description": "F1", "parameters": {}}}
    s2 = {"type": "function", "function": {"name": "f2", "description": "F2", "parameters": {}}}
    registry.register("f1", f1, s1)
    registry.register("f2", f2, s2)
    schemas = registry.get_all_schemas()
    assert len(schemas) == 2


@pytest.mark.asyncio
async def test_execute_tool(registry):
    """execute calls the registered function with kwargs."""
    mock_client = AsyncMock()
    results = []

    async def my_tool(client, **kwargs):
        results.append(kwargs)
        return {"found": True}

    schema = {"type": "function", "function": {"name": "my_tool", "description": "test", "parameters": {}}}
    registry.register("my_tool", my_tool, schema)
    result = await registry.execute("my_tool", mock_client, query="hello")
    assert result == {"found": True}
    assert results[0] == {"query": "hello"}


def test_execute_unknown_tool_raises(registry):
    """Calling an unregistered tool raises KeyError."""
    with pytest.raises(KeyError):
        registry.get_function("nonexistent")
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_assistant/test_tools.py -v
```

Expected: FAIL -- `ToolRegistry` does not exist.

**Step 3: Implement `assistant/assistant_svc/tools/__init__.py`**

```python
"""Tool registry for the assistant agent."""

import logging
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

ToolFunction = Callable[..., Coroutine[Any, Any, dict | str | None]]


class ToolRegistry:
    """Registry mapping tool names to functions and OpenAI schemas."""

    def __init__(self):
        self._tools: dict[str, ToolFunction] = {}
        self._schemas: dict[str, dict] = {}

    def register(self, name: str, func: ToolFunction, schema: dict) -> None:
        self._tools[name] = func
        self._schemas[name] = schema

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_function(self, name: str) -> ToolFunction:
        return self._tools[name]

    def get_schema(self, name: str) -> dict:
        return self._schemas[name]

    def get_all_schemas(self) -> list[dict]:
        return list(self._schemas.values())

    async def execute(self, name: str, client, **kwargs) -> dict | str | None:
        func = self._tools[name]
        return await func(client, **kwargs)
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_assistant/test_tools.py -v
```

Expected: all PASS

**Step 5: Implement the tool modules**

Create each tool module with the tool function and its OpenAI schema. Each function takes `client` (AssistantCoreClient) as first arg plus keyword arguments matching the schema parameters.

**`assistant/assistant_svc/tools/memories.py`:**
- `search_memories(client, query: str) -> dict` -- calls `client.search_memories(query, owner_user_id)`. Note: `owner_user_id` is injected by the agent (not in tool params).
- `get_memory(client, memory_id: str) -> dict` -- calls `client.get_memory(memory_id)`.
- Defines `SEARCH_MEMORIES_SCHEMA` and `GET_MEMORY_SCHEMA` dicts.

**`assistant/assistant_svc/tools/tasks.py`:**
- `list_tasks(client, state: str | None = None) -> dict` -- calls `client.list_tasks(owner_user_id, state)`.
- `create_task(client, memory_id: str, description: str, due_at: str | None = None) -> dict` -- calls `client.create_task(...)`.
- Defines `LIST_TASKS_SCHEMA` and `CREATE_TASK_SCHEMA`.

**`assistant/assistant_svc/tools/reminders.py`:**
- `list_reminders(client, upcoming_only: bool = True) -> dict` -- calls `client.list_reminders(owner_user_id, upcoming_only=upcoming_only)`.
- `create_reminder(client, memory_id: str, text: str, fire_at: str) -> dict` -- calls `client.create_reminder(...)`.
- Defines `LIST_REMINDERS_SCHEMA` and `CREATE_REMINDER_SCHEMA`.

**`assistant/assistant_svc/tools/events.py`:**
- `list_events(client, status: str | None = None) -> dict` -- calls `client.list_events(owner_user_id, status)`.
- Defines `LIST_EVENTS_SCHEMA`.

Each tool function returns a dict serializable to JSON (e.g., `[task.model_dump(mode="json") for task in tasks]`).

**Step 6: Write tests for individual tool functions**

Add to `tests/test_assistant/test_tools.py`:

```python
@pytest.mark.asyncio
async def test_search_memories_tool():
    """search_memories tool calls client and formats results."""
    from assistant_svc.tools.memories import search_memories
    mock_client = AsyncMock()
    mock_client.search_memories.return_value = []
    result = await search_memories(mock_client, query="groceries", owner_user_id=1)
    mock_client.search_memories.assert_called_once_with(query="groceries", owner_user_id=1)
    assert result == []


@pytest.mark.asyncio
async def test_create_task_tool():
    """create_task tool calls client with correct args."""
    from assistant_svc.tools.tasks import create_task
    mock_client = AsyncMock()
    mock_resp = MagicMock()
    mock_resp.model_dump.return_value = {"id": "t1", "description": "Buy milk"}
    mock_client.create_task.return_value = mock_resp
    result = await create_task(
        mock_client, memory_id="m1", description="Buy milk",
        due_at=None, owner_user_id=1
    )
    mock_client.create_task.assert_called_once()
```

**Step 7: Run all tool tests**

```bash
pytest tests/test_assistant/test_tools.py -v
```

Expected: all PASS

**Step 8: Commit**

```bash
git add assistant/assistant_svc/tools/ tests/test_assistant/test_tools.py
git commit -m "feat(assistant): add tool registry and 7 initial tools"
```

---

## Task 4: Context Manager (Chat History + Summarize-and-Truncate)

Build the module that manages chat history in Redis, counts tokens, and triggers summarization when the history grows too large.

**Files:**
- Create: `assistant/assistant_svc/context.py`
- Test: `tests/test_assistant/test_context.py`

**Step 1: Write the failing tests**

```python
# tests/test_assistant/test_context.py
"""Tests for chat history context management."""

import json
import pytest
import pytest_asyncio
import fakeredis.aioredis

from assistant_svc.context import ContextManager


@pytest_asyncio.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def ctx(redis):
    return ContextManager(
        redis=redis,
        context_window_tokens=1000,
        briefing_budget_tokens=200,
        response_reserve_tokens=100,
        session_timeout_seconds=1800,
    )


@pytest.mark.asyncio
async def test_empty_history(ctx):
    """New user has empty chat history."""
    messages = await ctx.load_history(user_id=1)
    assert messages == []


@pytest.mark.asyncio
async def test_save_and_load(ctx):
    """Messages are persisted to Redis and can be loaded back."""
    msgs = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
    await ctx.save_history(user_id=1, messages=msgs)
    loaded = await ctx.load_history(user_id=1)
    assert loaded == msgs


@pytest.mark.asyncio
async def test_token_count():
    """count_tokens returns a positive integer for non-empty text."""
    ctx = ContextManager.__new__(ContextManager)
    count = ctx.count_tokens("Hello, how are you?")
    assert isinstance(count, int)
    assert count > 0


@pytest.mark.asyncio
async def test_count_messages_tokens():
    """count_messages_tokens sums tokens across all message contents."""
    ctx = ContextManager.__new__(ContextManager)
    msgs = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there, how can I help?"},
    ]
    total = ctx.count_messages_tokens(msgs)
    assert total > 0


@pytest.mark.asyncio
async def test_chat_budget_calculation(ctx):
    """Chat budget = window - briefing - response reserve - system prompt estimate."""
    budget = ctx.chat_budget_tokens
    # 1000 - 200 - 100 - system_prompt_estimate
    assert budget > 0
    assert budget < 1000


@pytest.mark.asyncio
async def test_needs_summarization_false(ctx):
    """Short history does not trigger summarization."""
    msgs = [{"role": "user", "content": "Hi"}]
    assert ctx.needs_summarization(msgs) is False


@pytest.mark.asyncio
async def test_save_session_summary(ctx):
    """Session summary is saved to Redis and can be loaded."""
    await ctx.save_session_summary(user_id=1, summary="We discussed groceries.")
    summary = await ctx.load_session_summary(user_id=1)
    assert summary == "We discussed groceries."


@pytest.mark.asyncio
async def test_load_session_summary_empty(ctx):
    """Loading summary for user with no summary returns None."""
    summary = await ctx.load_session_summary(user_id=999)
    assert summary is None
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_assistant/test_context.py -v
```

Expected: FAIL -- `ContextManager` does not exist.

**Step 3: Implement `assistant/assistant_svc/context.py`**

```python
"""Chat history context management with summarize-and-truncate."""

import json
import logging

import tiktoken

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_ESTIMATE_TOKENS = 300


class ContextManager:
    """Manages chat history in Redis with token-aware truncation."""

    def __init__(
        self,
        redis,
        context_window_tokens: int,
        briefing_budget_tokens: int,
        response_reserve_tokens: int,
        session_timeout_seconds: int,
    ):
        self._redis = redis
        self._context_window_tokens = context_window_tokens
        self._briefing_budget_tokens = briefing_budget_tokens
        self._response_reserve_tokens = response_reserve_tokens
        self._session_timeout_seconds = session_timeout_seconds
        self._encoder = tiktoken.encoding_for_model("gpt-4o")

    @property
    def chat_budget_tokens(self) -> int:
        return (
            self._context_window_tokens
            - self._briefing_budget_tokens
            - self._response_reserve_tokens
            - SYSTEM_PROMPT_ESTIMATE_TOKENS
        )

    def count_tokens(self, text: str) -> int:
        return len(self._encoder.encode(text))

    def count_messages_tokens(self, messages: list[dict]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.count_tokens(content)
            # Tool call results may be dicts; serialize them
            elif isinstance(content, (dict, list)):
                total += self.count_tokens(json.dumps(content))
        return total

    def needs_summarization(self, messages: list[dict]) -> bool:
        threshold = int(self.chat_budget_tokens * 0.7)
        return self.count_messages_tokens(messages) > threshold

    async def load_history(self, user_id: int) -> list[dict]:
        raw = await self._redis.get(f"assistant:chat:{user_id}")
        if raw is None:
            return []
        return json.loads(raw)

    async def save_history(self, user_id: int, messages: list[dict]) -> None:
        await self._redis.set(
            f"assistant:chat:{user_id}",
            json.dumps(messages),
            ex=86400,  # 24 hour TTL
        )

    async def save_session_summary(self, user_id: int, summary: str) -> None:
        await self._redis.set(
            f"assistant:summary:{user_id}",
            summary,
            ex=604800,  # 7 day TTL
        )

    async def load_session_summary(self, user_id: int) -> str | None:
        raw = await self._redis.get(f"assistant:summary:{user_id}")
        if raw is None:
            return None
        return raw.decode() if isinstance(raw, bytes) else raw
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_assistant/test_context.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add assistant/assistant_svc/context.py tests/test_assistant/test_context.py
git commit -m "feat(assistant): add context manager with token counting and Redis persistence"
```

---

## Task 5: Briefing Builder

Build the module that fetches upcoming tasks, reminders, recent memories, and last session summary, then formats them into a compact briefing string within the token budget.

**Files:**
- Create: `assistant/assistant_svc/briefing.py`
- Test: `tests/test_assistant/test_briefing.py`

**Step 1: Write the failing tests**

```python
# tests/test_assistant/test_briefing.py
"""Tests for the briefing builder."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from assistant_svc.briefing import BriefingBuilder


@pytest.fixture
def mock_core_client():
    return AsyncMock()


@pytest.fixture
def mock_context_manager():
    ctx = MagicMock()
    ctx.count_tokens.side_effect = lambda text: len(text.split())  # rough word count
    return ctx


@pytest.fixture
def builder(mock_core_client, mock_context_manager):
    return BriefingBuilder(
        core_client=mock_core_client,
        context_manager=mock_context_manager,
        budget_tokens=5000,
    )


@pytest.mark.asyncio
async def test_empty_briefing(builder, mock_core_client, mock_context_manager):
    """User with no data gets a minimal briefing."""
    mock_core_client.list_tasks.return_value = []
    mock_core_client.list_reminders.return_value = []
    mock_core_client.search_memories.return_value = []
    mock_context_manager.load_session_summary = AsyncMock(return_value=None)

    text = await builder.build(user_id=1)
    assert isinstance(text, str)
    # Should still have section headers even if empty
    assert "tasks" in text.lower() or "no upcoming" in text.lower()


@pytest.mark.asyncio
async def test_briefing_includes_tasks(builder, mock_core_client, mock_context_manager):
    """Briefing includes upcoming tasks."""
    task = MagicMock()
    task.description = "Buy groceries"
    task.due_at = datetime(2026, 3, 1, 10, 0)
    task.state = "NOT_DONE"
    task.id = "t1"
    task.memory_id = "m1"
    mock_core_client.list_tasks.return_value = [task]
    mock_core_client.list_reminders.return_value = []
    mock_core_client.search_memories.return_value = []
    mock_context_manager.load_session_summary = AsyncMock(return_value=None)

    text = await builder.build(user_id=1)
    assert "Buy groceries" in text


@pytest.mark.asyncio
async def test_briefing_includes_reminders(builder, mock_core_client, mock_context_manager):
    """Briefing includes upcoming reminders."""
    reminder = MagicMock()
    reminder.text = "Call dentist"
    reminder.fire_at = datetime(2026, 3, 1, 9, 0)
    reminder.id = "r1"
    reminder.fired = False
    mock_core_client.list_tasks.return_value = []
    mock_core_client.list_reminders.return_value = [reminder]
    mock_core_client.search_memories.return_value = []
    mock_context_manager.load_session_summary = AsyncMock(return_value=None)

    text = await builder.build(user_id=1)
    assert "Call dentist" in text


@pytest.mark.asyncio
async def test_briefing_includes_session_summary(
    builder, mock_core_client, mock_context_manager
):
    """Briefing includes previous session summary when available."""
    mock_core_client.list_tasks.return_value = []
    mock_core_client.list_reminders.return_value = []
    mock_core_client.search_memories.return_value = []
    mock_context_manager.load_session_summary = AsyncMock(
        return_value="User discussed vacation plans."
    )

    text = await builder.build(user_id=1)
    assert "vacation plans" in text
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_assistant/test_briefing.py -v
```

Expected: FAIL -- `BriefingBuilder` does not exist.

**Step 3: Implement `assistant/assistant_svc/briefing.py`**

The builder:
1. Calls `core_client.list_tasks(owner_user_id, state="NOT_DONE")` to get open tasks, sorts by `due_at`, takes up to 20.
2. Calls `core_client.list_reminders(owner_user_id, upcoming_only=True)` to get unfired reminders, takes up to 20.
3. Calls `core_client.search_memories(query="*", owner_user_id=...)` or uses a list endpoint if available. For recent memories, we may need to add a "list recent" approach -- use `list_tasks` pattern or add a method to the core client. Simplest: just note "No recent memories endpoint yet" and skip this section initially, or call search with a broad query.
4. Calls `context_manager.load_session_summary(user_id)`.
5. Formats each section into compact text lines.
6. Trims sections if total tokens exceed budget.

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_assistant/test_briefing.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add assistant/assistant_svc/briefing.py tests/test_assistant/test_briefing.py
git commit -m "feat(assistant): add briefing builder with token-budget trimming"
```

---

## Task 6: Agent Core (OpenAI Tool-Calling Loop)

Build the central agent that constructs prompts, calls OpenAI with tools, handles tool call responses in a loop, and manages the summarize-and-truncate flow.

**Files:**
- Create: `assistant/assistant_svc/agent.py`
- Test: `tests/test_assistant/test_agent.py`

**Step 1: Write the failing tests**

```python
# tests/test_assistant/test_agent.py
"""Tests for the assistant agent core."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from assistant_svc.agent import Agent


@pytest.fixture
def mock_openai():
    """Mock OpenAI async client."""
    return AsyncMock()


@pytest.fixture
def mock_core_client():
    return AsyncMock()


@pytest.fixture
def mock_context():
    ctx = AsyncMock()
    ctx.load_history.return_value = []
    ctx.needs_summarization.return_value = False
    ctx.chat_budget_tokens = 100000
    ctx.count_tokens.side_effect = lambda t: len(t.split())
    ctx.count_messages_tokens.return_value = 0
    return ctx


@pytest.fixture
def mock_briefing():
    b = AsyncMock()
    b.build.return_value = "No upcoming tasks or reminders."
    return b


@pytest.fixture
def mock_registry():
    reg = MagicMock()
    reg.get_all_schemas.return_value = []
    return reg


@pytest.fixture
def agent(mock_openai, mock_core_client, mock_context, mock_briefing, mock_registry):
    return Agent(
        openai_client=mock_openai,
        model="gpt-4o",
        core_client=mock_core_client,
        context_manager=mock_context,
        briefing_builder=mock_briefing,
        tool_registry=mock_registry,
    )


@pytest.mark.asyncio
async def test_simple_text_response(agent, mock_openai, mock_context):
    """Agent returns text when LLM responds without tool calls."""
    # Mock a simple text response (no tool calls)
    mock_choice = MagicMock()
    mock_choice.message.content = "Hello! How can I help?"
    mock_choice.message.tool_calls = None
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_openai.chat.completions.create.return_value = mock_response

    reply = await agent.handle_message(user_id=1, text="Hello")
    assert reply == "Hello! How can I help?"
    mock_context.save_history.assert_called_once()


@pytest.mark.asyncio
async def test_tool_call_loop(agent, mock_openai, mock_context, mock_registry):
    """Agent executes tool calls and loops back to LLM."""
    # First call: LLM returns a tool call
    tool_call = MagicMock()
    tool_call.id = "call_123"
    tool_call.function.name = "search_memories"
    tool_call.function.arguments = '{"query": "groceries"}'

    first_choice = MagicMock()
    first_choice.message.content = None
    first_choice.message.tool_calls = [tool_call]
    first_choice.message.role = "assistant"
    first_response = MagicMock()
    first_response.choices = [first_choice]

    # Second call: LLM returns text
    second_choice = MagicMock()
    second_choice.message.content = "I found your grocery list."
    second_choice.message.tool_calls = None
    second_response = MagicMock()
    second_response.choices = [second_choice]

    mock_openai.chat.completions.create.side_effect = [first_response, second_response]

    mock_registry.get_all_schemas.return_value = [
        {"type": "function", "function": {"name": "search_memories"}}
    ]
    mock_registry.execute.return_value = [{"content": "Buy milk"}]

    reply = await agent.handle_message(user_id=1, text="What groceries do I need?")
    assert reply == "I found your grocery list."
    assert mock_openai.chat.completions.create.call_count == 2
    mock_registry.execute.assert_called_once()


@pytest.mark.asyncio
async def test_summarization_triggered(agent, mock_openai, mock_context):
    """When history is too long, agent triggers summarization."""
    mock_context.needs_summarization.return_value = True
    mock_context.load_history.return_value = [
        {"role": "user", "content": "old message 1"},
        {"role": "assistant", "content": "old reply 1"},
        {"role": "user", "content": "old message 2"},
        {"role": "assistant", "content": "old reply 2"},
    ]

    # Summarization LLM call
    summary_choice = MagicMock()
    summary_choice.message.content = "User asked two questions."
    summary_response = MagicMock()
    summary_response.choices = [summary_choice]

    # Actual response
    reply_choice = MagicMock()
    reply_choice.message.content = "Here's my answer."
    reply_choice.message.tool_calls = None
    reply_response = MagicMock()
    reply_response.choices = [reply_choice]

    mock_openai.chat.completions.create.side_effect = [summary_response, reply_response]

    reply = await agent.handle_message(user_id=1, text="New question")
    assert reply == "Here's my answer."
    # Should have made 2 LLM calls: summarization + actual response
    assert mock_openai.chat.completions.create.call_count == 2
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_assistant/test_agent.py -v
```

Expected: FAIL -- `Agent` does not exist.

**Step 3: Implement `assistant/assistant_svc/agent.py`**

The Agent class:

1. `handle_message(user_id, text) -> str`:
   - Load history from context manager
   - If `needs_summarization(history)`: call LLM to summarize oldest half, replace in history
   - Build briefing via `briefing_builder.build(user_id)`
   - Construct system message with persona + briefing
   - Append history + new user message
   - Call `openai_client.chat.completions.create(model, messages, tools)`
   - If response has `tool_calls`: execute each via `tool_registry.execute()`, append tool results, call LLM again (loop, max 10 iterations to prevent infinite loops)
   - Extract final text response
   - Save updated history to context manager
   - Return response text

2. System prompt should instruct the LLM:
   - It is a personal assistant with access to the user's memories, tasks, reminders, and events
   - It should always confirm before executing write operations
   - The briefing section contains current user context
   - `owner_user_id` is injected into tool calls (the LLM does not need to provide it)

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_assistant/test_agent.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add assistant/assistant_svc/agent.py tests/test_assistant/test_agent.py
git commit -m "feat(assistant): add agent with tool-calling loop and summarization"
```

---

## Task 7: Interface Layer (Abstract Base + Telegram)

Build the abstract interface and Telegram implementation.

**Files:**
- Create: `assistant/assistant_svc/interfaces/base.py`
- Create: `assistant/assistant_svc/interfaces/telegram.py`
- Test: `tests/test_assistant/test_interfaces.py`

**Step 1: Write the failing tests**

```python
# tests/test_assistant/test_interfaces.py
"""Tests for the interface layer."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from assistant_svc.interfaces.base import BaseInterface


def test_base_interface_is_abstract():
    """BaseInterface cannot be instantiated directly."""
    with pytest.raises(TypeError):
        BaseInterface()


def test_base_interface_requires_send_message():
    """Subclass must implement send_message."""

    class Incomplete(BaseInterface):
        async def start(self):
            pass

        async def stop(self):
            pass

    with pytest.raises(TypeError):
        Incomplete()


def test_base_interface_subclass_works():
    """A complete subclass can be instantiated."""

    class Complete(BaseInterface):
        async def send_message(self, user_id: int, text: str) -> None:
            pass

        async def start(self):
            pass

        async def stop(self):
            pass

    instance = Complete()
    assert instance is not None
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_assistant/test_interfaces.py -v
```

Expected: FAIL -- `BaseInterface` does not exist.

**Step 3: Implement `assistant/assistant_svc/interfaces/base.py`**

```python
"""Abstract base interface for the assistant."""

from abc import ABC, abstractmethod


class BaseInterface(ABC):
    """Abstract chat interface. Subclass for Telegram, web, etc."""

    @abstractmethod
    async def send_message(self, user_id: int, text: str) -> None:
        """Send a message to the user."""

    @abstractmethod
    async def start(self) -> None:
        """Start listening for messages."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening and clean up."""
```

**Step 4: Implement `assistant/assistant_svc/interfaces/telegram.py`**

This follows the pattern from `telegram/tg_gateway/main.py`:
- Uses `python-telegram-bot` with `ApplicationBuilder`
- Registers a message handler that calls `agent.handle_message(user_id, text)`
- `send_message` uses `bot.send_message(chat_id, text)`
- Filters messages by allowed user IDs
- `start()` calls `app.run_polling()`
- `stop()` calls `app.stop()`

**Step 5: Run tests to verify they pass**

```bash
pytest tests/test_assistant/test_interfaces.py -v
```

Expected: all PASS

**Step 6: Commit**

```bash
git add assistant/assistant_svc/interfaces/ tests/test_assistant/test_interfaces.py
git commit -m "feat(assistant): add interface layer with abstract base and Telegram impl"
```

---

## Task 8: Digest Scheduler

Build the daily digest scheduler that sends morning briefings.

**Files:**
- Create: `assistant/assistant_svc/digest.py`
- Test: `tests/test_assistant/test_digest.py`

**Step 1: Write the failing tests**

```python
# tests/test_assistant/test_digest.py
"""Tests for the daily digest scheduler."""

import pytest
import pytest_asyncio
import fakeredis.aioredis
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from assistant_svc.digest import DigestScheduler


@pytest_asyncio.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def mock_briefing():
    b = AsyncMock()
    b.build.return_value = "You have 2 tasks due today."
    return b


@pytest.fixture
def mock_interface():
    return AsyncMock()


@pytest.fixture
def mock_core_client():
    settings = MagicMock()
    settings.timezone = "UTC"
    client = AsyncMock()
    client.get_settings.return_value = settings
    return client


@pytest.fixture
def scheduler(redis, mock_briefing, mock_interface, mock_core_client):
    return DigestScheduler(
        redis=redis,
        briefing_builder=mock_briefing,
        interface=mock_interface,
        core_client=mock_core_client,
        user_ids=[1, 2],
        default_hour=8,
    )


@pytest.mark.asyncio
async def test_send_digest(scheduler, mock_interface, redis):
    """send_digest sends briefing and sets sent flag."""
    await scheduler.send_digest_for_user(user_id=1)
    mock_interface.send_message.assert_called_once()
    call_args = mock_interface.send_message.call_args
    assert call_args[1]["user_id"] == 1 or call_args[0][0] == 1
    assert "2 tasks" in str(call_args)


@pytest.mark.asyncio
async def test_digest_not_sent_twice(scheduler, mock_interface, redis):
    """Digest is not sent twice on the same day."""
    await scheduler.send_digest_for_user(user_id=1)
    await scheduler.send_digest_for_user(user_id=1)
    assert mock_interface.send_message.call_count == 1


@pytest.mark.asyncio
async def test_digest_skips_empty_briefing(scheduler, mock_briefing, mock_interface):
    """Digest is skipped if briefing has no actionable content."""
    mock_briefing.build.return_value = ""
    await scheduler.send_digest_for_user(user_id=1)
    mock_interface.send_message.assert_not_called()
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_assistant/test_digest.py -v
```

Expected: FAIL -- `DigestScheduler` does not exist.

**Step 3: Implement `assistant/assistant_svc/digest.py`**

The scheduler:
- `send_digest_for_user(user_id)`: checks Redis for `assistant:digest_sent:{user_id}:{today}`, skips if already sent. Builds briefing, sends via interface if non-empty, sets the sent flag with 48h TTL.
- `check_and_send_all()`: iterates over user_ids, gets each user's timezone from settings, checks if it's the configured hour in their timezone, and calls `send_digest_for_user` if so.
- The main loop calls `check_and_send_all()` every 15 minutes.

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_assistant/test_digest.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add assistant/assistant_svc/digest.py tests/test_assistant/test_digest.py
git commit -m "feat(assistant): add daily digest scheduler"
```

---

## Task 9: Main Entry Point

Wire everything together in `main.py`.

**Files:**
- Create: `assistant/assistant_svc/main.py`
- Test: `tests/test_assistant/test_main.py`

**Step 1: Write the failing tests**

```python
# tests/test_assistant/test_main.py
"""Tests for assistant service main entry point wiring."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_build_agent_wiring():
    """build_components creates all components with correct dependencies."""
    with patch("assistant_svc.main.AssistantConfig") as MockConfig:
        mock_config = MagicMock()
        mock_config.core_api_url = "http://test:8000"
        mock_config.redis_url = "redis://localhost:6379"
        mock_config.openai_api_key = "test-key"
        mock_config.openai_base_url = "https://api.openai.com/v1"
        mock_config.openai_model = "gpt-4o"
        mock_config.context_window_tokens = 128000
        mock_config.briefing_budget_tokens = 5000
        mock_config.response_reserve_tokens = 4000
        mock_config.session_timeout_seconds = 1800
        mock_config.allowed_user_ids = "1,2"
        mock_config.assistant_telegram_bot_token = "test-token"
        mock_config.digest_default_hour = 8
        MockConfig.return_value = mock_config

        from assistant_svc.main import build_components
        components = build_components(mock_config)
        assert "agent" in components
        assert "core_client" in components
        assert "context_manager" in components
        assert "tool_registry" in components
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_assistant/test_main.py -v
```

Expected: FAIL

**Step 3: Implement `assistant/assistant_svc/main.py`**

The main module:

1. `build_components(config) -> dict`: creates all instances:
   - `redis.asyncio.from_url(config.redis_url)`
   - `AssistantCoreClient(config.core_api_url)`
   - `ContextManager(redis, ...token budgets...)`
   - `BriefingBuilder(core_client, context_manager, config.briefing_budget_tokens)`
   - `ToolRegistry()` -- register all 7 tools from `tools/` submodules
   - `openai.AsyncOpenAI(base_url=config.openai_base_url, api_key=config.openai_api_key)`
   - `Agent(openai_client, config.openai_model, core_client, context_manager, briefing_builder, tool_registry)`
   - `TelegramInterface(agent, config.assistant_telegram_bot_token, allowed_user_ids)`
   - `DigestScheduler(redis, briefing_builder, interface, core_client, user_ids, config.digest_default_hour)`

2. `async def run()`: starts the interface and digest scheduler, handles SIGTERM/SIGINT for graceful shutdown.

3. `main()`: calls `load_config()`, `build_components()`, and `asyncio.run(run())`.

4. `if __name__ == "__main__": main()`

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_assistant/test_main.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add assistant/assistant_svc/main.py tests/test_assistant/test_main.py
git commit -m "feat(assistant): add main entry point wiring all components"
```

---

## Task 10: Integration Test

Write an end-to-end test that exercises the full agent flow: user sends message -> briefing is built -> LLM is called with tools -> tool is executed -> response is returned.

**Files:**
- Test: `tests/test_assistant/test_integration.py`

**Step 1: Write the integration test**

```python
# tests/test_assistant/test_integration.py
"""Integration test for the full assistant agent flow."""

import json
import pytest
import pytest_asyncio
import fakeredis.aioredis
from unittest.mock import AsyncMock, MagicMock

from assistant_svc.agent import Agent
from assistant_svc.briefing import BriefingBuilder
from assistant_svc.context import ContextManager
from assistant_svc.core_client import AssistantCoreClient
from assistant_svc.tools import ToolRegistry
from assistant_svc.tools.memories import search_memories, SEARCH_MEMORIES_SCHEMA
from assistant_svc.tools.tasks import list_tasks, LIST_TASKS_SCHEMA


@pytest_asyncio.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest_asyncio.fixture
async def full_agent(redis):
    """Build a full agent stack with mocked external deps (OpenAI + Core API)."""
    # Mock Core API client
    core_client = AsyncMock(spec=AssistantCoreClient)
    core_client.list_tasks.return_value = []
    core_client.list_reminders.return_value = []
    core_client.search_memories.return_value = []
    core_client.get_settings.return_value = MagicMock(timezone="UTC")

    # Real context manager with fake Redis
    ctx = ContextManager(
        redis=redis,
        context_window_tokens=128000,
        briefing_budget_tokens=5000,
        response_reserve_tokens=4000,
        session_timeout_seconds=1800,
    )

    # Real briefing builder with mocked client
    briefing = BriefingBuilder(
        core_client=core_client,
        context_manager=ctx,
        budget_tokens=5000,
    )

    # Real tool registry with mocked client
    registry = ToolRegistry()
    registry.register("search_memories", search_memories, SEARCH_MEMORIES_SCHEMA)
    registry.register("list_tasks", list_tasks, LIST_TASKS_SCHEMA)

    # Mock OpenAI
    mock_openai = AsyncMock()

    agent = Agent(
        openai_client=mock_openai,
        model="gpt-4o",
        core_client=core_client,
        context_manager=ctx,
        briefing_builder=briefing,
        tool_registry=registry,
    )

    return agent, mock_openai, core_client


@pytest.mark.asyncio
async def test_full_conversation_no_tools(full_agent):
    """Simple message that doesn't trigger tool calls."""
    agent, mock_openai, _ = full_agent

    choice = MagicMock()
    choice.message.content = "Hi! I'm your personal assistant."
    choice.message.tool_calls = None
    response = MagicMock()
    response.choices = [choice]
    mock_openai.chat.completions.create.return_value = response

    reply = await agent.handle_message(user_id=1, text="Hello")
    assert reply == "Hi! I'm your personal assistant."


@pytest.mark.asyncio
async def test_full_conversation_with_tool_call(full_agent):
    """Message triggers a tool call, then returns a final answer."""
    agent, mock_openai, core_client = full_agent

    # First LLM call returns tool call
    tool_call = MagicMock()
    tool_call.id = "call_abc"
    tool_call.function.name = "search_memories"
    tool_call.function.arguments = json.dumps({"query": "vacation"})
    first_choice = MagicMock()
    first_choice.message.content = None
    first_choice.message.tool_calls = [tool_call]
    first_choice.message.role = "assistant"
    first_resp = MagicMock()
    first_resp.choices = [first_choice]

    # Second LLM call returns text
    second_choice = MagicMock()
    second_choice.message.content = "You have a vacation planned for March."
    second_choice.message.tool_calls = None
    second_resp = MagicMock()
    second_resp.choices = [second_choice]

    mock_openai.chat.completions.create.side_effect = [first_resp, second_resp]
    core_client.search_memories.return_value = []

    reply = await agent.handle_message(user_id=1, text="Do I have any vacation plans?")
    assert "vacation" in reply.lower()
    assert mock_openai.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_conversation_history_persists(full_agent, redis):
    """Chat history is saved between messages."""
    agent, mock_openai, _ = full_agent

    choice = MagicMock()
    choice.message.content = "Response 1"
    choice.message.tool_calls = None
    resp = MagicMock()
    resp.choices = [choice]
    mock_openai.chat.completions.create.return_value = resp

    await agent.handle_message(user_id=1, text="First message")

    # Verify history was saved
    raw = await redis.get("assistant:chat:1")
    assert raw is not None
    history = json.loads(raw)
    assert len(history) >= 2  # at least user + assistant messages
```

**Step 2: Run the integration tests**

```bash
pytest tests/test_assistant/test_integration.py -v
```

Expected: all PASS

**Step 3: Run the full test suite**

```bash
pytest tests/test_assistant/ -v
```

Expected: all PASS

**Step 4: Commit**

```bash
git add tests/test_assistant/test_integration.py
git commit -m "test(assistant): add integration tests for full agent flow"
```

---

## Task 11: conftest and sys.path Setup

Add a `conftest.py` for the assistant test suite that ensures imports work correctly (same pattern as llm_worker in the root conftest).

**Files:**
- Modify: `tests/conftest.py` -- add assistant path to `sys.path`
- Create: `tests/test_assistant/conftest.py` -- shared fixtures for assistant tests

**Step 1: Update `tests/conftest.py`**

Add after the existing llm_worker path setup:

```python
_assistant_path = os.path.join(PROJECT_ROOT, "assistant")
if _assistant_path not in sys.path:
    sys.path.insert(0, _assistant_path)
```

**Step 2: Create `tests/test_assistant/conftest.py`**

```python
"""Shared fixtures for assistant service tests."""

import pytest_asyncio
import fakeredis.aioredis


@pytest_asyncio.fixture
async def mock_redis():
    """Fake Redis for assistant tests."""
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()
```

**Step 3: Run the full test suite to verify nothing is broken**

```bash
pytest tests/ -v
```

Expected: all existing tests still pass, all new assistant tests pass.

**Step 4: Commit**

```bash
git add tests/conftest.py tests/test_assistant/conftest.py
git commit -m "test(assistant): add conftest with sys.path and shared fixtures"
```

---

## Summary of Tasks

| Task | What it builds | Test file |
|------|---------------|-----------|
| 1 | Project scaffolding, config, Dockerfile, docker-compose | `test_config.py` |
| 2 | Core API HTTP client | `test_core_client.py` |
| 3 | Tool registry + 7 tool definitions | `test_tools.py` |
| 4 | Context manager (Redis history, token counting, summarization trigger) | `test_context.py` |
| 5 | Briefing builder (upcoming tasks/reminders, session summary) | `test_briefing.py` |
| 6 | Agent core (OpenAI tool-calling loop, summarize-and-truncate) | `test_agent.py` |
| 7 | Interface layer (abstract base + Telegram) | `test_interfaces.py` |
| 8 | Digest scheduler (daily morning briefing) | `test_digest.py` |
| 9 | Main entry point (wiring) | `test_main.py` |
| 10 | Integration tests (full flow) | `test_integration.py` |
| 11 | conftest / sys.path setup | (run all tests) |

**Dependency order:** Task 11 should be done first (or alongside Task 1), as all other test files depend on the sys.path setup. Tasks 2-5 can be done in parallel. Task 6 depends on 3, 4, 5. Task 7 depends on 6. Task 8 depends on 5, 7. Task 9 depends on all. Task 10 depends on all.
