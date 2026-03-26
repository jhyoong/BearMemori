# Memory Importance Field & Telegram Menu Commands -- Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a 1-10 importance score to memories (LLM-assigned, user-overridable) that affects context construction, and add /search, /list, /help commands to the Telegram bot.

**Architecture:** The importance field flows through the entire memory pipeline: LLM extraction -> pending preview -> confirmation -> database -> vector store metadata -> context retrieval. Telegram commands add three new CommandHandlers that query the existing storage layer directly.

**Tech Stack:** Python 3.12+, SQLite, ChromaDB, python-telegram-bot, pydantic, FastAPI

---

### Task 1: Add importance field to data models

**Files:**
- Modify: `bearmemori/storage/models.py:30-76`

**Step 1: Write the failing test**

Create `tests/test_importance_models.py`:

```python
from datetime import UTC, datetime

from bearmemori.storage.models import (
    MemoryCategory,
    MemoryDraft,
    MemoryRecord,
    PendingMemory,
)


def test_memory_record_default_importance():
    record = MemoryRecord(
        id="mem_test",
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        created_at=datetime.now(UTC),
    )
    assert record.importance == 5


def test_memory_record_custom_importance():
    record = MemoryRecord(
        id="mem_test",
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        created_at=datetime.now(UTC),
        importance=9,
    )
    assert record.importance == 9


def test_memory_draft_default_importance():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
    )
    assert draft.importance == 5


def test_memory_draft_custom_importance():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        importance=8,
    )
    assert draft.importance == 8


def test_pending_memory_importance():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        importance=7,
    )
    pending = PendingMemory(
        pending_id="pend_test",
        draft=draft,
        ttl_seconds=3600,
    )
    assert pending.draft.importance == 7


def test_from_draft_preserves_importance():
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        importance=8,
    )
    record = MemoryRecord.from_draft(draft, "mem_test")
    assert record.importance == 8
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_importance_models.py -v`
Expected: FAIL -- `importance` field not recognized

**Step 3: Write minimal implementation**

In `bearmemori/storage/models.py`:

Add `importance: int = 5` to `MemoryDraft` (line 36, after `tags`):
```python
class MemoryDraft(BaseModel):
    category: MemoryCategory
    title: str
    content: str
    event_fields: EventFields | None = None
    tags: list[str] = Field(default_factory=list)
    importance: int = 5
    source: MemorySource | None = None
```

Add `importance: int = 5` to `MemoryRecord` (line 49, after `tags`):
```python
class MemoryRecord(BaseModel):
    id: str
    category: MemoryCategory
    title: str
    content: str
    created_at: datetime
    raw_input: str = ""
    event_fields: EventFields | None = None
    tags: list[str] = Field(default_factory=list)
    importance: int = 5
    source: MemorySource | None = None
    metadata: dict = Field(default_factory=dict)
    needs_review: bool = False
    image_path: str | None = None
```

Update `from_draft` to pass through importance:
```python
@classmethod
def from_draft(cls, draft: MemoryDraft, record_id: str) -> MemoryRecord:
    return cls(
        id=record_id,
        category=draft.category,
        title=draft.title,
        content=draft.content,
        created_at=datetime.now(UTC),
        event_fields=draft.event_fields,
        tags=draft.tags,
        importance=draft.importance,
        source=draft.source,
        needs_review=False,
    )
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_importance_models.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All existing tests still pass

**Step 6: Commit**

```bash
git add bearmemori/storage/models.py tests/test_importance_models.py
git commit -m "feat: add importance field to MemoryDraft and MemoryRecord models"
```

---

### Task 2: Add importance column to SQLite database

**Files:**
- Modify: `bearmemori/storage/database.py:28-104` (schema, migration, _row_to_record)
- Modify: `bearmemori/storage/database.py:134-170` (create method)
- Modify: `bearmemori/storage/database.py:247-281` (update method)

**Step 1: Write the failing test**

Create `tests/test_importance_storage.py`:

```python
from datetime import UTC, datetime

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryRecord


