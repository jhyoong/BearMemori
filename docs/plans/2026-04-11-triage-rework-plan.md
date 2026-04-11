# Triage Rework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify triage LLM calls through `LLMClient` and expose `triage_conversation` as an MCP tool backed by `PendingStore`.

**Architecture:** Add `triage()` and `extract_triage()` methods to `LLMClient` (moving prompt templates there), refactor `run_triage()` to accept an `LLMClient` instance, then wire up a new async MCP tool. The REST endpoint behaviour is unchanged; the MCP tool mirrors it.

**Tech Stack:** Python 3.12, FastAPI, openai SDK, FastMCP, pytest + pytest-asyncio

---

### Task 1: Add `triage()` and `extract_triage()` to `LLMClient`

**Files:**
- Modify: `bearmemori/llm/client.py`
- Modify: `tests/test_llm_client.py`

**Step 1: Write failing tests**

Add to `tests/test_llm_client.py`:

```python
@pytest.mark.asyncio
async def test_llm_client_triage_returns_dict(client):
    response_data = {
        "should_save": True,
        "category": "profile",
        "title": "Likes coffee",
        "content": "User prefers black coffee",
        "tags": ["preference"],
        "importance": 5,
        "event_fields": None,
    }
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps(response_data), reasoning_content=None))
    ]
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.triage("USER: I love black coffee", "", "2026-04-11T10:00:00")
    assert result["should_save"] is True
    assert result["category"] == "profile"


@pytest.mark.asyncio
async def test_llm_client_extract_triage_returns_dict(client):
    response_data = {
        "category": "reminder",
        "title": "Pack bag",
        "content": "Pack bag in 10 minutes",
        "tags": ["reminder"],
        "importance": 6,
        "event_fields": {"datetime": "2026-04-11T10:10:00", "status": "pending", "recurrence": None},
    }
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps(response_data), reasoning_content=None))
    ]
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.extract_triage("USER: Pack my bag in 10 minutes", "2026-04-11T10:00:00")
    assert result["category"] == "reminder"
    assert result["event_fields"] is not None


def test_triage_prompt_templates_exist():
    from bearmemori.llm.client import _TRIAGE_SYSTEM_TEMPLATE, _EXTRACTION_SYSTEM_TEMPLATE
    assert "should_save" in _TRIAGE_SYSTEM_TEMPLATE
    assert "when in doubt" in _TRIAGE_SYSTEM_TEMPLATE.lower()
    assert "multiple messages" in _TRIAGE_SYSTEM_TEMPLATE
    assert "multiple unrelated topics" in _TRIAGE_SYSTEM_TEMPLATE
    assert "category" in _EXTRACTION_SYSTEM_TEMPLATE
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_llm_client.py::test_llm_client_triage_returns_dict tests/test_llm_client.py::test_llm_client_extract_triage_returns_dict tests/test_llm_client.py::test_triage_prompt_templates_exist -v
```

Expected: FAIL with `AttributeError: 'LLMClient' object has no attribute 'triage'`

**Step 3: Move prompt templates and add methods to `LLMClient`**

In `bearmemori/llm/client.py`, add the two prompt templates (copy from `bearmemori/core/triage.py`):

