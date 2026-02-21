# Sub-phase 3.1: Foundation -- Config, LLM Client, Core API Client, Retry, Utilities

## Context

This is the first sub-phase of Phase 3 (LLM Worker). It builds the foundational components that all handlers and the consumer loop depend on. Nothing in the LLM worker currently works -- `llm_worker/worker/main.py` is a stub that sleeps forever.

**Dependencies from other services (DO NOT modify these, just use them):**
- `shared/shared_lib/config.py` -- `Settings` class pattern using `pydantic_settings.BaseSettings`
- `shared/shared_lib/redis_streams.py` -- `publish()`, `consume()`, `ack()`, `create_consumer_group()` helpers
- `shared/shared_lib/enums.py` -- `JobType`, `JobStatus` enums
- `shared/shared_lib/schemas.py` -- `LLMJobUpdate`, `TagsAddRequest`, `EventCreate`, `TaskResponse`

**Key design decisions:**
- LLM client uses the **OpenAI API** (`/v1/chat/completions`) via the `openai` Python SDK.
- Retry tracking is in-memory (`dict[str, int]`). Resets on worker restart, which is acceptable since unacked Redis messages will be redelivered.
- `extract_json()` handles unreliable LLM output by finding the first `{...}` or `[...]` block via regex before parsing.

---

## Files to Create

### 1. `llm_worker/worker/config.py`

Pydantic settings class for the LLM worker. Follow the pattern in `shared/shared_lib/config.py`.

```python
"""Configuration settings for the LLM Worker service."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMWorkerSettings(BaseSettings):
    """LLM Worker settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    llm_base_url: str = "http://localhost:8080/v1"
    llm_vision_model: str = "llava"
    llm_text_model: str = "mistral"
    llm_api_key: str = "not-needed"
    llm_max_retries: int = 5
    redis_url: str = "redis://redis:6379"
    core_api_url: str = "http://core:8000"
    image_storage_path: str = "/data/images"


def load_llm_worker_settings() -> LLMWorkerSettings:
    """Load and return LLM worker settings."""
    return LLMWorkerSettings()
```

Env var names: `LLM_BASE_URL`, `LLM_VISION_MODEL`, `LLM_TEXT_MODEL`, `LLM_API_KEY`, `LLM_MAX_RETRIES`, `REDIS_URL`, `CORE_API_URL`, `IMAGE_STORAGE_PATH`.

---

### 2. `llm_worker/worker/llm_client.py`

OpenAI-compatible async LLM client.

```python
"""Async LLM client using the OpenAI API."""

import logging

import openai

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when LLM API call fails."""


class LLMClient:
    """Async client for OpenAI-compatible LLM APIs."""

    def __init__(self, base_url: str, api_key: str = "not-needed"):
        self._client = openai.AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=60.0,
        )

    async def complete(self, model: str, prompt: str) -> str:
        """Text completion via /v1/chat/completions.

        Args:
            model: Model name (e.g. "mistral").
            prompt: User prompt text.

        Returns:
            Assistant response text.

        Raises:
            LLMError: On API or connection failure.
        """
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return response.choices[0].message.content or ""
        except (openai.APIError, openai.APIConnectionError) as e:
            raise LLMError(f"LLM API error: {e}") from e

    async def complete_with_image(
        self, model: str, prompt: str, image_b64: str
    ) -> str:
        """Vision completion with base64 image.

        Uses the multi-part content format for vision models.

        Args:
            model: Vision model name (e.g. "llava").
            prompt: Text prompt.
            image_b64: Base64-encoded image string.

        Returns:
            Assistant response text.

        Raises:
            LLMError: On API or connection failure.
        """
        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_b64}"
                                },
                            },
                        ],
                    }
                ],
                temperature=0.3,
                timeout=120.0,
            )
            return response.choices[0].message.content or ""
        except (openai.APIError, openai.APIConnectionError) as e:
            raise LLMError(f"LLM vision API error: {e}") from e

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
```

---

### 3. `llm_worker/worker/core_api_client.py`

HTTP client for the Core REST API. The worker calls these endpoints:
- `PATCH /llm_jobs/{job_id}` -- update job status/result
- `POST /memories/{memory_id}/tags` -- add suggested tags (uses `TagsAddRequest` schema: `{"tags": [...], "status": "suggested"}`)
- `POST /events` -- create pending events (uses `EventCreate` schema: `{"owner_user_id": int, "event_time": str, "description": str, "source_type": "email"}`)
- `GET /tasks?owner_user_id={id}&state=NOT_DONE` -- list open tasks (returns `list[TaskResponse]`)