def test_store_and_retrieve_importance(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()

    record = MemoryRecord(
        id="mem_imp_test",
        category=MemoryCategory.GENERAL,
        title="Important memory",
        content="This is very important",
        created_at=datetime.now(UTC),
        importance=9,
    )
    db.create(record)
    retrieved = db.get("mem_imp_test")

    assert retrieved is not None
    assert retrieved.importance == 9


def test_default_importance_is_5(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()

    record = MemoryRecord(
        id="mem_def_test",
        category=MemoryCategory.GENERAL,
        title="Default importance",
        content="Should default to 5",
        created_at=datetime.now(UTC),
    )
    db.create(record)
    retrieved = db.get("mem_def_test")

    assert retrieved is not None
    assert retrieved.importance == 5


def test_update_importance(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()

    record = MemoryRecord(
        id="mem_upd_test",
        category=MemoryCategory.GENERAL,
        title="Update test",
        content="Will update importance",
        created_at=datetime.now(UTC),
        importance=3,
    )
    db.create(record)

    record.importance = 8
    db.update(record)

    retrieved = db.get("mem_upd_test")
    assert retrieved is not None
    assert retrieved.importance == 8


def test_migration_adds_importance_column(tmp_path):
    """Existing databases without importance column should get it via migration."""
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()

    # Insert a record, then verify importance defaults correctly
    record = MemoryRecord(
        id="mem_mig_test",
        category=MemoryCategory.GENERAL,
        title="Migration test",
        content="Pre-migration record",
        created_at=datetime.now(UTC),
    )
    db.create(record)
    retrieved = db.get("mem_mig_test")
    assert retrieved.importance == 5
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_importance_storage.py -v`
Expected: FAIL -- importance column doesn't exist in SQL

**Step 3: Write minimal implementation**

In `bearmemori/storage/database.py`:

1. Add importance column migration in `_migrate()` (after the image_path migration):
```python
cursor = self._conn.execute(
    "SELECT name FROM pragma_table_info('memories') WHERE name = ?",
    ("importance",),
)
if cursor.fetchone() is None:
    self._conn.execute(
        "ALTER TABLE memories ADD COLUMN importance INTEGER NOT NULL DEFAULT 5"
    )
    self._conn.commit()
```

2. Add index after existing indexes in `initialize()`:
```python
self._conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_memories_importance
    ON memories (importance)
""")
```

3. Update `_row_to_record()` to read importance:
```python
return MemoryRecord(
    id=row["id"],
    category=MemoryCategory(row["category"]),
    title=row["title"],
    content=row["content"],
    raw_input=row["raw_input"],
    created_at=datetime.fromisoformat(row["created_at"]),
    event_fields=event_fields,
    tags=json.loads(row["tags"]),
    importance=row["importance"],
    source=source,
    metadata=json.loads(row["metadata"]),
    needs_review=bool(row["needs_review"]),
    image_path=row["image_path"],
)
```

4. Update `create()` to include importance in INSERT:
```python
self._conn.execute(
    """INSERT INTO memories
       (id, category, title, content, raw_input, created_at, updated_at,
        tags, source, event_datetime, event_status, event_recurrence,
        metadata, needs_review, image_path, importance)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    (
        record.id,
        record.category.value,
        record.title,
        record.content,
        record.raw_input,
        record.created_at.isoformat(),
        now,
        json.dumps(record.tags),
        source_json,
        event_dt,
        event_status,
        event_recurrence,
        json.dumps(record.metadata),
        1 if record.needs_review else 0,
        record.image_path,
        record.importance,
    ),
)
```

5. Update `update()` to include importance in UPDATE:
```python
self._conn.execute(
    """UPDATE memories SET category=?, title=?, content=?, raw_input=?,
       updated_at=?, tags=?, source=?, event_datetime=?, event_status=?,
       event_recurrence=?, metadata=?, needs_review=?, image_path=?, importance=?
       WHERE id=?""",
    (
        record.category.value,
        record.title,
        record.content,
        record.raw_input,
        now,
        json.dumps(record.tags),
        source_json,
        event_dt,
        event_status,
        event_recurrence,
        json.dumps(record.metadata),
        1 if record.needs_review else 0,
        record.image_path,
        record.importance,
        record.id,
    ),
)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_importance_storage.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add bearmemori/storage/database.py tests/test_importance_storage.py
git commit -m "feat: add importance column to SQLite schema with migration"
```

---

### Task 3: Add importance to LLM extraction

**Files:**
- Modify: `bearmemori/llm/client.py:42-48` (ExtractionResult)
- Modify: `bearmemori/llm/client.py:66-85` (_EXTRACT_SYSTEM_TEMPLATE)
- Modify: `bearmemori/llm/client.py:97-107` (DESCRIBE_IMAGE_SYSTEM_PROMPT)
- Modify: `bearmemori/llm/client.py:165-182` (extract_memory parsing)
- Modify: `bearmemori/llm/client.py:197-218` (describe_image parsing)

**Step 1: Write the failing test**

Create `tests/test_importance_extraction.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.llm.client import ExtractionResult, LLMClient


def test_extraction_result_has_importance():
    result = ExtractionResult(
        content="Test",
        category="general",
        title="Test",
        tags=["test"],
        importance=7,
    )
    assert result.importance == 7


def test_extraction_result_default_importance():
    result = ExtractionResult(
        content="Test",
        category="general",
        title="Test",
        tags=["test"],
    )
    assert result.importance == 5


@pytest.mark.asyncio
async def test_extract_memory_parses_importance():
    client = LLMClient(base_url="http://fake", model="test")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"content": "Test memory", "category": "general", '
        '"title": "Test", "tags": ["test"], "importance": 8, '
        '"event_fields": null}'
    )
    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.extract_memory("test input", None)
    assert result.importance == 8


@pytest.mark.asyncio
async def test_extract_memory_defaults_importance_when_missing():
    client = LLMClient(base_url="http://fake", model="test")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"content": "Test memory", "category": "general", '
        '"title": "Test", "tags": ["test"], "event_fields": null}'
    )
    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.extract_memory("test input", None)
    assert result.importance == 5