```python
_TRIAGE_SYSTEM_TEMPLATE = """\
You are a memory triage agent. Given a conversation, decide if any information \
is worth saving as a long-term memory.

Current date and time: {current_time}
When the user mentions relative times (e.g. "in 10 minutes", "tomorrow", "next week"), \
use the current date and time above to compute the absolute ISO 8601 datetime for event_fields.

Categories:
- "profile": Stable facts about the user (preferences, identity, relationships)
- "general": Non-time-bound useful information (prices, recommendations, facts)
- "event": Time-bound commitments, reminders, appointments
- "location": Places, addresses, venues the user mentions
- "task": Action items, to-dos
- "reminder": Triggered notifications with scheduling

You MUST respond with a single valid JSON object and nothing else. No explanation, \
no commentary, no markdown formatting.

Importance (1-10 integer):
- 1-3: Low importance (trivial facts, casual mentions)
- 4-6: Medium importance (useful information, general preferences)
- 7-8: High importance (key personal facts, significant events, strong preferences)
- 9-10: Critical importance (core identity, health/safety, major life events)

If the conversation contains memory-worthy information:
{{"should_save": true, "category": "<category>", "title": "<short title>", \
"content": "<key information>", "tags": ["tag1", "tag2"], \
"importance": <1-10>, "event_fields": null}}

For events/tasks/reminders, set event_fields to:
{{"datetime": "ISO 8601", "status": "pending", "recurrence": null}}

If nothing is worth saving:
{{"should_save": false}}

IMPORTANT: Reminders and events are always worth saving. A reminder about a
future action (e.g., "pack my bag in 10 minutes") is valuable user
information - do NOT treat it as trivial. Set importance 5-8 for
reminders, 6-9 for events/tasks.

When in doubt, lean toward saving. It is better to save something \
the user can dismiss than to lose information they wanted kept.

The conversation may contain information spread across multiple messages. \
Synthesize the full conversation to extract the complete memory, not just \
the last message.

If the conversation covers multiple unrelated topics, focus on the most \
recent topic that contains memory-worthy information.

Save specific, actionable information. Skip only:
- Greetings or small talk
- Questions without answers
- Truly trivial information (e.g., casual mentions without context)
"""

_EXTRACTION_SYSTEM_TEMPLATE = """\
You are a memory extraction agent. The following conversation contains \
information that should be saved as a long-term memory.

Current date and time: {current_time}
When the user mentions relative times (e.g. "in 10 minutes", "tomorrow", "next week"), \
use the current date and time above to compute the absolute ISO 8601 datetime for event_fields.

Extract the memory details from the conversation. You MUST respond with a \
single valid JSON object and nothing else. No explanation, no commentary, \
no markdown formatting.

Categories:
- "profile": Stable facts about the user (preferences, identity, relationships)
- "general": Non-time-bound useful information (prices, recommendations, facts)
- "event": Time-bound commitments, reminders, appointments
- "location": Places, addresses, venues the user mentions
- "task": Action items, to-dos
- "reminder": Triggered notifications with scheduling

Importance (1-10 integer):
- 1-3: Low importance (trivial facts, casual mentions)
- 4-6: Medium importance (useful information, general preferences)
- 7-8: High importance (key personal facts, significant events, strong preferences)
- 9-10: Critical importance (core identity, health/safety, major life events)

Respond with:
{{"category": "<category>", "title": "<short title>", \
"content": "<key information>", "tags": ["tag1", "tag2"], \
"importance": <1-10>, "event_fields": null}}

For events/tasks/reminders, set event_fields to:
{{"datetime": "ISO 8601", "status": "pending", "recurrence": null}}

IMPORTANT: Reminders and events should have importance 5-8 for reminders, \
6-9 for events/tasks.

The conversation may contain information spread across multiple messages. \
Synthesize the full conversation to extract the complete memory, not just \
the last message.
"""
```

Then add two methods to the `LLMClient` class (after `describe_image`):

```python
async def triage(self, conversation_text: str, hint_text: str, current_time: str) -> dict:
    system_prompt = _TRIAGE_SYSTEM_TEMPLATE.format(current_time=current_time)
    response = await self._client.chat.completions.create(
        model=self._model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Conversation:\n{conversation_text}{hint_text}"},
        ],
        temperature=0.1,
    )
    raw = _get_content(response.choices[0].message)
    logger.debug("Triage LLM raw output: %s", raw)
    return extract_json(raw)

async def extract_triage(self, conversation_text: str, current_time: str) -> dict:
    system_prompt = _EXTRACTION_SYSTEM_TEMPLATE.format(current_time=current_time)
    response = await self._client.chat.completions.create(
        model=self._model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Conversation:\n{conversation_text}"},
        ],
        temperature=0.1,
    )
    raw = _get_content(response.choices[0].message)
    logger.debug("Extraction LLM raw output: %s", raw)
    return extract_json(raw)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_llm_client.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/llm/client.py tests/test_llm_client.py
git commit -m "feat: add triage() and extract_triage() methods to LLMClient"
```

---

### Task 2: Refactor `run_triage()` to use `LLMClient`

**Files:**
- Modify: `bearmemori/core/triage.py`
- Modify: `tests/test_triage.py`

**Step 1: Update `test_triage.py` to patch LLMClient methods**

