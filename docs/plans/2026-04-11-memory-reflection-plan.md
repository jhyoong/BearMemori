# Memory Reflection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a memory reflection system that periodically reviews stored memories, reranks importance, and archives low-value entries via per-memory LLM calls — surfacing changes to the user via Telegram and a REST/MCP API.

**Architecture:** A new `ReflectionTask` in `bearmemori/core/reflection.py` runs on a configurable schedule (gated to an off-hours time window) and on-demand via REST/MCP. Pre-filter rules select candidate memories; each candidate gets one LLM call returning an archive/keep decision plus optional new importance. Results are logged to a JSONL file and summarised via Telegram. The database gains an `archived` boolean column; all existing read queries are updated to exclude archived records.

**Tech Stack:** Python 3.12, FastAPI, openai SDK, pytest + pytest-asyncio, SQLite, pydantic-settings

---

### Task 1: Add `archived` column to database

**Files:**
- Modify: `bearmemori/storage/models.py`
- Modify: `bearmemori/storage/database.py`
- Modify: `tests/test_triage.py` (if snapshots break — check after)

**Step 1: Write the failing tests**

Add to `tests/test_triage.py` (or create `tests/test_database_archived.py`):

```python
import pytest
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryRecord
from datetime import UTC, datetime


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _make_record(record_id: str, importance: int = 5) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title="Test",
        content="Test content",
        created_at=datetime.now(UTC),
        importance=importance,
    )


def test_record_archived_defaults_false(db):
    r = _make_record("mem_001")
    db.create(r)
    fetched = db.get("mem_001")
    assert fetched.archived is False


def test_archive_record_hides_from_list_all(db):
    r = _make_record("mem_002")
    db.create(r)
    r.archived = True
    db.update(r)
    records = db.list_all()
    assert not any(rec.id == "mem_002" for rec in records)


def test_list_archived_returns_archived(db):
    r = _make_record("mem_003")
    db.create(r)
    r.archived = True
    db.update(r)
    archived = db.list_archived()
    assert any(rec.id == "mem_003" for rec in archived)


def test_archived_record_hidden_from_list_by_category(db):
    r = _make_record("mem_004")
    db.create(r)
    r.archived = True
    db.update(r)
    records = db.list_by_category(MemoryCategory.GENERAL)
    assert not any(rec.id == "mem_004" for rec in records)


def test_count_all_excludes_archived(db):
    r1 = _make_record("mem_005")
    r2 = _make_record("mem_006")
    db.create(r1)
    db.create(r2)
    r2.archived = True
    db.update(r2)
    assert db.count_all() == 1
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_database_archived.py -v
```

Expected: FAIL — `MemoryRecord` has no `archived` field, `list_archived` does not exist.

**Step 3: Add `archived` to `MemoryRecord`**

In `bearmemori/storage/models.py`, add `archived: bool = False` to `MemoryRecord` (after `needs_review`):

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
    archived: bool = False
```

**Step 4: Update `MemoryDatabase` in `bearmemori/storage/database.py`**

4a. Add migration for `archived` column at the end of `_migrate()`:

```python
cursor = self._conn.execute(
    "SELECT name FROM pragma_table_info('memories') WHERE name = ?",
    ("archived",),
)
if cursor.fetchone() is None:
    self._conn.execute(
        "ALTER TABLE memories ADD COLUMN archived INTEGER NOT NULL DEFAULT 0"
    )
    self._conn.commit()
```

4b. Add `archived` to the `CREATE TABLE` statement (after `needs_review`):

```sql
archived INTEGER NOT NULL DEFAULT 0
```

4c. Add index after the existing `idx_memories_importance` index:

```python
self._conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_memories_archived
    ON memories (archived)