@pytest.mark.asyncio
async def test_extract_memory_clamps_importance_above_10():
    client = LLMClient(base_url="http://fake", model="test")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"content": "Test memory", "category": "general", '
        '"title": "Test", "tags": ["test"], "importance": 15, '
        '"event_fields": null}'
    )
    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.extract_memory("test input", None)
    assert result.importance == 10


@pytest.mark.asyncio
async def test_extract_memory_clamps_importance_below_1():
    client = LLMClient(base_url="http://fake", model="test")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = (
        '{"content": "Test memory", "category": "general", '
        '"title": "Test", "tags": ["test"], "importance": -2, '
        '"event_fields": null}'
    )
    client._client.chat.completions.create = AsyncMock(return_value=mock_response)

    result = await client.extract_memory("test input", None)
    assert result.importance == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_importance_extraction.py -v`
Expected: FAIL -- importance not in ExtractionResult or not clamped

**Step 3: Write minimal implementation**

In `bearmemori/llm/client.py`:

1. Add `importance` to `ExtractionResult`:
```python
class ExtractionResult(BaseModel):
    content: str
    category: str
    title: str
    tags: list[str]
    event_fields: dict | None = None
    importance: int = 5
```

2. Update `_EXTRACT_SYSTEM_TEMPLATE` to include importance instructions. Add before the `"You MUST respond"` line:
```python
_EXTRACT_SYSTEM_TEMPLATE = (
    "/no_think\n"
    "You are a memory extraction assistant. Extract structured memory data from the user input.\n"
    "If follow-up context is provided, use the full conversation to understand the memory.\n"
    "\n"
    "Current date and time: {current_time}\n"
    'When the user mentions relative times (e.g. "in 10 minutes", "tomorrow", "next week"), '
    "use the current date and time above to compute the absolute "
    "ISO 8601 datetime for event_fields.\n"
    "\n"
    "Assign an importance score from 1-10:\n"
    "  1-3: Trivial/ephemeral (casual observations, low-value notes)\n"
    "  4-6: Useful but not critical (general facts, routine tasks)\n"
    "  7-9: Important (key personal info, significant events, recurring tasks)\n"
    "  10: Critical (health info, credentials, life events)\n"
    "\n"
    "You MUST respond with a single valid JSON object and nothing else.\n"
    '{{"content": "<clear summary of the memory>", "category": "<category>", '
    '"title": "<short descriptive title>", "tags": ["tag1", "tag2"], '
    '"importance": <1-10>, "event_fields": null}}\n'
    "Categories: profile, general, event, location, task, reminder\n"
    "\n"
    "For events, tasks, and reminders, set event_fields to:\n"
    '{{"datetime": "<ISO 8601 datetime>", "status": "pending", "recurrence": null}}\n'
    "For non-event categories, set event_fields to null"
)
```

3. Update `DESCRIBE_IMAGE_SYSTEM_PROMPT` similarly:
```python
DESCRIBE_IMAGE_SYSTEM_PROMPT = (
    "/no_think\n"
    "You are a memory extraction assistant. "
    "Describe the image and extract structured memory data.\n"
    "\n"
    "Assign an importance score from 1-10:\n"
    "  1-3: Trivial/ephemeral\n"
    "  4-6: Useful but not critical\n"
    "  7-9: Important\n"
    "  10: Critical\n"
    "\n"
    "You MUST respond with a single valid JSON object and nothing else.\n"
    '{"content": "<description of what the image shows>", "category": "<category>", '
    '"title": "<short descriptive title>", "tags": ["tag1", "tag2"], '
    '"importance": <1-10>, "event_fields": null}\n'
    "Categories: profile, general, event, location, task, reminder"
)
```

4. Add clamping helper and update `extract_memory()` and `describe_image()` to clamp:
```python
def _clamp_importance(data: dict) -> dict:
    """Clamp importance to 1-10, defaulting to 5 if missing."""
    raw = data.get("importance", 5)
    try:
        val = int(raw)
    except (TypeError, ValueError):
        val = 5
    data["importance"] = max(1, min(10, val))
    return data