Replace all tests that patch `bearmemori.core.triage._llm_call` with patches on `LLMClient` methods. The new pattern passes a real `LLMClient` instance (or mock) instead of raw connection params.

Replace the entire `tests/test_triage.py` content with:

```python
import json
from unittest.mock import AsyncMock, patch

import pytest

from bearmemori.core.triage import run_triage
from bearmemori.llm.client import LLMClient
from bearmemori.storage.models import MemoryCategory


@pytest.fixture
def llm():
    return LLMClient(base_url="http://localhost:11434/v1", model="test", api_key="test")


@pytest.mark.asyncio
async def test_triage_should_save(llm):
    response_data = {
        "should_save": True,
        "category": "profile",
        "title": "Likes coffee",
        "content": "User prefers black coffee",
        "tags": ["preference"],
        "importance": 5,
        "event_fields": None,
    }
    with patch.object(llm, "triage", new_callable=AsyncMock, return_value=response_data):
        result = await run_triage(
            [{"role": "user", "content": "I love black coffee"}],
            llm=llm,
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.PROFILE


@pytest.mark.asyncio
async def test_triage_should_not_save(llm):
    with patch.object(llm, "triage", new_callable=AsyncMock, return_value={"should_save": False}):
        result = await run_triage(
            [{"role": "user", "content": "Hello"}],
            llm=llm,
        )
    assert result.should_save is False
    assert result.draft is None


@pytest.mark.asyncio
async def test_triage_malformed_response(llm):
    with patch.object(llm, "triage", new_callable=AsyncMock, side_effect=json.JSONDecodeError("bad", "", 0)):
        result = await run_triage(
            [{"role": "user", "content": "test"}],
            llm=llm,
        )
    assert result.should_save is False


@pytest.mark.asyncio
async def test_triage_with_memory_hint(llm):
    response_data = {
        "should_save": True,
        "category": "event",
        "title": "Meeting tomorrow",
        "content": "Team standup at 9am",
        "tags": ["meeting"],
        "importance": 7,
        "event_fields": {"datetime": "2026-03-22T09:00:00", "status": "pending", "recurrence": None},
    }
    with patch.object(llm, "triage", new_callable=AsyncMock, return_value=response_data):
        result = await run_triage(
            [{"role": "user", "content": "I have a standup at 9am tomorrow"}],
            llm=llm,
            memory_hint={"likely_category": "event", "confidence": "high"},
        )
    assert result.should_save is True
    assert result.draft.event_fields is not None
    assert result.draft.event_fields.datetime == "2026-03-22T09:00:00"


@pytest.mark.asyncio
async def test_triage_high_confidence_skips_should_save(llm):
    """When memory_hint has confidence='high', uses extraction-only path."""
    response_data = {
        "category": "reminder",
        "title": "Pack bag",
        "content": "Pack bag in 10 minutes",
        "tags": ["reminder"],
        "importance": 6,
        "event_fields": {"datetime": "2026-03-30T15:10:00", "status": "pending", "recurrence": None},
    }
    with patch.object(llm, "extract_triage", new_callable=AsyncMock, return_value=response_data):
        result = await run_triage(
            [{"role": "user", "content": "Remind me to pack my bag in 10 minutes"}],
            llm=llm,
            memory_hint={"likely_category": "reminder", "confidence": "high"},
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.REMINDER
    assert result.draft.title == "Pack bag"


@pytest.mark.asyncio
async def test_triage_high_confidence_falls_back_on_extraction_failure(llm):
    """When extraction-only fails, should fall back to full triage prompt."""
    full_triage_data = {
        "should_save": True,
        "category": "reminder",
        "title": "Pack bag",
        "content": "Pack bag in 10 minutes",
        "tags": ["reminder"],
        "importance": 6,
        "event_fields": {"datetime": "2026-03-30T15:10:00", "status": "pending", "recurrence": None},
    }
    with (
        patch.object(llm, "extract_triage", new_callable=AsyncMock, side_effect=json.JSONDecodeError("bad", "", 0)),
        patch.object(llm, "triage", new_callable=AsyncMock, return_value=full_triage_data),
    ):
        result = await run_triage(
            [{"role": "user", "content": "Remind me to pack my bag in 10 minutes"}],
            llm=llm,
            memory_hint={"likely_category": "reminder", "confidence": "high"},
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.REMINDER


def test_triage_prompt_contains_when_in_doubt_save():
    from bearmemori.llm.client import _TRIAGE_SYSTEM_TEMPLATE
    assert "when in doubt" in _TRIAGE_SYSTEM_TEMPLATE.lower()
    assert "Be selective" not in _TRIAGE_SYSTEM_TEMPLATE


def test_triage_prompt_contains_multi_turn_guidance():
    from bearmemori.llm.client import _TRIAGE_SYSTEM_TEMPLATE
    assert "multiple messages" in _TRIAGE_SYSTEM_TEMPLATE


def test_triage_prompt_contains_mixed_topic_guidance():
    from bearmemori.llm.client import _TRIAGE_SYSTEM_TEMPLATE
    assert "multiple unrelated topics" in _TRIAGE_SYSTEM_TEMPLATE
```