""")
```

4d. Update `_row_to_record()` — add `archived=bool(row["archived"])` to the `MemoryRecord(...)` call.

4e. Update `create()` — add `archived` to the `INSERT` statement:

In the column list: `..., needs_review, image_path, importance, archived`
In the values tuple: `..., 1 if record.needs_review else 0, record.image_path, record.importance, 1 if record.archived else 0`

4f. Update `update()` — add `archived=?` to the `UPDATE SET` clause and add `1 if record.archived else 0` before `record.id` in the values tuple.

4g. Add `WHERE archived = 0` to these methods:
- `list_all()`: both the `needs_review` and non-`needs_review` queries
- `list_by_category()`: the main query
- `search_keyword()`: the JOIN query
- `count_all()`: `SELECT COUNT(*) FROM memories WHERE archived = 0`
- `count_by_category()`: add `AND archived = 0`
- `list_recently_updated()`: add `AND archived = 0`
- `get_upcoming_events()`: add `AND archived = 0`
- `get_due_events()`: add `AND archived = 0`
- `get_events_in_range()`: add `AND archived = 0` to the outer WHERE

4h. Add `list_archived()` method:

```python
def list_archived(self, offset: int = 0, limit: int = 50) -> list[MemoryRecord]:
    rows = self._conn.execute(
        "SELECT * FROM memories WHERE archived = 1 ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [self._row_to_record(r) for r in rows]
```

**Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/test_database_archived.py -v
```

Expected: all PASS

**Step 6: Run full test suite to check for regressions**

```bash
uv run pytest -v
```

Expected: all PASS

**Step 7: Commit**

```bash
git add bearmemori/storage/models.py bearmemori/storage/database.py tests/test_database_archived.py
git commit -m "feat: add archived column to memories table with migration and list_archived()"
```

---

### Task 2: Add `reflect_memory()` to `LLMClient`

**Files:**
- Modify: `bearmemori/llm/client.py`
- Modify: `tests/test_llm_client.py`

**Step 1: Write the failing test**

Add to `tests/test_llm_client.py`:

```python
@pytest.mark.asyncio
async def test_reflect_memory_returns_archive_decision(client):
    from bearmemori.storage.models import MemoryCategory, MemoryRecord
    from datetime import UTC, datetime

    record = MemoryRecord(
        id="mem_test",
        category=MemoryCategory.GENERAL,
        title="Old note",
        content="Some old content",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
        importance=2,
    )
    response_data = {
        "action": "archive",
        "new_importance": None,
        "reason": "Outdated and low value",
    }
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps(response_data), reasoning_content=None))
    ]
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.reflect_memory(record)
    assert result["action"] == "archive"
    assert result["reason"] == "Outdated and low value"


@pytest.mark.asyncio
async def test_reflect_memory_returns_keep_with_new_importance(client):
    from bearmemori.storage.models import MemoryCategory, MemoryRecord
    from datetime import UTC, datetime

    record = MemoryRecord(
        id="mem_test2",
        category=MemoryCategory.PROFILE,
        title="Preference",
        content="Likes hiking",
        created_at=datetime(2025, 6, 1, tzinfo=UTC),
        importance=4,
    )
    response_data = {
        "action": "keep",
        "new_importance": 7,
        "reason": "Still relevant personal preference",
    }
    mock_response = AsyncMock()
    mock_response.choices = [
        AsyncMock(message=AsyncMock(content=json.dumps(response_data), reasoning_content=None))
    ]
    with patch.object(client._client.chat.completions, "create", return_value=mock_response):
        result = await client.reflect_memory(record)
    assert result["action"] == "keep"
    assert result["new_importance"] == 7


def test_reflect_memory_prompt_template_exists():
    from bearmemori.llm.client import _REFLECT_SYSTEM_PROMPT
    assert "archive" in _REFLECT_SYSTEM_PROMPT
    assert "new_importance" in _REFLECT_SYSTEM_PROMPT
    assert "reason" in _REFLECT_SYSTEM_PROMPT
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_llm_client.py::test_reflect_memory_returns_archive_decision tests/test_llm_client.py::test_reflect_memory_returns_keep_with_new_importance tests/test_llm_client.py::test_reflect_memory_prompt_template_exists -v
```

Expected: FAIL — `reflect_memory` not defined, `_REFLECT_SYSTEM_PROMPT` not defined.

**Step 3: Add prompt template and method to `bearmemori/llm/client.py`**

Add the prompt constant (after `_EXTRACTION_SYSTEM_TEMPLATE`):

```python
_REFLECT_SYSTEM_PROMPT = """\
You are a memory reflection agent. Review the following memory and decide whether \
to archive it or keep it. You may also update its importance score.