```python
"""HTTP client for Core REST API."""

import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


class CoreAPIError(Exception):
    """Raised when a Core API call fails."""


class CoreAPIClient:
    """Async HTTP client for Core service REST API."""

    def __init__(self, base_url: str, session: aiohttp.ClientSession):
        self._base_url = base_url.rstrip("/")
        self._session = session

    async def update_job(
        self,
        job_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> None:
        """Update an LLM job via PATCH /llm_jobs/{job_id}."""
        body: dict[str, Any] = {"status": status}
        if result is not None:
            body["result"] = result
        if error_message is not None:
            body["error_message"] = error_message
        url = f"{self._base_url}/llm_jobs/{job_id}"
        async with self._session.patch(url, json=body) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise CoreAPIError(
                    f"PATCH {url} returned {resp.status}: {text}"
                )

    async def add_tags(
        self,
        memory_id: str,
        tags: list[str],
        status: str = "suggested",
    ) -> None:
        """Add tags to a memory via POST /memories/{memory_id}/tags."""
        url = f"{self._base_url}/memories/{memory_id}/tags"
        async with self._session.post(
            url, json={"tags": tags, "status": status}
        ) as resp:
            if resp.status not in (200, 201):
                text = await resp.text()
                raise CoreAPIError(
                    f"POST {url} returned {resp.status}: {text}"
                )

    async def create_event(
        self, event_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Create a pending event via POST /events."""
        url = f"{self._base_url}/events"
        async with self._session.post(url, json=event_data) as resp:
            if resp.status != 201:
                text = await resp.text()
                raise CoreAPIError(
                    f"POST {url} returned {resp.status}: {text}"
                )
            return await resp.json()

    async def get_open_tasks(
        self, user_id: int
    ) -> list[dict[str, Any]]:
        """Get open tasks for a user via GET /tasks."""
        url = f"{self._base_url}/tasks"
        params = {"owner_user_id": user_id, "state": "NOT_DONE"}
        async with self._session.get(url, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise CoreAPIError(
                    f"GET {url} returned {resp.status}: {text}"
                )
            return await resp.json()
```

---

### 4. `llm_worker/worker/retry.py`

In-memory retry tracker with exponential backoff.

```python
"""In-memory retry tracker with exponential backoff."""

import logging

logger = logging.getLogger(__name__)


class RetryTracker:
    """Tracks job retry attempts in memory.

    If the worker restarts, counts reset. This is acceptable because
    unacknowledged Redis messages will be redelivered.
    """

    def __init__(self, max_retries: int = 5):
        self._attempts: dict[str, int] = {}
        self._max_retries = max_retries

    def record_attempt(self, job_id: str) -> int:
        """Increment and return the attempt count for a job."""
        self._attempts[job_id] = self._attempts.get(job_id, 0) + 1
        return self._attempts[job_id]

    def should_retry(self, job_id: str) -> bool:
        """Return True if the job has not exceeded max retries."""
        return self._attempts.get(job_id, 0) < self._max_retries

    def clear(self, job_id: str) -> None:
        """Remove a job from the tracker (on success or final failure)."""
        self._attempts.pop(job_id, None)

    def backoff_seconds(self, job_id: str) -> float:
        """Calculate exponential backoff: min(2^(attempts-1), 60)."""
        attempts = self._attempts.get(job_id, 1)
        return min(2.0 ** (attempts - 1), 60.0)
```

---

### 5. `llm_worker/worker/utils.py`

JSON extraction utility for unreliable LLM output.

```python
"""Utility functions for the LLM Worker."""

import json
import re
import logging

logger = logging.getLogger(__name__)


def extract_json(text: str) -> dict:
    """Extract the first JSON object from text.

    LLMs often wrap JSON in markdown code blocks or add surrounding text.
    This function finds the first {...} block and parses it.

    Args:
        text: Raw text from LLM response.

    Returns:
        Parsed dict from the JSON block.

    Raises:
        ValueError: If no valid JSON object is found.
    """
    # Try parsing the entire text first
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    # Find the first {...} block using brace matching
    match = re.search(r"\{", text)
    if match:
        start = match.start()
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError(f"No valid JSON object found in text: {text[:200]}")
```

---

## Files to Modify

### 6. `llm_worker/pyproject.toml`

**Current state:** Empty dependencies list.

**Change to:**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "life-organiser-llm-worker"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "openai>=1.0.0",
    "aiohttp>=3.9.0",
    "redis[hiredis]>=5.0.0",
    "pydantic-settings>=2.0.0",
    "life-organiser-shared @ file:///${PROJECT_ROOT}/../shared",
]

[tool.hatch.build.targets.wheel]
packages = ["worker"]
```

Note: The path dependency syntax may need adjustment based on how the Docker build context works. In the Dockerfile, `shared/` is copied first and installed separately, so the path dep may not be needed in pyproject.toml for Docker builds. For local dev, use `pip install -e ../shared && pip install -e .`.

---

### 7. `llm_worker/Dockerfile`

**Current state:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY llm_worker/ /app/llm_worker/
RUN pip install --no-cache-dir -e /app/llm_worker/
CMD ["python", "-m", "worker.main"]
```