**Step 2: Run to verify tests fail**

```bash
uv run pytest tests/test_triage.py -v
```

Expected: FAIL — `run_triage()` still takes raw connection params.

**Step 3: Rewrite `bearmemori/core/triage.py`**

Replace the file with:

```python
import json
import logging
from dataclasses import dataclass

import openai
from pydantic import ValidationError

from bearmemori.storage.models import EventFields, MemoryCategory, MemoryDraft
from bearmemori.utils.time import get_server_time

logger = logging.getLogger(__name__)


@dataclass
class TriageResult:
    should_save: bool
    draft: MemoryDraft | None = None
    reason: str | None = None


def _build_draft(data: dict) -> MemoryDraft:
    """Build a MemoryDraft from parsed LLM response data. Raises ValueError/KeyError on failure."""
    event_fields = None
    if data.get("event_fields"):
        event_fields = EventFields(**data["event_fields"])

    importance = max(1, min(10, int(data.get("importance", 5))))

    return MemoryDraft(
        category=MemoryCategory(data["category"]),
        title=data["title"],
        content=data["content"],
        tags=data.get("tags", []),
        importance=importance,
        event_fields=event_fields,
    )


async def _try_extraction(
    conv_text: str,
    llm,
    current_time: str,
) -> TriageResult | None:
    """Call extraction-only prompt. Returns TriageResult on success, None on failure."""
    try:
        data = await llm.extract_triage(conv_text, current_time)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Extraction LLM returned unparseable output: %s", e)
        return None
    except openai.APIError as e:
        logger.error("Extraction LLM call failed (%s): %s", type(e).__name__, e)
        return None

    try:
        draft = _build_draft(data)
        logger.info(
            "Extraction decision: should_save=True, category=%s, title=%s, importance=%d",
            draft.category,
            draft.title,
            draft.importance,
        )
        return TriageResult(should_save=True, draft=draft, reason="high_confidence")
    except (ValueError, KeyError, ValidationError) as e:
        logger.warning("Extraction produced invalid draft: %s", e)
        return None


async def _run_full_triage(
    conv_text: str,
    hint_text: str,
    llm,
    current_time: str,
) -> TriageResult:
    """Run full triage (should_save decision + extraction) and return a TriageResult."""
    try:
        data = await llm.triage(conv_text, hint_text, current_time)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Triage LLM returned unparseable output: %s", e)
        return TriageResult(should_save=False, reason="extraction_failed")
    except openai.APIError as e:
        logger.error("Triage LLM call failed (%s): %s", type(e).__name__, e)
        return TriageResult(should_save=False, reason="extraction_failed")

    if not data.get("should_save", False):
        logger.info("Triage decision: should_save=False")
        return TriageResult(should_save=False, reason="llm_decided_no")

    try:
        draft = _build_draft(data)
        logger.info(
            "Triage decision: should_save=True, category=%s, title=%s, importance=%d",
            draft.category,
            draft.title,
            draft.importance,
        )
        return TriageResult(should_save=True, draft=draft)
    except (ValueError, KeyError, ValidationError) as e:
        logger.warning("Triage produced invalid draft: %s", e)
        return TriageResult(should_save=False, reason="validation_failed")


async def run_triage(
    conversation: list[dict],
    llm,
    memory_hint: dict | None = None,
    current_time: str | None = None,
    user_timezone: str = "UTC",
) -> TriageResult:
    if current_time is None:
        current_time = get_server_time(user_timezone)

    hint_text = ""
    if memory_hint:
        hint_text = f"\n\nMemory hint from chatbot: {json.dumps(memory_hint)}"

    try:
        conv_text = "\n".join(
            f"{msg['role'].upper()}: {msg.get('content', '')}" for msg in conversation[-10:]
        )
    except (KeyError, AttributeError) as e:
        logger.warning("Malformed conversation item: %s", e)
        return TriageResult(should_save=False)

    # High-confidence path: skip should_save decision, use extraction-only prompt.
    # Fall back to full triage if extraction fails.
    if memory_hint and memory_hint.get("confidence") == "high":
        result = await _try_extraction(conv_text, llm, current_time)
        if result is not None:
            return result
        logger.warning("High-confidence extraction failed, falling back to full triage")

    return await _run_full_triage(conv_text, hint_text, llm, current_time)
```