```

In `extract_memory()`, after `data = extract_json(raw)`:
```python
data = _clamp_importance(data)
```

In `describe_image()`, after `data = extract_json(raw)`:
```python
data = _clamp_importance(data)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_importance_extraction.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add bearmemori/llm/client.py tests/test_importance_extraction.py
git commit -m "feat: add importance scoring to LLM extraction prompts"
```

---

### Task 4: Pass importance through processor and confirmation flow

**Files:**
- Modify: `bearmemori/core/processor.py:110-158` (_create_pending)
- Modify: `bearmemori/core/confirm.py:30-67` (handle_confirmed)

**Step 1: Write the failing test**

Create `tests/test_importance_flow.py`:

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.core.processor import Processor
from bearmemori.events.bus import EventBus
from bearmemori.events.domain import MemoryPending
from bearmemori.llm.client import ExtractionResult
from bearmemori.storage.pending_store import PendingStore


@pytest.mark.asyncio
async def test_create_pending_includes_importance_in_draft():
    bus = EventBus()
    pending_store = PendingStore()
    llm = MagicMock()
    processor = Processor(bus=bus, llm=llm, pending_store=pending_store)

    pending_events = []
    bus.on(MemoryPending, lambda e: pending_events.append(e))

    extraction = ExtractionResult(
        content="Important meeting",
        category="event",
        title="Team standup",
        tags=["work"],
        importance=8,
    )

    await processor._create_pending(extraction, "meeting tomorrow", "42")

    assert len(pending_events) == 1
    assert pending_events[0].preview_data["importance"] == 8

    # Check the draft stored in pending store has correct importance
    pending = pending_store.get(pending_events[0].pending_id)
    assert pending.draft.importance == 8
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_importance_flow.py -v`
Expected: FAIL -- importance not in preview_data or not passed to draft

**Step 3: Write minimal implementation**

In `bearmemori/core/processor.py`, update `_create_pending()`:

1. Pass importance to `MemoryDraft`:
```python
draft = MemoryDraft(
    category=MemoryCategory(extraction.category),
    title=extraction.title,
    content=extraction.content,
    event_fields=event_fields,
    tags=extraction.tags,
    importance=extraction.importance,
    source=MemorySource(platform="telegram", chat_id=chat_id),
)
```

2. Add importance to preview_data:
```python
preview_data = {
    "title": extraction.title,
    "category": extraction.category,
    "content": extraction.content,
    "tags": extraction.tags,
    "importance": extraction.importance,
    "event_fields": extraction.event_fields,
}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_importance_flow.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add bearmemori/core/processor.py tests/test_importance_flow.py
git commit -m "feat: pass importance through processor to pending store and preview"
```

---

### Task 5: Add importance to vector store metadata and context retrieval

**Files:**
- Modify: `bearmemori/storage/vector_store.py:26-38` (add method metadata)
- Modify: `bearmemori/api/routes.py:130-158` (retrieve_context endpoint)
- Modify: `bearmemori/config.py` (add threshold settings)

**Step 1: Write the failing test**

Create `tests/test_importance_context.py`:

```python
from datetime import UTC, datetime

from bearmemori.storage.models import MemoryCategory, MemoryRecord
from bearmemori.storage.vector_store import VectorStore


def test_vector_store_includes_importance_in_metadata():
    vs = VectorStore()
    vs.init()

    record = MemoryRecord(
        id="mem_vs_test",
        category=MemoryCategory.GENERAL,
        title="Important fact",
        content="The sky is blue",
        created_at=datetime.now(UTC),
        importance=9,
    )
    vs.add(record)

    results = vs.search("sky", top_k=1)
    assert len(results) == 1
    assert results[0]["metadata"]["importance"] == 9
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_importance_context.py -v`
Expected: FAIL -- importance not in metadata

**Step 3: Write minimal implementation**

1. In `bearmemori/storage/vector_store.py`, update `add()` method:
```python
def add(self, record: MemoryRecord) -> None:
    text = f"{record.title}: {record.content}"
    metadata = {
        "category": record.category.value,
        "created_at": record.created_at.isoformat(),
        "importance": record.importance,
    }
    if record.event_fields:
        metadata["event_datetime"] = record.event_fields.datetime
    self._collection.upsert(
        ids=[record.id],
        documents=[text],
        metadatas=[metadata],
    )
```

2. In `bearmemori/config.py`, add threshold settings:
```python
importance_high_threshold: int = 8
importance_low_threshold: int = 2
importance_relevance_weight: float = 0.5
importance_weight: float = 0.5
```