**Change to:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY shared/ /app/shared/
RUN pip install --no-cache-dir -e /app/shared/
COPY llm_worker/ /app/llm_worker/
RUN pip install --no-cache-dir -e /app/llm_worker/
CMD ["python", "-m", "worker.main"]
```

---

## Test Files to Create

### 8. `tests/test_llm_worker/__init__.py`

Empty file (package marker).

### 9. `tests/test_llm_worker/conftest.py`

Shared fixtures for all LLM worker tests.

```python
"""Shared test fixtures for LLM worker tests."""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio


@pytest.fixture
def mock_llm_client():
    """Mock LLMClient with async methods."""
    client = AsyncMock()
    client.complete = AsyncMock(return_value="")
    client.complete_with_image = AsyncMock(return_value="")
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_core_api():
    """Mock CoreAPIClient with async methods."""
    client = AsyncMock()
    client.update_job = AsyncMock()
    client.add_tags = AsyncMock()
    client.create_event = AsyncMock(return_value={"id": "evt-1"})
    client.get_open_tasks = AsyncMock(return_value=[])
    return client


@pytest_asyncio.fixture
async def mock_redis():
    """Create a fake Redis client for testing."""
    import fakeredis.aioredis

    redis_client = fakeredis.aioredis.FakeRedis()
    yield redis_client
    await redis_client.aclose()


@pytest.fixture
def llm_worker_config():
    """Create a test config with defaults."""
    from worker.config import LLMWorkerSettings

    return LLMWorkerSettings(
        llm_base_url="http://localhost:8080/v1",
        llm_vision_model="test-vision",
        llm_text_model="test-text",
        llm_api_key="test-key",
        llm_max_retries=3,
        redis_url="redis://localhost:6379",
        core_api_url="http://localhost:8000",
        image_storage_path="/tmp/test-images",
    )
```

### 10. `tests/test_llm_worker/test_retry.py`

Pure unit tests, no I/O or mocking needed.

```
Test cases:
- test_record_attempt_increments: record_attempt returns 1, 2, 3...
- test_should_retry_under_limit: True when attempts < max_retries
- test_should_retry_at_limit: False when attempts == max_retries
- test_clear_removes_tracking: After clear, should_retry returns True again
- test_backoff_seconds_exponential: 1, 2, 4, 8, 16, 32, 60, 60 (capped)
- test_backoff_seconds_default: Returns 1.0 for unknown job_id
```

### 11. `tests/test_llm_worker/test_utils.py`

Test extract_json with various LLM outputs.

```
Test cases:
- test_extract_json_clean: '{"key": "value"}' -> {"key": "value"}
- test_extract_json_with_text: 'Here is the result: {"key": "value"} Hope that helps!' -> {"key": "value"}
- test_extract_json_markdown_block: '```json\n{"key": "value"}\n```' -> {"key": "value"}
- test_extract_json_nested: '{"outer": {"inner": [1, 2]}}' -> correctly nested
- test_extract_json_no_json: 'no json here' -> raises ValueError
- test_extract_json_invalid_json: '{broken json}' -> raises ValueError
```

### 12. `tests/test_llm_worker/test_llm_client.py`

Test the LLMClient. Mock the `openai.AsyncOpenAI` client.

```
Test cases:
- test_complete_returns_text: Mock completions.create to return a response, verify text returned
- test_complete_with_image_sends_multipart: Verify the messages list includes image_url content part
- test_complete_raises_llm_error_on_api_error: Mock APIError, verify LLMError raised
- test_complete_raises_llm_error_on_connection_error: Mock APIConnectionError, verify LLMError raised
```

### 13. `tests/test_llm_worker/test_core_api_client.py`

Test with `aioresponses` to mock HTTP.

```
Test cases:
- test_update_job_success: Mock PATCH 200, verify correct URL and body
- test_update_job_error: Mock PATCH 500, verify CoreAPIError raised
- test_add_tags_success: Mock POST 201, verify body is {"tags": [...], "status": "suggested"}
- test_create_event_success: Mock POST 201, verify returns parsed JSON
- test_get_open_tasks_success: Mock GET 200, verify query params include owner_user_id and state=NOT_DONE
- test_get_open_tasks_empty: Mock GET 200 with [], verify returns empty list
```

---

## Checkpoint

After this sub-phase is complete, verify:

1. `pytest tests/test_llm_worker/test_retry.py` -- all pass
2. `pytest tests/test_llm_worker/test_utils.py` -- all pass
3. `pytest tests/test_llm_worker/test_llm_client.py` -- all pass
4. `pytest tests/test_llm_worker/test_core_api_client.py` -- all pass
5. `pytest tests/test_core/` -- no regressions (nothing in core changed yet)

---

## Code Conventions (match existing codebase)

- Async throughout: `async def`, `await`
- Type hints on all function signatures
- Max 100 char line length, double quotes, f-strings
- Logger per module: `logger = logging.getLogger(__name__)`
- Imports: stdlib, then third-party, then first-party, alphabetical within groups