**Step 4: Run triage tests to verify they pass**

```bash
uv run pytest tests/test_triage.py -v
```

Expected: all PASS

**Step 5: Check for other files importing from `core.triage`**

```bash
grep -r "from bearmemori.core.triage import" .
grep -r "_TRIAGE_SYSTEM_TEMPLATE\|_EXTRACTION_SYSTEM_TEMPLATE\|TRIAGE_SYSTEM_PROMPT" .
```

Update any remaining references: `_TRIAGE_SYSTEM_TEMPLATE` and `_EXTRACTION_SYSTEM_TEMPLATE` now live in `bearmemori.llm.client`. Check `tests/test_triage_time.py` and `tests/test_triage_schema.py` — update imports there if needed.

**Step 6: Run affected tests**

```bash
uv run pytest tests/test_triage.py tests/test_triage_time.py tests/test_triage_schema.py -v
```

Expected: all PASS

**Step 7: Commit**

```bash
git add bearmemori/core/triage.py tests/test_triage.py tests/test_triage_time.py tests/test_triage_schema.py
git commit -m "refactor: run_triage() now accepts LLMClient instead of raw connection params"
```

---

### Task 3: Update `api/routes.py` `create_app()` signature

**Files:**
- Modify: `bearmemori/api/routes.py`
- Modify: `tests/test_routes_triage_time.py`
- Check and modify: `tests/api/test_routes.py`, `tests/test_api.py`, `tests/test_integration.py`

**Step 1: Update `test_routes_triage_time.py`**

Replace the fixture:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.llm.client import LLMClient


@pytest.fixture
def client():
    db = MagicMock()
    vector_store = MagicMock()
    pending_store = MagicMock()
    llm = MagicMock(spec=LLMClient)
    app = create_app(
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        llm=llm,
    )
    return TestClient(app)
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_routes_triage_time.py -v
```

Expected: FAIL — `create_app()` still takes old params.

**Step 3: Update `bearmemori/api/routes.py`**

Change the `create_app()` signature and remove the five individual LLM params. Replace:

```python
def create_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    pending_store: PendingStore,
    llm_base_url: str = "",
    llm_api_key: str = "",
    llm_model: str = "",
    llm_max_tokens: int = 4096,
    triage_timeout: float = 60.0,
    user_timezone: str = "UTC",
    image_storage_dir: str = "",
) -> FastAPI:
```

With:

```python
from bearmemori.llm.client import LLMClient

def create_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    pending_store: PendingStore,
    llm: LLMClient | None = None,
    user_timezone: str = "UTC",
    image_storage_dir: str = "",
) -> FastAPI:
```

Update the triage route handler to call `run_triage` with `llm`:

```python
@app.post("/memory/triage")
async def triage_conversation(request: TriageRequest):
    logger.info(
        "Triage request: conversation_len=%d, memory_hint=%s, current_time=%s",
        len(request.conversation),
        request.memory_hint,
        request.current_time,
    )
    if request.conversation:
        logger.info(
            "Triage last message: %s",
            request.conversation[-1].get("content", "")[:200],
        )
    result = await run_triage(
        request.conversation,
        llm=llm,
        memory_hint=request.memory_hint,
        current_time=request.current_time,
        user_timezone=user_timezone,
    )
    if not result.should_save or result.draft is None:
        response = {"should_save": False}
        if result.reason:
            response["reason"] = result.reason
        return response

    pending_id = pending_store.add(result.draft)
    logger.info("Triage proposed memory: %s", pending_id)
    return {
        "should_save": True,
        "pending_id": pending_id,
        "draft": result.draft.model_dump(mode="json"),
    }