3. In `bearmemori/api/routes.py`, update `retrieve_context()` to sort by combined score. Replace the current implementation:
```python
@app.get("/memory/retrieve")
def retrieve_context(query_context: str, top_k: int = 5, event_days: int = 7):
    semantic_results = vector_store.search(query=query_context, top_k=top_k * 2)
    upcoming_events = db.get_upcoming_events(days=event_days)

    # Score and rank by combined relevance + importance
    scored = []
    for r in semantic_results:
        distance = r.get("distance", 1.0)
        similarity = max(0.0, 1.0 - distance)
        importance = r.get("metadata", {}).get("importance", 5) / 10.0
        combined = 0.5 * similarity + 0.5 * importance
        scored.append((combined, r))

    # Sort by combined score descending
    scored.sort(key=lambda x: x[0], reverse=True)

    # Apply importance thresholds
    filtered = []
    for score, r in scored:
        imp = r.get("metadata", {}).get("importance", 5)
        distance = r.get("distance", 1.0)
        similarity = max(0.0, 1.0 - distance)
        # Skip low importance unless highly relevant
        if imp <= 2 and similarity < 0.7:
            continue
        filtered.append(r)
        if len(filtered) >= top_k:
            break

    # Always include high-importance memories with any relevance
    high_imp = [
        r for _, r in scored
        if r.get("metadata", {}).get("importance", 5) >= 8
        and r not in filtered
    ]
    filtered.extend(high_imp[:top_k - len(filtered)] if len(filtered) < top_k else [])

    lines = []
    if filtered:
        lines.append("## Relevant Memories")
        for r in filtered:
            lines.append(f"- {r['document']}")

    if upcoming_events:
        lines.append("\n## Upcoming Events")
        for e in upcoming_events:
            dt = e.event_fields.datetime if e.event_fields else "unknown"
            lines.append(f"- [{dt}] {e.title}: {e.content}")

    context_block = "\n".join(lines) if lines else ""

    items = filtered + [
        {
            "id": e.id,
            "document": f"{e.title}: {e.content}",
            "metadata": {"category": e.category.value},
        }
        for e in upcoming_events
    ]

    return {"context_block": context_block, "items": items}
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_importance_context.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add bearmemori/storage/vector_store.py bearmemori/api/routes.py bearmemori/config.py tests/test_importance_context.py
git commit -m "feat: add importance to vector store metadata and context retrieval scoring"
```

---

### Task 6: Add importance to API schemas and Telegram preview

**Files:**
- Modify: `bearmemori/api/schemas.py:21-27` (UpdateMemoryRequest)
- Modify: `bearmemori/api/schemas.py:29-33` (CreateMemoryRequest)
- Modify: `bearmemori/api/routes.py:265-267` (bulk update allowed_fields)
- Modify: `bearmemori/interfaces/telegram.py:218-257` (handle_memory_pending)

**Step 1: Write the failing test**

Add to `tests/test_importance_flow.py`:

```python
@pytest.mark.asyncio
async def test_telegram_preview_shows_importance():
    from bearmemori.events.domain import MemoryPending
    from bearmemori.interfaces.telegram import TelegramInterface

    bus = EventBus()
    interface = TelegramInterface(bus=bus, token="fake", allowed_user_id=12345)

    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    event = MemoryPending(
        pending_id="pend_imp_test",
        preview_data={
            "title": "Test memory",
            "category": "general",
            "content": "Some content",
            "tags": [],
            "importance": 8,
        },
        source_chat_id="42",
    )

    await interface.handle_memory_pending(event)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "Importance: 8" in call_kwargs["text"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_importance_flow.py::test_telegram_preview_shows_importance -v`
Expected: FAIL -- "Importance: 8" not in preview text

**Step 3: Write minimal implementation**

1. In `bearmemori/api/schemas.py`, add importance to update/create schemas:

```python
class UpdateMemoryRequest(BaseModel):
    title: str | None = None
    content: str | None = None
    category: str | None = None
    tags: list[str] | None = None
    needs_review: bool | None = None
    importance: int | None = None


class CreateMemoryRequest(BaseModel):
    category: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    importance: int = 5
```

2. In `bearmemori/api/routes.py`, update `bulk_update` allowed_fields:
```python
allowed_fields = {"title", "content", "category", "tags", "needs_review", "importance"}
```

3. In `bearmemori/api/routes.py`, update `create_memory_direct` to pass importance:
```python
record = MemoryRecord(
    id=record_id,
    category=category,
    title=request.title,
    content=request.content,
    created_at=datetime.now(UTC),
    tags=request.tags or [],
    importance=request.importance,
    needs_review=False,
)
```