Respond with a single valid JSON object and nothing else. No explanation, no commentary, \
no markdown formatting.

{{"action": "archive" | "keep", "new_importance": <1-10 or null>, "reason": "<brief reason>"}}

Guidelines:
- "action": "archive" if the memory is outdated, superseded, trivial, or no longer useful.
- "action": "keep" if the memory is still relevant or valuable.
- "new_importance": provide an updated 1-10 score if the current score seems wrong; \
null to leave unchanged.
- "reason": always required. One sentence explaining the decision.

Importance scale:
- 1-3: Low (trivial facts, casual mentions, no longer relevant)
- 4-6: Medium (useful but not critical)
- 7-8: High (key personal facts, significant events)
- 9-10: Critical (health/safety, core identity, major life events)
"""
```

Add the method to `LLMClient` (after `extract_triage`):

```python
async def reflect_memory(self, record) -> dict:
    from datetime import UTC, datetime

    age_days = (datetime.now(UTC) - record.created_at).days
    memory_text = (
        f"Title: {record.title}\n"
        f"Category: {record.category.value}\n"
        f"Content: {record.content}\n"
        f"Tags: {', '.join(record.tags) if record.tags else 'none'}\n"
        f"Importance: {record.importance}/10\n"
        f"Age: {age_days} days\n"
        f"Needs review: {record.needs_review}"
    )
    response = await self._client.chat.completions.create(
        model=self._model,
        messages=[
            {"role": "system", "content": _REFLECT_SYSTEM_PROMPT},
            {"role": "user", "content": memory_text},
        ],
        temperature=0.1,
    )
    raw = _get_content(response.choices[0].message)
    logger.debug("Reflect memory raw output: %s", raw)
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
git commit -m "feat: add reflect_memory() method to LLMClient"
```

---

### Task 3: Add reflection settings to config

**Files:**
- Modify: `bearmemori/config.py`

**Step 1: Write the failing test**

Create `tests/test_reflection_config.py`:

```python
from bearmemori.config import Settings


def test_reflection_defaults():
    s = Settings(
        telegram_bot_token="x",
        telegram_allowed_user_id=1,
    )
    assert s.reflection_start_hour == 2
    assert s.reflection_end_hour == 6
    assert s.reflection_poll_interval_seconds == 3600
    assert s.reflection_low_importance_age_days == 30
    assert s.reflection_needs_review_age_days == 21
    assert s.reflection_mid_importance_age_days == 90
    assert s.reflection_log_path == "data/reflection.log"
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_reflection_config.py -v
```

Expected: FAIL — attributes not found.

**Step 3: Add settings to `bearmemori/config.py`**

Add after `importance_weight`:

```python
reflection_start_hour: int = 2
reflection_end_hour: int = 6
reflection_poll_interval_seconds: int = 3600
reflection_low_importance_age_days: int = 30
reflection_needs_review_age_days: int = 21
reflection_mid_importance_age_days: int = 90
reflection_log_path: str = "data/reflection.log"
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_reflection_config.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/config.py tests/test_reflection_config.py
git commit -m "feat: add reflection settings to config"
```

---

### Task 4: Implement `ReflectionTask`

**Files:**
- Create: `bearmemori/core/reflection.py`
- Create: `tests/test_reflection.py`

**Step 1: Write the failing tests**

Create `tests/test_reflection.py`:

```python
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bearmemori.core.reflection import ReflectionTask
from bearmemori.llm.client import LLMClient
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryRecord
from bearmemori.storage.vector_store import VectorStore


def _make_record(record_id: str, importance: int, age_days: int, needs_review: bool = False) -> MemoryRecord:
    return MemoryRecord(
        id=record_id,
        category=MemoryCategory.GENERAL,
        title=f"Memory {record_id}",
        content="Some content",
        created_at=datetime.now(UTC) - timedelta(days=age_days),
        importance=importance,
        needs_review=needs_review,
    )


@pytest.fixture
def db():
    return MagicMock(spec=MemoryDatabase)


@pytest.fixture
def vector_store():
    return MagicMock(spec=VectorStore)


@pytest.fixture
def llm():
    return MagicMock(spec=LLMClient)


@pytest.fixture
def bus():
    m = MagicMock()
    m.emit = AsyncMock()
    return m


@pytest.fixture
def settings():
    s = MagicMock()
    s.reflection_low_importance_age_days = 30
    s.reflection_needs_review_age_days = 21
    s.reflection_mid_importance_age_days = 90
    s.reflection_log_path = ""  # empty = no file write in tests
    s.reflection_start_hour = 2
    s.reflection_end_hour = 6
    s.reflection_poll_interval_seconds = 3600
    s.user_timezone = "UTC"
    return s


@pytest.mark.asyncio
async def test_run_once_archives_low_importance_old_memory(db, vector_store, llm, bus, settings, tmp_path):
    settings.reflection_log_path = str(tmp_path / "reflection.log")
    candidate = _make_record("mem_001", importance=2, age_days=40)
    db.list_all.return_value = [candidate]

    llm.reflect_memory = AsyncMock(return_value={
        "action": "archive",
        "new_importance": None,
        "reason": "Old and trivial",
    })

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["archived"] == 1
    assert summary["kept_unchanged"] == 0
    db.update.assert_called_once()
    updated_record = db.update.call_args[0][0]
    assert updated_record.archived is True


@pytest.mark.asyncio
async def test_run_once_reranks_mid_importance_old_memory(db, vector_store, llm, bus, settings, tmp_path):
    settings.reflection_log_path = str(tmp_path / "reflection.log")
    candidate = _make_record("mem_002", importance=5, age_days=100)
    db.list_all.return_value = [candidate]

    llm.reflect_memory = AsyncMock(return_value={
        "action": "keep",
        "new_importance": 7,
        "reason": "Still relevant",
    })

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["reranked"] == 1
    db.update.assert_called_once()
    updated_record = db.update.call_args[0][0]
    assert updated_record.importance == 7
    assert updated_record.archived is False


@pytest.mark.asyncio
async def test_run_once_skips_high_importance_recent_memory(db, vector_store, llm, bus, settings, tmp_path):
    settings.reflection_log_path = str(tmp_path / "reflection.log")
    # importance=8, only 10 days old — should not be a candidate
    non_candidate = _make_record("mem_003", importance=8, age_days=10)
    db.list_all.return_value = [non_candidate]

    llm.reflect_memory = AsyncMock()

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["candidates_evaluated"] == 0
    llm.reflect_memory.assert_not_called()


@pytest.mark.asyncio
async def test_run_once_writes_log_entry(db, vector_store, llm, bus, settings, tmp_path):
    log_path = tmp_path / "reflection.log"
    settings.reflection_log_path = str(log_path)

    candidate = _make_record("mem_004", importance=2, age_days=40)
    db.list_all.return_value = [candidate]
    llm.reflect_memory = AsyncMock(return_value={
        "action": "archive",
        "new_importance": None,
        "reason": "Obsolete",
    })

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    await task.run_once(triggered_by="scheduler")

    assert log_path.exists()
    entry = json.loads(log_path.read_text().strip())
    assert entry["triggered_by"] == "scheduler"
    assert entry["archived"] == 1
    assert len(entry["decisions"]) == 1
    assert entry["decisions"][0]["memory_id"] == "mem_004"


@pytest.mark.asyncio
async def test_run_once_needs_review_old_memory_is_candidate(db, vector_store, llm, bus, settings, tmp_path):
    settings.reflection_log_path = str(tmp_path / "reflection.log")
    # needs_review=True, 25 days old — threshold is 21
    candidate = _make_record("mem_005", importance=6, age_days=25, needs_review=True)
    db.list_all.return_value = [candidate]
    llm.reflect_memory = AsyncMock(return_value={
        "action": "keep",
        "new_importance": None,
        "reason": "Still valid",
    })

    task = ReflectionTask(db=db, vector_store=vector_store, llm=llm, bus=bus, settings=settings)
    summary = await task.run_once(triggered_by="api")

    assert summary["candidates_evaluated"] == 1


def test_is_within_window_true():
    from bearmemori.core.reflection import _is_within_window
    # 3am is within 2-6 window
    assert _is_within_window(current_hour=3, start_hour=2, end_hour=6) is True


def test_is_within_window_false():
    from bearmemori.core.reflection import _is_within_window
    # 10am is outside 2-6 window
    assert _is_within_window(current_hour=10, start_hour=2, end_hour=6) is False


def test_is_within_window_equals_start_equals_end_always_true():
    from bearmemori.core.reflection import _is_within_window
    # start == end means no restriction
    assert _is_within_window(current_hour=15, start_hour=4, end_hour=4) is True
```

**Step 2: Run to verify they fail**

```bash
uv run pytest tests/test_reflection.py -v
```

Expected: FAIL — `bearmemori.core.reflection` does not exist.

**Step 3: Create `bearmemori/core/reflection.py`**

```python
import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bearmemori.events.domain import SendMessage
from bearmemori.storage.models import MemoryRecord

logger = logging.getLogger(__name__)


def _is_within_window(current_hour: int, start_hour: int, end_hour: int) -> bool:
    """Return True if current_hour is within [start_hour, end_hour).

    If start_hour == end_hour, always returns True (no restriction).
    """
    if start_hour == end_hour:
        return True
    return start_hour <= current_hour < end_hour


def _is_candidate(record: MemoryRecord, settings) -> bool:
    """Return True if the record should be reviewed by reflection."""
    age_days = (datetime.now(UTC) - record.created_at).days
    if record.importance <= 2 and age_days >= settings.reflection_low_importance_age_days:
        return True
    if record.needs_review and age_days >= settings.reflection_needs_review_age_days:
        return True
    if 3 <= record.importance <= 7 and age_days >= settings.reflection_mid_importance_age_days:
        return True
    return False


class ReflectionTask:
    def __init__(self, db, vector_store, llm, bus, settings) -> None:
        self._db = db
        self._vector_store = vector_store
        self._llm = llm
        self._bus = bus
        self._settings = settings

    async def run_once(self, triggered_by: str = "scheduler") -> dict:
        run_id = f"ref_{uuid.uuid4().hex[:8]}"
        started_at = datetime.now(UTC)
        logger.info("Reflection run started: %s (triggered_by=%s)", run_id, triggered_by)

        all_records = self._db.list_all(limit=10000)
        candidates = [r for r in all_records if _is_candidate(r, self._settings)]

        archived = 0
        reranked = 0
        kept_unchanged = 0
        decisions = []

        for record in candidates:
            try:
                decision = await self._llm.reflect_memory(record)
            except Exception as e:
                logger.warning("reflect_memory failed for %s: %s", record.id, e)
                continue

            action = decision.get("action", "keep")
            new_importance = decision.get("new_importance")
            reason = decision.get("reason", "")

            old_importance = record.importance
            changed = False

            if action == "archive":
                record.archived = True
                self._db.update(record)
                self._vector_store.delete(record.id)
                archived += 1
                changed = True
            elif new_importance is not None:
                clamped = max(1, min(10, int(new_importance)))
                if clamped != record.importance:
                    record.importance = clamped
                    self._db.update(record)
                    self._vector_store.update(record)
                    reranked += 1
                    changed = True
                else:
                    kept_unchanged += 1
            else:
                kept_unchanged += 1

            decisions.append({
                "memory_id": record.id,
                "action": action,
                "old_importance": old_importance,
                "new_importance": new_importance,
                "reason": reason,
            })

        finished_at = datetime.now(UTC)
        summary = {
            "run_id": run_id,
            "triggered_by": triggered_by,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "candidates_evaluated": len(candidates),
            "archived": archived,
            "reranked": reranked,
            "kept_unchanged": kept_unchanged,
            "decisions": decisions,
        }

        self._write_log(summary)
        await self._notify(summary)

        logger.info(
            "Reflection run complete: %s — archived=%d reranked=%d kept=%d",
            run_id, archived, reranked, kept_unchanged,
        )
        return summary

    def _write_log(self, summary: dict) -> None:
        log_path = self._settings.reflection_log_path
        if not log_path:
            return
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a") as f:
                f.write(json.dumps(summary) + "\n")
        except OSError as e:
            logger.error("Failed to write reflection log: %s", e)

    async def _notify(self, summary: dict) -> None:
        archived = summary["archived"]
        reranked = summary["reranked"]
        kept = summary["kept_unchanged"]
        run_id = summary["run_id"]
        triggered_by = summary["triggered_by"]

        archived_titles = [
            d["memory_id"]
            for d in summary["decisions"]
            if d["action"] == "archive"
        ]

        lines = [
            f"Reflection complete ({run_id}, triggered by {triggered_by}):",
            f"  Archived: {archived}",
            f"  Reranked: {reranked}",
            f"  Kept unchanged: {kept}",
        ]
        if archived_titles:
            lines.append("  Archived memories: " + ", ".join(archived_titles[:10]))

        await self._bus.emit(SendMessage(chat_id="", text="\n".join(lines)))

    async def run(self) -> None:
        logger.info(
            "Reflection scheduler started (poll every %ds, window %d-%d)",
            self._settings.reflection_poll_interval_seconds,
            self._settings.reflection_start_hour,
            self._settings.reflection_end_hour,
        )
        while True:
            await asyncio.sleep(self._settings.reflection_poll_interval_seconds)
            now_local_hour = datetime.now(UTC).hour  # simplified; TZ conversion done below
            try:
                import zoneinfo
                tz = zoneinfo.ZoneInfo(self._settings.user_timezone)
                now_local_hour = datetime.now(tz).hour
            except Exception:
                pass

            if _is_within_window(
                now_local_hour,
                self._settings.reflection_start_hour,
                self._settings.reflection_end_hour,
            ):
                try:
                    await self.run_once(triggered_by="scheduler")
                except Exception:
                    logger.exception("Error during reflection run")
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_reflection.py -v
```

Expected: all PASS

**Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all PASS

**Step 6: Commit**

```bash
git add bearmemori/core/reflection.py tests/test_reflection.py
git commit -m "feat: add ReflectionTask with pre-filter, per-memory LLM review, logging and Telegram notification"
```

---

### Task 5: Add `POST /memory/reflection/run` API endpoint

**Files:**
- Modify: `bearmemori/api/routes.py`
- Modify: `tests/test_api.py` (add test)

**Step 1: Write the failing test**

Add to `tests/test_api.py`:

```python
def test_reflection_run_returns_summary(client_with_reflection):
    response = client_with_reflection.post("/memory/reflection/run")
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert "archived" in data
    assert "reranked" in data
    assert data["triggered_by"] == "api"


def test_reflection_run_returns_error_when_not_configured(client):
    # client fixture has no reflection_task
    response = client.post("/memory/reflection/run")
    assert response.status_code == 200
    assert response.json().get("error") is not None
```

Add a `client_with_reflection` fixture in `tests/test_api.py` (or `conftest.py`):

```python
@pytest.fixture
def client_with_reflection():
    from unittest.mock import AsyncMock, MagicMock
    from fastapi.testclient import TestClient
    from bearmemori.api.routes import create_app
    from bearmemori.core.reflection import ReflectionTask

    db = MagicMock()
    vector_store = MagicMock()
    pending_store = MagicMock()
    reflection_task = MagicMock(spec=ReflectionTask)
    reflection_task.run_once = AsyncMock(return_value={
        "run_id": "ref_abc123",
        "triggered_by": "api",
        "started_at": "2026-04-11T03:00:00+00:00",
        "finished_at": "2026-04-11T03:00:05+00:00",
        "candidates_evaluated": 0,
        "archived": 0,
        "reranked": 0,
        "kept_unchanged": 0,
        "decisions": [],
    })
    app = create_app(
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        reflection_task=reflection_task,
    )
    return TestClient(app)
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_api.py::test_reflection_run_returns_summary tests/test_api.py::test_reflection_run_returns_error_when_not_configured -v
```

Expected: FAIL — endpoint does not exist, `create_app` does not accept `reflection_task`.

**Step 3: Update `bearmemori/api/routes.py`**

Add `reflection_task` parameter to `create_app()`:

```python
from bearmemori.core.reflection import ReflectionTask

def create_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    pending_store: PendingStore,
    llm: LLMClient | None = None,
    reflection_task: ReflectionTask | None = None,
    user_timezone: str = "UTC",
    image_storage_dir: str = "",
) -> FastAPI:
```

Add the endpoint inside `create_app()`, after the `triage_conversation` route:

```python
@app.post("/memory/reflection/run")
async def run_reflection():
    if reflection_task is None:
        return {"error": "Reflection is not configured"}
    summary = await reflection_task.run_once(triggered_by="api")
    return summary
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_api.py -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/api/routes.py tests/test_api.py
git commit -m "feat: add POST /memory/reflection/run API endpoint"
```

---

### Task 6: Add `run_reflection` MCP tool

**Files:**
- Modify: `bearmemori/mcp/server.py`
- Create: `tests/mcp/test_reflection_tool.py`

**Step 1: Write the failing test**

Create `tests/mcp/test_reflection_tool.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from bearmemori.config import Settings
from bearmemori.core.reflection import ReflectionTask
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
    settings.image_storage_dir = ""
    llm = MagicMock(spec=LLMClient)
    pending_store = MagicMock(spec=PendingStore)
    reflection_task = MagicMock(spec=ReflectionTask)
    reflection_task.run_once = AsyncMock(return_value={
        "run_id": "ref_test",
        "triggered_by": "mcp",
        "started_at": "2026-04-11T03:00:00+00:00",
        "finished_at": "2026-04-11T03:00:01+00:00",
        "candidates_evaluated": 0,
        "archived": 0,
        "reranked": 0,
        "kept_unchanged": 0,
        "decisions": [],
    })
    return db, vector_store, settings, llm, pending_store, reflection_task


def test_create_mcp_app_accepts_reflection_task(mcp_deps):
    db, vector_store, settings, llm, pending_store, reflection_task = mcp_deps
    app = create_mcp_app(
        db=db,
        vector_store=vector_store,
        settings=settings,
        llm=llm,
        pending_store=pending_store,
        reflection_task=reflection_task,
    )
    assert app is not None


def test_create_mcp_app_without_reflection_task(mcp_deps):
    db, vector_store, settings, llm, pending_store, _ = mcp_deps
    # Should still work with reflection_task=None
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
uv run pytest tests/mcp/test_reflection_tool.py -v
```

Expected: FAIL — `create_mcp_app` does not accept `reflection_task`.

**Step 3: Update `bearmemori/mcp/server.py`**

Add import at the top:

```python
from bearmemori.core.reflection import ReflectionTask
```

Update `create_mcp_app()` signature:

```python
def create_mcp_app(
    db: MemoryDatabase,
    vector_store: VectorStore,
    settings: Settings,
    llm: LLMClient | None = None,
    pending_store: PendingStore | None = None,
    reflection_task: ReflectionTask | None = None,
):
```

Add the tool inside `create_mcp_app()`, after `triage_conversation` and before `app = mcp.sse_app()`:

```python
@mcp.tool(
    description=(
        "Trigger a memory reflection run. Reviews stored memories, archives low-value entries, "
        "and reranks importance scores. Returns a summary of what changed. "
        "This bypasses the scheduled time window and runs immediately."
    )
)
async def run_reflection() -> dict:
    if reflection_task is None:
        return {"error": "Reflection is not configured on this server"}
    return await reflection_task.run_once(triggered_by="mcp")
```

**Step 4: Run MCP tests to verify they pass**

```bash
uv run pytest tests/mcp/ -v
```

Expected: all PASS

**Step 5: Commit**

```bash
git add bearmemori/mcp/server.py tests/mcp/test_reflection_tool.py
git commit -m "feat: add run_reflection MCP tool"
```

---

### Task 7: Wire `ReflectionTask` in `app.py` and `__main__.py`

**Files:**
- Modify: `bearmemori/app.py`
- Modify: `bearmemori/__main__.py`

**Step 1: Update `bearmemori/app.py`**

7a. Add import:

```python
from bearmemori.core.reflection import ReflectionTask
```

7b. Add `reflection_task` to the `Application` dataclass `__init__` parameter list and as an attribute:

```python
class Application:
    def __init__(
        self,
        ...
        scheduler: ReminderScheduler,
        reflection_task: ReflectionTask,
    ) -> None:
        ...
        self.scheduler = scheduler
        self.reflection_task = reflection_task
```

7c. In `create_application()`, instantiate `ReflectionTask` after the `scheduler` creation:

```python
reflection_task = ReflectionTask(
    db=db,
    vector_store=vector_store,
    llm=llm,
    bus=bus,
    settings=settings,
)
```

7d. Pass `reflection_task` to `Application(...)`:

```python
application = Application(
    ...
    scheduler=scheduler,
    reflection_task=reflection_task,
)
```

7e. Pass `reflection_task` to `create_api_app(...)`:

```python
api = create_api_app(
    db=db,
    vector_store=vector_store,
    pending_store=pending_store,
    llm=llm,
    reflection_task=reflection_task,
    user_timezone=settings.user_timezone,
    image_storage_dir=settings.image_storage_dir,
)
```

7f. Pass `reflection_task` to `create_mcp_app(...)`:

```python
mcp_asgi = create_mcp_app(
    db=db,
    vector_store=vector_store,
    settings=settings,
    llm=llm,
    pending_store=pending_store,
    reflection_task=reflection_task,
)
```

**Step 2: Update `bearmemori/__main__.py`**

Add the reflection background task after `asyncio.create_task(application.cleanup_task.run())`:

```python
asyncio.create_task(application.reflection_task.run())
```

**Step 3: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all PASS

**Step 4: Run linter**

```bash
uv run ruff check .
uv run ruff format --check .
```

Fix any issues:

```bash
uv run ruff check --fix .
uv run ruff format .
```

**Step 5: Commit**

```bash
git add bearmemori/app.py bearmemori/__main__.py
git commit -m "chore: wire ReflectionTask into application and start background loop"
```

---

### Task 8: Final verification

**Step 1: Run full test suite and linter**

```bash
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
```

Expected: all tests PASS, no lint errors.

**Step 2: Commit any formatting fixes if needed**

```bash
git add -u
git commit -m "chore: apply ruff formatting fixes"
```