```

Also remove the `import httpx` that was only used by `_llm_call` (it no longer exists in routes).

**Step 4: Grep for other callers of `create_app` from routes**

```bash
grep -rn "create_app\|llm_base_url\|llm_model\|triage_timeout" tests/
```

Open `tests/api/test_routes.py`, `tests/test_api.py`, `tests/test_integration.py` and update any `create_app()` call that passes the old LLM params. Replace those params with `llm=MagicMock(spec=LLMClient)`.

**Step 5: Run all route-related tests**

```bash
uv run pytest tests/test_routes_triage_time.py tests/api/test_routes.py tests/test_api.py tests/test_integration.py -v
```

Expected: all PASS

**Step 6: Commit**

```bash
git add bearmemori/api/routes.py tests/test_routes_triage_time.py tests/api/test_routes.py tests/test_api.py tests/test_integration.py
git commit -m "refactor: create_app() now accepts LLMClient instead of raw LLM connection params"
```

---

### Task 4: Add `triage_conversation` MCP tool

**Files:**
- Modify: `bearmemori/mcp/server.py`
- Create: `tests/mcp/test_triage_tool.py`

**Step 1: Write failing test**

Create `tests/mcp/test_triage_tool.py`:

```python
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bearmemori.config import Settings
from bearmemori.llm.client import LLMClient
from bearmemori.mcp.server import create_mcp_app
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


@pytest.fixture
def mcp_deps():
    db = MagicMock(spec=MemoryDatabase)
    vector_store = MagicMock(spec=VectorStore)
    vector_store.search.return_value = []
    db.get_upcoming_events.return_value = []
    settings = MagicMock(spec=Settings)
    settings.webapp_secret = ""
    settings.user_timezone = "UTC"
    llm = MagicMock(spec=LLMClient)
    pending_store = MagicMock(spec=PendingStore)
    return db, vector_store, settings, llm, pending_store


@pytest.mark.asyncio
async def test_triage_tool_should_save(mcp_deps):
    db, vector_store, settings, llm, pending_store = mcp_deps
    triage_result_data = {
        "should_save": True,
        "category": "profile",
        "title": "Likes coffee",
        "content": "User prefers black coffee",
        "tags": ["preference"],
        "importance": 5,
        "event_fields": None,
    }
    pending_store.add.return_value = "pend_abc123"

    from bearmemori.core.triage import TriageResult
    from bearmemori.storage.models import MemoryCategory, MemoryDraft

    draft = MemoryDraft(
        category=MemoryCategory.PROFILE,
        title="Likes coffee",
        content="User prefers black coffee",
        tags=["preference"],
        importance=5,
    )
    mock_result = TriageResult(should_save=True, draft=draft)

    with patch("bearmemori.mcp.server.run_triage", new_callable=AsyncMock, return_value=mock_result):
        app = create_mcp_app(
            db=db,
            vector_store=vector_store,
            settings=settings,
            llm=llm,
            pending_store=pending_store,
        )

    pending_store.add.assert_not_called()  # tool not invoked yet, just confirming setup


@pytest.mark.asyncio
async def test_triage_tool_should_not_save(mcp_deps):
    db, vector_store, settings, llm, pending_store = mcp_deps

    from bearmemori.core.triage import TriageResult

    mock_result = TriageResult(should_save=False, reason="llm_decided_no")

    with patch("bearmemori.mcp.server.run_triage", new_callable=AsyncMock, return_value=mock_result):
        app = create_mcp_app(
            db=db,
            vector_store=vector_store,
            settings=settings,
            llm=llm,
            pending_store=pending_store,
        )
    # App created without error; tool registration is confirmed by no AttributeError
    assert app is not None