4. In `bearmemori/interfaces/telegram.py`, update `handle_memory_pending()` to show importance:
```python
async def handle_memory_pending(self, event: MemoryPending) -> None:
    if not self._app:
        return

    preview = event.preview_data
    tags_str = ", ".join(preview.get("tags", []))
    importance = preview.get("importance", 5)
    text = f"Memory Preview\n\nTitle: {preview['title']}\nCategory: {preview['category']}\n"
    text += f"Importance: {importance}/10\n"
    if tags_str:
        text += f"Tags: {tags_str}\n"
    text += f"Content: {preview['content']}"

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Save", callback_data=f"save:{event.pending_id}"),
                InlineKeyboardButton(
                    "Review Later", callback_data=f"review:{event.pending_id}"
                ),
            ],
            [
                InlineKeyboardButton("Edit", callback_data=f"edit:{event.pending_id}"),
                InlineKeyboardButton("Discard", callback_data=f"discard:{event.pending_id}"),
            ],
        ]
    )

    if event.image_bytes:
        await self._app.bot.send_photo(
            chat_id=int(event.source_chat_id),
            photo=event.image_bytes,
            caption=text,
            reply_markup=keyboard,
        )
    else:
        await self._app.bot.send_message(
            chat_id=int(event.source_chat_id),
            text=text,
            reply_markup=keyboard,
        )
    self._pending_chat_ids[event.pending_id] = event.source_chat_id
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_importance_flow.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add bearmemori/api/schemas.py bearmemori/api/routes.py bearmemori/interfaces/telegram.py tests/test_importance_flow.py
git commit -m "feat: add importance to API schemas and Telegram preview"
```

---

### Task 7: Add /help command to Telegram

**Files:**
- Modify: `bearmemori/interfaces/telegram.py:49-64` (build method, set_bot_commands)

**Step 1: Write the failing test**

Add to `tests/test_telegram.py`:

```python
@pytest.mark.asyncio
async def test_handle_help_returns_command_list(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    update = _make_update()
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    await interface._handle_help(update, context)

    update.message.reply_text.assert_called_once()
    text = update.message.reply_text.call_args[0][0]
    assert "/start" in text
    assert "/recall" in text
    assert "/search" in text
    assert "/list" in text
    assert "/help" in text
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram.py::test_handle_help_returns_command_list -v`
Expected: FAIL -- _handle_help doesn't exist

**Step 3: Write minimal implementation**

In `bearmemori/interfaces/telegram.py`:

1. Add `_handle_help` method:
```python
async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not self._is_authorized(update):
        return

    text = (
        "Available commands:\n\n"
        "/start - Welcome message\n"
        "/recall <memory_id> - Retrieve a memory by ID\n"
        "/search <query> - Search your memories\n"
        "/list [category] - List memories (categories: profile, general, event, location, task, reminder)\n"
        "/help - Show this help message"
    )
    await update.message.reply_text(text)
```

2. Register handler in `build()`:
```python
self._app.add_handler(CommandHandler("help", self._handle_help))
```

3. Update `set_bot_commands` in `post_init`:
```python
await application.bot.set_my_commands(
    [
        BotCommand("start", "Welcome message"),
        BotCommand("recall", "Retrieve a memory by ID"),
        BotCommand("search", "Search your memories"),
        BotCommand("list", "List memories"),
        BotCommand("help", "Show available commands"),
    ]
)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_telegram.py::test_handle_help_returns_command_list -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add bearmemori/interfaces/telegram.py tests/test_telegram.py
git commit -m "feat: add /help command to Telegram bot"
```

---

### Task 8: Add /search command to Telegram

**Files:**
- Modify: `bearmemori/interfaces/telegram.py` (add _handle_search, register handler)

**Step 1: Write the failing test**

Add to `tests/test_telegram.py`:

```python
@pytest.mark.asyncio
async def test_search_returns_results(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from unittest.mock import MagicMock as SyncMock

    mock_vs = SyncMock()
    interface._vector_store = mock_vs
    mock_vs.search.return_value = [
        {
            "id": "mem_abc123",
            "document": "Pizza preference: I like pepperoni pizza",
            "metadata": {"category": "general", "importance": 7},
            "distance": 0.3,
        },
    ]

    update = _make_update()
    context = MagicMock()
    context.args = ["pizza"]

    await interface._handle_search(update, context)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "Pizza preference" in call_kwargs["text"]
    assert "7/10" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_search_no_query_shows_usage(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    update = _make_update()
    context = MagicMock()
    context.args = []

    await interface._handle_search(update, context)

    mock_bot.send_message.assert_called_once()
    assert "usage" in mock_bot.send_message.call_args.kwargs["text"].lower()


@pytest.mark.asyncio
async def test_search_no_results(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from unittest.mock import MagicMock as SyncMock

    mock_vs = SyncMock()
    interface._vector_store = mock_vs
    mock_vs.search.return_value = []

    update = _make_update()
    context = MagicMock()
    context.args = ["nonexistent"]

    await interface._handle_search(update, context)

    mock_bot.send_message.assert_called_once()
    assert "no memories found" in mock_bot.send_message.call_args.kwargs["text"].lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram.py::test_search_returns_results -v`
Expected: FAIL -- _handle_search doesn't exist

**Step 3: Write minimal implementation**

In `bearmemori/interfaces/telegram.py`:

1. Add `vector_store` parameter to `__init__`:
```python
def __init__(
    self,
    bus: EventBus,
    token: str,
    allowed_user_id: int,
    db: MemoryDatabase | None = None,
    image_storage_dir: str = "",
    vector_store=None,
) -> None:
    self._bus = bus
    self._token = token
    self._allowed_user_id = allowed_user_id
    self._app: Application | None = None
    self._pending_chat_ids: dict[str, str] = {}
    self._edit_pending: dict[str, str] = {}
    self._db = db
    self._image_storage_dir = image_storage_dir
    self._vector_store = vector_store
```

2. Add import at the top of file:
```python
from bearmemori.storage.vector_store import VectorStore
```

3. Add `_handle_search` method:
```python
async def _handle_search(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not self._is_authorized(update):
        return

    chat_id = str(update.effective_chat.id)

    if not context.args:
        await self._app.bot.send_message(
            chat_id=int(chat_id),
            text="Usage: /search <query>",
        )
        return

    if not self._vector_store:
        await self._app.bot.send_message(
            chat_id=int(chat_id),
            text="Search not available.",
        )
        return

    query = " ".join(context.args)
    results = self._vector_store.search(query=query, top_k=5)

    if not results:
        await self._app.bot.send_message(
            chat_id=int(chat_id),
            text="No memories found.",
        )
        return

    lines = ["Search results:\n"]
    for r in results:
        doc = r["document"]
        title = doc.split(":")[0] if ":" in doc else doc[:50]
        category = r.get("metadata", {}).get("category", "unknown")
        importance = r.get("metadata", {}).get("importance", 5)
        content_preview = doc[:100] + "..." if len(doc) > 100 else doc
        lines.append(f"[{category}] {title} ({importance}/10)")
        lines.append(f"  {content_preview}\n")

    await self._app.bot.send_message(
        chat_id=int(chat_id),
        text="\n".join(lines),
    )
```