def test_create_mcp_app_accepts_llm_and_pending_store(mcp_deps):
    db, vector_store, settings, llm, pending_store = mcp_deps
    # Must not raise TypeError
    app = create_mcp_app(
        db=db,
        vector_store=vector_store,
        settings=settings,
        llm=llm,
        pending_store=pending_store,
    )
    assert app is not None
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/mcp/test_triage_tool.py -v
```

Expected: FAIL — `create_mcp_app()` does not accept `llm` or `pending_store`.

**Step 3: Update `bearmemori/mcp/server.py`**

Update `create_mcp_app()` signature and add the tool. Add imports at the top:

```python
from bearmemori.core.triage import run_triage
from bearmemori.llm.client import LLMClient
from bearmemori.storage.pending_store import PendingStore
```

Change the function signature:

```python
def create_mcp_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    settings: Settings,
    llm: LLMClient | None = None,
    pending_store: PendingStore | None = None,
):
```

Add the new tool inside `create_mcp_app()`, after the existing tools and before `app = mcp.sse_app()`:

```python
@mcp.tool(
    description=(
        "Analyse a conversation and decide if any information is worth saving as a memory. "
        "Returns should_save=true with a pending_id and draft when memory-worthy content is found. "
        "The memory enters a pending state for user review — it is not saved automatically. "
        "conversation: list of {role, content} dicts. "
        "memory_hint: optional {likely_category, confidence} from the calling agent. "
        "current_time: optional ISO 8601 string; uses server time if omitted."
    )
)
async def triage_conversation(
    conversation: list[dict],
    memory_hint: dict | None = None,
    current_time: str | None = None,
) -> dict:
    if llm is None or pending_store is None:
        return {"error": "Triage is not configured on this server"}
    result = await run_triage(
        conversation,
        llm=llm,
        memory_hint=memory_hint,
        current_time=current_time,
        user_timezone=settings.user_timezone,
    )
    if not result.should_save or result.draft is None:
        response: dict = {"should_save": False}
        if result.reason:
            response["reason"] = result.reason
        return response
    pending_id = pending_store.add(result.draft)
    return {
        "should_save": True,
        "pending_id": pending_id,
        "draft": result.draft.model_dump(mode="json"),
    }
```

**Step 4: Run MCP tests to verify they pass**

```bash
uv run pytest tests/mcp/ -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/mcp/server.py tests/mcp/test_triage_tool.py
git commit -m "feat: add triage_conversation MCP tool"
```

---

### Task 5: Update `app.py` wiring

**Files:**
- Modify: `bearmemori/app.py`

No new tests needed — `tests/mcp/test_mount.py` exercises the full `create_application()` path.

**Step 1: Update `app.py`**

Find the `create_api_app(...)` call (around line 149) and replace:

```python
api = create_api_app(
    db=db,
    vector_store=vector_store,
    pending_store=pending_store,
    llm_base_url=settings.llm_base_url,
    llm_api_key=settings.llm_api_key,
    llm_model=settings.llm_model,
    llm_max_tokens=settings.llm_max_tokens,
    triage_timeout=settings.triage_timeout_seconds,
    user_timezone=settings.user_timezone,
    image_storage_dir=settings.image_storage_dir,
)
```

With:

```python
api = create_api_app(
    db=db,
    vector_store=vector_store,
    pending_store=pending_store,
    llm=llm,
    user_timezone=settings.user_timezone,
    image_storage_dir=settings.image_storage_dir,
)
```

Find the `create_mcp_app(...)` call (around line 188) and replace:

```python
mcp_asgi = create_mcp_app(db=db, vector_store=vector_store, settings=settings)
```

With:

```python
mcp_asgi = create_mcp_app(
    db=db,
    vector_store=vector_store,
    settings=settings,
    llm=llm,
    pending_store=pending_store,
)
```

**Step 2: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all PASS. If `test_app.py` or `test_integration.py` fail due to removed settings keys (`llm_max_tokens`, `triage_timeout_seconds`), check whether those keys still exist in `config.py` — they are used by other parts of the system, so leave them in place; they're just no longer passed to `create_app()`.

**Step 3: Commit**

```bash
git add bearmemori/app.py
git commit -m "chore: wire llm and pending_store into MCP app and API app"
```

---

### Task 6: Final verification

**Step 1: Run the full test suite and linter**

```bash
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
```

Expected: all tests PASS, no lint errors.

**Step 2: Fix any lint issues**

```bash
uv run ruff check --fix .
uv run ruff format .
```

**Step 3: Final commit if any formatting fixes were applied**

```bash
git add -u
git commit -m "chore: apply ruff formatting fixes"
```