4. Register handler in `build()`:
```python
self._app.add_handler(CommandHandler("search", self._handle_search))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_telegram.py::test_search_returns_results tests/test_telegram.py::test_search_no_query_shows_usage tests/test_telegram.py::test_search_no_results -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass (note: existing `interface` fixture will need updating -- see step below)

**Important:** Update the `interface` fixture in `tests/test_telegram.py` if the new `vector_store` param causes issues. It has a default of `None` so existing tests should still pass.

**Step 6: Commit**

```bash
git add bearmemori/interfaces/telegram.py tests/test_telegram.py
git commit -m "feat: add /search command to Telegram bot"
```

---

### Task 9: Add /list command to Telegram

**Files:**
- Modify: `bearmemori/interfaces/telegram.py` (add _handle_list, register handler)

**Step 1: Write the failing test**

Add to `tests/test_telegram.py`:

```python
@pytest.mark.asyncio
async def test_list_all_memories(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from datetime import UTC, datetime
    from unittest.mock import MagicMock as SyncMock

    from bearmemori.storage.models import MemoryCategory, MemoryRecord

    mock_db = SyncMock()
    interface._db = mock_db
    mock_db.list_all.return_value = [
        MemoryRecord(
            id="mem_list1",
            category=MemoryCategory.GENERAL,
            title="First memory",
            content="Content one",
            created_at=datetime.now(UTC),
            importance=7,
        ),
        MemoryRecord(
            id="mem_list2",
            category=MemoryCategory.EVENT,
            title="Second memory",
            content="Content two",
            created_at=datetime.now(UTC),
            importance=3,
        ),
    ]

    update = _make_update()
    context = MagicMock()
    context.args = []

    await interface._handle_list(update, context)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "First memory" in call_kwargs["text"]
    assert "Second memory" in call_kwargs["text"]


@pytest.mark.asyncio
async def test_list_by_category(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from datetime import UTC, datetime
    from unittest.mock import MagicMock as SyncMock

    from bearmemori.storage.models import MemoryCategory, MemoryRecord

    mock_db = SyncMock()
    interface._db = mock_db
    mock_db.list_by_category.return_value = [
        MemoryRecord(
            id="mem_cat1",
            category=MemoryCategory.EVENT,
            title="Event memory",
            content="An event",
            created_at=datetime.now(UTC),
            importance=6,
        ),
    ]

    update = _make_update()
    context = MagicMock()
    context.args = ["event"]

    await interface._handle_list(update, context)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "Event memory" in call_kwargs["text"]
    mock_db.list_by_category.assert_called_once()


@pytest.mark.asyncio
async def test_list_invalid_category(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from unittest.mock import MagicMock as SyncMock

    mock_db = SyncMock()
    interface._db = mock_db

    update = _make_update()
    context = MagicMock()
    context.args = ["invalid_cat"]

    await interface._handle_list(update, context)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "valid categories" in call_kwargs["text"].lower() or "profile" in call_kwargs["text"].lower()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram.py::test_list_all_memories -v`
Expected: FAIL -- _handle_list doesn't exist

**Step 3: Write minimal implementation**

In `bearmemori/interfaces/telegram.py`, add `_handle_list` method and import `MemoryCategory`:

1. Add import:
```python
from bearmemori.storage.models import MemoryCategory
```

2. Add method:
```python
async def _handle_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not self._is_authorized(update):
        return

    chat_id = str(update.effective_chat.id)

    if not self._db:
        await self._app.bot.send_message(
            chat_id=int(chat_id),
            text="Database not available.",
        )
        return

    if context.args:
        category_str = context.args[0].lower()
        try:
            category = MemoryCategory(category_str)
        except ValueError:
            valid = ", ".join(c.value for c in MemoryCategory)
            await self._app.bot.send_message(
                chat_id=int(chat_id),
                text=f"Invalid category. Valid categories: {valid}",
            )
            return
        records = self._db.list_by_category(category)
    else:
        records = self._db.list_all()

    if not records:
        await self._app.bot.send_message(
            chat_id=int(chat_id),
            text="No memories found.",
        )
        return

    lines = ["Memories:\n"]
    for r in records[:10]:
        lines.append(f"[{r.category.value}] {r.title} ({r.importance}/10)")
        lines.append(f"  ID: {r.id}\n")

    if len(records) > 10:
        lines.append(f"... and {len(records) - 10} more")

    await self._app.bot.send_message(
        chat_id=int(chat_id),
        text="\n".join(lines),
    )
```

3. Register handler in `build()`:
```python
self._app.add_handler(CommandHandler("list", self._handle_list))
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_telegram.py::test_list_all_memories tests/test_telegram.py::test_list_by_category tests/test_telegram.py::test_list_invalid_category -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 6: Commit**

```bash
git add bearmemori/interfaces/telegram.py tests/test_telegram.py
git commit -m "feat: add /list command to Telegram bot"
```

---

### Task 10: Wire vector_store into TelegramInterface in app.py and update recall to show importance

**Files:**
- Modify: `bearmemori/app.py` (pass vector_store to TelegramInterface)
- Modify: `bearmemori/interfaces/telegram.py:166-216` (_handle_recall to show importance)

**Step 1: Read app.py to find the wiring**

Run: `cat bearmemori/app.py` to find where TelegramInterface is instantiated.

**Step 2: Write the failing test**

Add to `tests/test_telegram.py`:

```python
@pytest.mark.asyncio
async def test_recall_shows_importance(interface):
    mock_bot = AsyncMock()
    interface._app = MagicMock()
    interface._app.bot = mock_bot

    from datetime import UTC, datetime
    from unittest.mock import MagicMock as SyncMock

    from bearmemori.storage.models import MemoryCategory, MemoryRecord

    mock_db = SyncMock()
    interface._db = mock_db

    record = MemoryRecord(
        id="mem_imp_recall",
        category=MemoryCategory.GENERAL,
        title="Important memory",
        content="Very important content",
        created_at=datetime.now(UTC),
        importance=9,
        tags=["critical"],
    )
    mock_db.get.return_value = record

    update = _make_update()
    context = MagicMock()
    context.args = ["mem_imp_recall"]

    await interface._handle_recall(update, context)

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "9/10" in call_kwargs["text"] or "Importance: 9" in call_kwargs["text"]
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_telegram.py::test_recall_shows_importance -v`
Expected: FAIL -- importance not in recall output

**Step 4: Write minimal implementation**

1. In `bearmemori/interfaces/telegram.py`, update `_handle_recall` to include importance:
```python
tags_str = ", ".join(record.tags) if record.tags else ""
text = f"Title: {record.title}\nCategory: {record.category.value}\n"
text += f"Importance: {record.importance}/10\n"
if tags_str:
    text += f"Tags: {tags_str}\n"
text += f"Content: {record.content}"
```

2. In `bearmemori/app.py`, pass `vector_store` to `TelegramInterface` constructor. Find the line that creates `TelegramInterface` and add `vector_store=vector_store`.

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_telegram.py::test_recall_shows_importance -v`
Expected: PASS

**Step 6: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 7: Commit**

```bash
git add bearmemori/interfaces/telegram.py bearmemori/app.py tests/test_telegram.py
git commit -m "feat: wire vector_store into Telegram, show importance in /recall"
```

---

### Task 11: Lint, format, and final verification

**Step 1: Run linter**

Run: `uv run ruff check .`
Fix any issues.

**Step 2: Run formatter**

Run: `uv run ruff format .`

**Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

**Step 4: Commit any formatting fixes**

```bash
git add -A
git commit -m "chore: lint and format"
```
