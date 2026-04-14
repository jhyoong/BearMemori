# Refactor & Simplification Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce BearMemori's complexity in three phases — safe cleanup, internal refactoring, and structural changes — without altering any external behavior until Phase 3.

**Architecture:** Remove dead code and unused config first (Phase 1, zero risk), then extract a shared MemoryService to eliminate triple CRUD duplication and simplify app wiring (Phase 2, internal only), then unify auth, trim the CLI, and fix silent failures (Phase 3, observable changes).

**Tech Stack:** Python 3.12, FastAPI, Starlette, pytest, uv

---

## PHASE 1 — Safe Cleanup

---

### Task 1: Delete dead code and update affected tests

Three symbols exist only in tests or are never called in production.

**Files:**
- Modify: `bearmemori/storage/pending_store.py:56-60`
- Modify: `bearmemori/core/queue.py:19-20`
- Modify: `bearmemori/core/followup.py:14-15`
- Modify: `tests/test_pending_store.py:45-51`
- Modify: `tests/test_queue.py:29`
- Modify: `tests/test_followup.py:30`

**Step 1: Delete `PendingStore.cleanup()` from `pending_store.py`**

Remove lines 56-60 entirely:
```python
# DELETE these lines:
def cleanup(self) -> int:
    expired = [pid for pid, item in self._store.items() if self._is_expired(item)]
    for pid in expired:
        del self._store[pid]
    return len(expired)
```

**Step 2: Update `test_cleanup` in `tests/test_pending_store.py`**

The test at lines 45-51 calls the now-deleted `cleanup()`. Replace it to use `cleanup_with_details()`:

```python
def test_cleanup():
    store = PendingStore(default_ttl=1)
    store.add(_make_draft())
    store.add(_make_draft())
    time.sleep(1.1)
    expired = store.cleanup_with_details()
    assert len(expired) == 2
```

**Step 3: Run affected tests to verify**

```
uv run pytest tests/test_pending_store.py -v
```
Expected: all PASS.

**Step 4: Delete `QueueManager.size()` from `queue.py`**

Remove lines 19-20 entirely:
```python
# DELETE these lines:
def size(self) -> int:
    return len(self._heap)
```

**Step 5: Update `test_queue.py` to not use `size()`**

Line 29: `assert queue.size() == 1` — replace with:
```python
assert len(queue._heap) == 1
```

**Step 6: Run queue tests**

```
uv run pytest tests/test_queue.py -v
```
Expected: all PASS.

**Step 7: Delete `FollowUpManager.has_active_followup()` from `followup.py`**

Remove lines 14-15 entirely:
```python
# DELETE these lines:
def has_active_followup(self, chat_id: str) -> bool:
    return chat_id in self._active
```

**Step 8: Update `test_followup.py` — remove use of `has_active_followup`**

Line 30: `assert manager.has_active_followup("123")` — replace with:
```python
assert "123" in manager._active
```

**Step 9: Run followup tests**

```
uv run pytest tests/test_followup.py -v
```
Expected: all PASS.

**Step 10: Run full test suite to confirm no regressions**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 11: Commit**

```bash
git add bearmemori/storage/pending_store.py bearmemori/core/queue.py bearmemori/core/followup.py tests/test_pending_store.py tests/test_queue.py tests/test_followup.py
git commit -m "refactor: remove dead code (cleanup, size, has_active_followup)"
```

---

### Task 2: Remove unused config settings

Six settings in `config.py` are defined but never read by any production code. The actual values are hardcoded at the call sites.

**Files:**
- Modify: `bearmemori/config.py:33-43`

**Step 1: Delete the six settings from `Settings`**

Remove these lines from `bearmemori/config.py`:
```python
# DELETE:
retrieval_top_k: int = 5          # line 33
upcoming_events_days: int = 7      # line 34
importance_high_threshold: int = 8  # line 40
importance_low_threshold: int = 2   # line 41
importance_relevance_weight: float = 0.5  # line 42
importance_weight: float = 0.5     # line 43
```

**Step 2: Check for any use of these in tests**

```
uv run grep -r "retrieval_top_k\|upcoming_events_days\|importance_high_threshold\|importance_low_threshold\|importance_relevance_weight\|importance_weight" tests/
```

If any test accesses these settings, remove those attribute accesses too.

**Step 3: Run config tests**

```
uv run pytest tests/test_config.py tests/test_reflection_config.py -v
```
Expected: all PASS.

**Step 4: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add bearmemori/config.py
git commit -m "refactor: remove unused config settings"
```

---

### Task 3: Fix two small bugs

**Files:**
- Modify: `bearmemori/app.py:172-188`
- Modify: `bearmemori/core/reflection.py:163-168`

**Step 1: Fix double-instantiation of `WebappAuthMiddleware` in `app.py`**

Lines 172-188 currently look like:
```python
if settings.webapp_secret:
    webapp_auth = WebappAuthMiddleware(           # line 173 — instantiated and discarded
        api, settings.webapp_secret, secure_cookie=settings.webapp_secure_cookie
    )
    webapp_router = create_webapp_router(
        db,
        vector_store,
        webapp_auth,                              # passed here
        image_storage_dir=settings.image_storage_dir,
        user_timezone=settings.user_timezone,
    )
    api.include_router(webapp_router)
    api.add_middleware(                           # also instantiated here — this is the real one
        WebappAuthMiddleware,
        secret=settings.webapp_secret,
        secure_cookie=settings.webapp_secure_cookie,
    )
```

The `webapp_auth` instance at line 173 is discarded — `add_middleware` creates a fresh one. But `webapp_auth` is passed to `create_webapp_router`. Check `bearmemori/webapp/router.py` to see what `create_webapp_router` does with `webapp_auth`.

Read `bearmemori/webapp/router.py` lines 1-30 to understand `create_webapp_router`'s signature before making changes — the `webapp_auth` parameter may be used for `create_session_cookie` on the login route. If so, the fix is to keep `webapp_auth` as a standalone instance but remove the redundant `add_middleware` call and mount the middleware a different way — or pass the secret directly so the router creates its own instance. Adapt the fix based on what you find.

The key outcome: `WebappAuthMiddleware` should only be instantiated once for the middleware chain.

**Step 2: Fix `reflection.py` UTC hour variable shadowing**

Lines 163-168:
```python
now_local_hour = datetime.now(UTC).hour   # sets UTC hour — misleadingly named
try:
    tz = zoneinfo.ZoneInfo(self._settings.user_timezone)
    now_local_hour = datetime.now(tz).hour  # immediately overwrites
except Exception:
    pass
```

Replace with:
```python
try:
    tz = zoneinfo.ZoneInfo(self._settings.user_timezone)
    now_local_hour = datetime.now(tz).hour
except Exception:
    now_local_hour = datetime.now(UTC).hour  # fallback to UTC
```

This makes the intent clear: local hour with UTC as fallback.

**Step 3: Run relevant tests**

```
uv run pytest tests/test_app.py tests/test_reflection.py tests/test_webapp.py tests/test_webapp_auth.py -v
```
Expected: all PASS.

**Step 4: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add bearmemori/app.py bearmemori/core/reflection.py
git commit -m "fix: remove discarded middleware instance and clarify reflection UTC fallback"
```

---

### Task 4: Deduplicate LLM system prompt constants

`llm/client.py` contains 180+ lines of system prompts. The category enum and importance scale are defined ~3 times each. `_EXTRACT_SYSTEM_TEMPLATE` and `_EXTRACTION_SYSTEM_TEMPLATE` (lines 67-92 and 161-201) define overlapping extraction instructions. `EXTRACT_SYSTEM_PROMPT` (line 95) is a backward-compat alias.

**Files:**
- Modify: `bearmemori/llm/client.py:51-242`

**Step 1: Read the full system prompt section**

Read `bearmemori/llm/client.py` lines 51-242 fully to map every place `_CATEGORY_ENUM` and `_IMPORTANCE_SCALE` content appears inline before editing.

**Step 2: Add shared constants at the top of the prompt section**

After line 50 (after the `logger` line), add:

```python
_CATEGORY_ENUM = (
    'Categories: profile, general, event, location, task, reminder\n'
    '- "profile": Stable facts about the user (preferences, identity, relationships)\n'
    '- "general": Non-time-bound useful information (prices, recommendations, facts)\n'
    '- "event": Time-bound commitments, reminders, appointments\n'
    '- "location": Places, addresses, venues the user mentions\n'
    '- "task": Action items, to-dos\n'
    '- "reminder": Triggered notifications with scheduling'
)

_IMPORTANCE_SCALE = (
    "Importance (1-10 integer):\n"
    "- 1-3: Low importance (trivial facts, casual mentions)\n"
    "- 4-6: Medium importance (useful information, general preferences)\n"
    "- 7-8: High importance (key personal facts, significant events, strong preferences)\n"
    "- 9-10: Critical importance (core identity, health/safety, major life events)"
)
```

**Step 3: Replace inline definitions in each prompt with the constants**

In `CLASSIFY_SYSTEM_PROMPT`, `_EXTRACT_SYSTEM_TEMPLATE`, `_TRIAGE_SYSTEM_TEMPLATE`, `_EXTRACTION_SYSTEM_TEMPLATE`, and `DESCRIBE_IMAGE_SYSTEM_PROMPT`, replace the inline category and importance text with `{_CATEGORY_ENUM}` / `{_IMPORTANCE_SCALE}` or concatenation as fits the prompt's format. Only change the deduplicated lines, not the surrounding instructions.

**Step 4: Assess `_EXTRACT_SYSTEM_TEMPLATE` vs `_EXTRACTION_SYSTEM_TEMPLATE`**

Read both carefully. If their extraction instructions are equivalent (same fields, same format), delete `_EXTRACTION_SYSTEM_TEMPLATE` and update all call sites to use `_EXTRACT_SYSTEM_TEMPLATE`. Search for usages:

```
uv run grep -n "_EXTRACTION_SYSTEM_TEMPLATE\|_EXTRACT_SYSTEM_TEMPLATE" bearmemori/llm/client.py
```

Consolidate to whichever is used more broadly.

**Step 5: Remove the backward-compat alias**

Delete line 95:
```python
# DELETE:
EXTRACT_SYSTEM_PROMPT = _EXTRACT_SYSTEM_TEMPLATE.format(current_time="(not provided)")
```

Search for any usage of `EXTRACT_SYSTEM_PROMPT` outside of `client.py`:
```
uv run grep -rn "EXTRACT_SYSTEM_PROMPT" bearmemori/ tests/
```
If found, update those callers to use `_EXTRACT_SYSTEM_TEMPLATE.format(current_time=...)` directly.

**Step 6: Run LLM tests**

```
uv run pytest tests/test_llm_client.py tests/test_importance_extraction.py -v
```
Expected: all PASS.

**Step 7: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 8: Commit**

```bash
git add bearmemori/llm/client.py
git commit -m "refactor: deduplicate LLM system prompt constants"
```

---

## PHASE 2 — Internal Refactoring

---

### Task 5: Create MemoryService

The `retrieve_context` scoring algorithm and all CRUD operations are duplicated across `api/routes.py`, `webapp/router.py`, and `mcp/server.py`. Extract all of it into a single service class.

**Files:**
- Create: `bearmemori/core/memory_service.py`
- Create: `tests/core/test_memory_service.py` (create `tests/core/` if it doesn't exist)

**Step 1: Read the source material**

Read these in full before writing anything:
- `bearmemori/api/routes.py` lines 139-500 (the CRUD endpoints)
- `bearmemori/storage/database.py` (understand available db methods)
- `bearmemori/storage/vector_store.py` (understand available vs methods)
- `bearmemori/storage/models.py` (MemoryDraft, MemoryRecord, MemoryCategory)

**Step 2: Write the tests first**

Create `tests/core/test_memory_service.py`:

```python
import pytest
from unittest.mock import MagicMock, AsyncMock
from bearmemori.core.memory_service import MemoryService
from bearmemori.storage.models import MemoryCategory, MemoryDraft, MemoryRecord


@pytest.fixture
def db():
    return MagicMock()


@pytest.fixture
def vector_store():
    return MagicMock()


@pytest.fixture
def service(db, vector_store):
    return MemoryService(db=db, vector_store=vector_store)


def test_search_delegates_to_vector_store(service, vector_store):
    vector_store.search.return_value = [{"id": "mem_1", "document": "test"}]
    results = service.search("query", top_k=3)
    vector_store.search.assert_called_once_with(query="query", top_k=3, category=None)
    assert len(results) == 1


def test_get_delegates_to_db(service, db):
    db.get.return_value = None
    result = service.get("mem_abc")
    db.get.assert_called_once_with("mem_abc")
    assert result is None


def test_delete_calls_db_and_vector_store(service, db, vector_store):
    db.get.return_value = MagicMock(image_path=None)
    service.delete("mem_abc")
    db.delete.assert_called_once_with("mem_abc")
    vector_store.delete.assert_called_once_with("mem_abc")


def test_retrieve_context_scores_results(service, vector_store, db):
    vector_store.search.return_value = [
        {"id": "mem_1", "document": "high imp", "distance": 0.1,
         "metadata": {"importance": 9}},
        {"id": "mem_2", "document": "low imp", "distance": 0.5,
         "metadata": {"importance": 1}},
    ]
    db.get_upcoming_events.return_value = []
    result = service.retrieve_context("query", top_k=5)
    # high importance item should appear in results
    assert any("high imp" in item["document"] for item in result["items"])
```

**Step 3: Run the tests — expect failure**

```
uv run pytest tests/core/test_memory_service.py -v
```
Expected: FAIL with `ModuleNotFoundError` or `ImportError`.

**Step 4: Implement `MemoryService`**

Create `bearmemori/core/memory_service.py`:

```python
import logging
import uuid
from pathlib import Path

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import MemoryCategory, MemoryDraft, MemoryRecord, MemorySource
from bearmemori.storage.vector_store import VectorStore

logger = logging.getLogger(__name__)


class MemoryService:
    def __init__(
        self,
        db: MemoryDatabase,
        vector_store: VectorStore,
        image_storage_dir: str = "",
    ) -> None:
        self._db = db
        self._vector_store = vector_store
        self._image_storage_dir = image_storage_dir

    def search(self, query: str, top_k: int = 5, category: str | None = None) -> list[dict]:
        return self._vector_store.search(query=query, top_k=top_k, category=category)

    def retrieve_context(self, query: str, top_k: int = 5, event_days: int = 7) -> dict:
        semantic_results = self._vector_store.search(query=query, top_k=top_k * 2)
        upcoming_events = self._db.get_upcoming_events(days=event_days)

        scored = []
        for r in semantic_results:
            distance = r.get("distance", 1.0)
            similarity = max(0.0, 1.0 - distance)
            importance = r.get("metadata", {}).get("importance", 5) / 10.0
            combined = 0.5 * similarity + 0.5 * importance
            scored.append((combined, r))
        scored.sort(key=lambda x: x[0], reverse=True)

        filtered = []
        for score, r in scored:
            imp = r.get("metadata", {}).get("importance", 5)
            distance = r.get("distance", 1.0)
            similarity = max(0.0, 1.0 - distance)
            if imp <= 2 and similarity < 0.7:
                continue
            filtered.append(r)
            if len(filtered) >= top_k:
                break

        high_imp = [
            r for _, r in scored
            if r.get("metadata", {}).get("importance", 5) >= 8 and r not in filtered
        ]
        filtered.extend(high_imp[: max(0, top_k - len(filtered))])

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

        items = filtered + [
            {"id": e.id, "document": f"{e.title}: {e.content}",
             "metadata": {"category": e.category.value}}
            for e in upcoming_events
        ]
        return {"context_block": "\n".join(lines) if lines else "", "items": items}

    def list(
        self,
        category: str | None = None,
        needs_review: bool | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[MemoryRecord]:
        limit = min(limit, 200)
        if category is not None:
            cat = MemoryCategory(category)
            records = self._db.list_by_category(cat)
        else:
            records = self._db.list_all()
        if needs_review is not None:
            records = [r for r in records if r.needs_review == needs_review]
        return records[offset: offset + limit]

    def get(self, record_id: str) -> MemoryRecord | None:
        return self._db.get(record_id)

    def create(self, draft: MemoryDraft) -> MemoryRecord:
        record_id = f"mem_{uuid.uuid4().hex[:12]}"
        record = MemoryRecord.from_draft(draft, record_id=record_id)
        self._db.create(record)
        self._vector_store.add(record)
        logger.info("Created memory: %s", record_id)
        return record

    def update(self, record_id: str, updates: dict) -> MemoryRecord | None:
        record = self._db.get(record_id)
        if record is None:
            return None
        allowed = {"title", "content", "category", "tags", "needs_review",
                   "importance", "event_status", "event_datetime", "event_recurrence"}
        for key, value in updates.items():
            if key not in allowed:
                continue
            if key == "category":
                record.category = MemoryCategory(value)
            elif key == "event_status" and record.event_fields:
                record.event_fields.status = value
            elif key == "event_datetime" and record.event_fields:
                record.event_fields.datetime = value
            elif key == "event_recurrence" and record.event_fields:
                record.event_fields.recurrence = value
            else:
                setattr(record, key, value)
        self._db.update(record)
        self._vector_store.update(record)
        return record

    def delete(self, record_id: str) -> bool:
        self._delete_image(record_id)
        deleted = self._db.delete(record_id)
        if deleted:
            self._vector_store.delete(record_id)
        return deleted

    def bulk_delete(self, record_ids: list[str]) -> int:
        count = 0
        for record_id in record_ids:
            if self.delete(record_id):
                count += 1
        return count

    def bulk_update(self, record_ids: list[str], updates: dict) -> int:
        count = 0
        for record_id in record_ids:
            if self.update(record_id, updates) is not None:
                count += 1
        return count

    def _delete_image(self, record_id: str) -> None:
        if not self._image_storage_dir:
            return
        record = self._db.get(record_id)
        if record and record.image_path:
            file_path = Path(self._image_storage_dir) / record.image_path
            if file_path.exists():
                file_path.unlink()
                logger.info("Deleted image: %s", file_path)
```

**Step 5: Run service tests**

```
uv run pytest tests/core/test_memory_service.py -v
```
Expected: all PASS.

**Step 6: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS (MemoryService not yet wired in, no regressions).

**Step 7: Commit**

```bash
git add bearmemori/core/memory_service.py tests/core/test_memory_service.py
git commit -m "feat: add MemoryService to consolidate CRUD and retrieve_context logic"
```

---

### Task 6: Wire API routes to MemoryService

Replace inline CRUD and retrieve_context logic in `api/routes.py` with calls to `MemoryService`.

**Files:**
- Modify: `bearmemori/api/routes.py`
- Modify: `bearmemori/app.py`

**Step 1: Read `api/routes.py` in full**

Read `bearmemori/api/routes.py` completely before editing.

**Step 2: Add `MemoryService` to `create_app` signature**

In `api/routes.py`, update `create_app` to accept a `memory_service: MemoryService` parameter alongside the existing ones.

**Step 3: Replace each CRUD handler**

For each of these endpoints, replace the inline `db.*` / `vector_store.*` calls with `memory_service.*`:

- `GET /memory/search` → `memory_service.search(query, top_k, category)`
- `GET /memory/retrieve` → `memory_service.retrieve_context(query_context, top_k, event_days)`
- `GET /memory/list` → `memory_service.list(category, needs_review, offset, limit)`
- `GET /memory/{record_id}` → `memory_service.get(record_id)`
- `POST /memory/direct` (create) → `memory_service.create(draft)`
- `PUT /memory/{record_id}` → `memory_service.update(record_id, updates_dict)`
- `DELETE /memory/{record_id}` → `memory_service.delete(record_id)`
- `POST /memory/bulk/delete` → `memory_service.bulk_delete(record_ids)`
- `POST /memory/bulk/update` → `memory_service.bulk_update(record_ids, updates)`

Remove the `_delete_image` closure (it moves into `MemoryService`). Keep `db`, `vector_store`, `pending_store`, `llm`, and `reflection_task` parameters — they are still needed for triage, confirm, and events endpoints.

**Step 4: Update `app.py` to instantiate and pass `MemoryService`**

In `bearmemori/app.py`, after the existing storage instantiation, add:

```python
from bearmemori.core.memory_service import MemoryService

memory_service = MemoryService(
    db=db,
    vector_store=vector_store,
    image_storage_dir=settings.image_storage_dir,
)
```

Pass `memory_service=memory_service` to `create_api_app(...)`.

**Step 5: Run API tests**

```
uv run pytest tests/test_api.py tests/test_routes_triage_time.py tests/api/ -v
```
Expected: all PASS.

**Step 6: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 7: Commit**

```bash
git add bearmemori/api/routes.py bearmemori/app.py
git commit -m "refactor: wire API routes to MemoryService"
```

---

### Task 7: Wire webapp router to MemoryService

Replace inline db/vector_store calls in `webapp/router.py` with MemoryService.

**Files:**
- Modify: `bearmemori/webapp/router.py`
- Modify: `bearmemori/app.py`

**Step 1: Read `webapp/router.py` in full**

Read `bearmemori/webapp/router.py` completely before editing.

**Step 2: Update `create_webapp_router` signature**

Add `memory_service: MemoryService` parameter. Remove `vector_store` if its only use is search (which will move to MemoryService). Keep `db` if the webapp uses db methods not covered by MemoryService (e.g., calendar queries, `search_keyword`).

**Step 3: Replace CRUD calls**

For each route that does list, get, create, update, delete, bulk operations — replace with `memory_service.*` calls. Remove the `_delete_image_file` closure since that logic lives in `MemoryService.delete()`.

Keep `db` for calendar-specific queries (`get_events_in_range`, `get_upcoming_events`) and FTS5 keyword search (`search_keyword`) if those remain.

**Step 4: Update `app.py` to pass `memory_service` to `create_webapp_router`**

```python
webapp_router = create_webapp_router(
    db,
    memory_service,            # replaces vector_store
    webapp_auth,
    image_storage_dir=settings.image_storage_dir,
    user_timezone=settings.user_timezone,
)
```

**Step 5: Run webapp tests**

```
uv run pytest tests/test_webapp.py tests/test_webapp_auth.py -v
```
Expected: all PASS.

**Step 6: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 7: Commit**

```bash
git add bearmemori/webapp/router.py bearmemori/app.py
git commit -m "refactor: wire webapp router to MemoryService"
```

---

### Task 8: Wire MCP server to MemoryService

Replace duplicated CRUD and retrieve_context logic in `mcp/server.py` with MemoryService.

**Files:**
- Modify: `bearmemori/mcp/server.py`
- Modify: `bearmemori/app.py`

**Step 1: Read `mcp/server.py` in full**

Read `bearmemori/mcp/server.py` completely before editing.

**Step 2: Update `create_mcp_app` signature**

Add `memory_service: MemoryService` parameter.

**Step 3: Replace duplicated tool implementations**

For each MCP tool that currently re-implements list, search, get, create, update, delete, retrieve_context, bulk operations — replace with `memory_service.*` calls. The `retrieve_context` tool in MCP is the most important (it is a verbatim copy of the algorithm now in MemoryService).

Keep `llm`, `pending_store`, and triage-related code — those remain local to MCP.

**Step 4: Update `app.py`**

Pass `memory_service=memory_service` to `create_mcp_app(...)`.

**Step 5: Run MCP tests**

```
uv run pytest tests/mcp/ -v
```
Expected: all PASS.

**Step 6: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 7: Commit**

```bash
git add bearmemori/mcp/server.py bearmemori/app.py
git commit -m "refactor: wire MCP server to MemoryService, remove retrieve_context duplication"
```

---

### Task 9: Remove `CreateMemoryRequest`, use `MemoryDraft` directly

`api/schemas.py` has a `CreateMemoryRequest` that mirrors `MemoryDraft` from `storage/models.py`. Consolidate.

**Files:**
- Modify: `bearmemori/api/schemas.py:30-38`
- Modify: `bearmemori/api/routes.py` (the create endpoint)

**Step 1: Read `storage/models.py` to understand `MemoryDraft`**

Read `bearmemori/storage/models.py` to confirm `MemoryDraft` has all the same fields as `CreateMemoryRequest`.

**Step 2: Update the create endpoint in `routes.py`**

Change the `POST /memory/direct` endpoint to accept `MemoryDraft` instead of `CreateMemoryRequest`. The conversion logic (string → enum, building EventFields) should already be handled by MemoryDraft's validators or can be done inline.

**Step 3: Delete `CreateMemoryRequest` from `schemas.py`**

Remove lines 30-38 from `bearmemori/api/schemas.py`. Remove its import from `routes.py`.

**Step 4: Run API tests**

```
uv run pytest tests/test_api.py -v
```
Expected: all PASS.

**Step 5: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 6: Commit**

```bash
git add bearmemori/api/schemas.py bearmemori/api/routes.py
git commit -m "refactor: replace CreateMemoryRequest with MemoryDraft in API"
```

---

### Task 10: Fix source_chat_id dual source of truth and remove `Application` class

Two cleanups that both touch `app.py`.

**Files:**
- Modify: `bearmemori/core/scheduler.py:80-83`
- Modify: `bearmemori/app.py:39-68, 144-208`
- Modify: `bearmemori/__main__.py`

**Step 1: Audit record creation paths**

Search for everywhere `MemoryRecord` is created to confirm `source` is always set:
```
uv run grep -n "MemoryRecord.from_draft\|MemoryRecord(" bearmemori/ -r
```

Check each call site: does it set `source` on the resulting record? The key places are `confirm_handler.py` and `memory_service.py`.

In `api/routes.py` line 125-129, `source` is set conditionally on `request.source_chat_id`. For the direct create endpoint and any path where `source_chat_id` is absent, `record.source` may be None — which is legitimate. The scheduler fallback exists for this case.

**Step 2: Decide on the fix scope**

If some records legitimately have no `source` (created via API without a chat_id), the fallback in `_get_chat_id` is necessary. In that case: delete only the `metadata["source_chat_id"]` fallback (the metadata half), and return empty string when `record.source` is None:

```python
def _get_chat_id(self, record) -> str:
    if record.source:
        return record.source.chat_id
    return ""
```

Also remove the line in `routes.py` that writes `source_chat_id` into `metadata`:
```python
# DELETE in routes.py confirm_pending:
record.metadata["source_chat_id"] = request.source_chat_id
```

**Step 3: Run scheduler tests**

```
uv run pytest tests/test_scheduler.py -v
```
Expected: all PASS.

**Step 4: Remove the `Application` class from `app.py`**

The `Application` class (lines 39-68) is a pure data holder used only so `__main__.py` can access components via `api.state.application`. Replace it:

In `app.py`, delete the class definition and replace:
```python
application = Application(...)
...
api.state.application = application
```

With individual attributes:
```python
api.state.bus = bus
api.state.db = db
api.state.vector_store = vector_store
api.state.pending_store = pending_store
api.state.queue_manager = queue_manager
api.state.processor = processor
api.state.followup_manager = followup_manager
api.state.confirm_handler = confirm_handler
api.state.cleanup_task = cleanup_task
api.state.telegram = telegram
api.state.settings = settings
api.state.scheduler = scheduler
api.state.reflection_task = reflection_task
```

**Step 5: Update `__main__.py` to access components directly**

Read `bearmemori/__main__.py` fully. Anywhere it accesses `app.state.application.X`, change to `app.state.X`.

**Step 6: Remove the `Application` import from `app.py`** if it was exported.

**Step 7: Run app tests**

```
uv run pytest tests/test_app.py -v
```
Expected: all PASS.

**Step 8: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 9: Commit**

```bash
git add bearmemori/core/scheduler.py bearmemori/app.py bearmemori/__main__.py bearmemori/api/routes.py
git commit -m "refactor: remove Application class and simplify source_chat_id storage"
```

---

### Task 11: Remove LLM wrapper classes

Three nested wrapper classes (`_AsyncCompletionsWrapper`, `_ChatWrapper`, `_ClientWrapper`) exist solely to make `AsyncOpenAI.chat.completions.create` patchable in tests. Replace the approach with mock injection.

**Files:**
- Modify: `bearmemori/llm/client.py:256-293`
- Modify: `tests/test_llm_client.py`

**Step 1: Read `tests/test_llm_client.py` in full**

Understand how tests currently patch the client.

**Step 2: Read `llm/client.py` lines 256-310 in full**

Understand the wrapper chain and how `LLMClient` uses it.

**Step 3: Update `LLMClient.__init__` to accept an optional client parameter**

Replace the wrapper construction with direct `AsyncOpenAI` instantiation:

```python
class LLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "not-needed",
        user_timezone: str = "UTC",
        _client=None,  # injectable for tests
    ) -> None:
        self._client = _client or AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._model = model
        self._user_timezone = user_timezone
```

All `self._client.chat.completions.create(...)` calls remain the same — but now `_client` is the real `AsyncOpenAI` object.

**Step 4: Delete the three wrapper classes**

Remove `_AsyncCompletionsWrapper` (lines 256-269), `_ChatWrapper` (272-274), and `_ClientWrapper` (277-282) entirely.

**Step 5: Update `tests/test_llm_client.py`**

Replace any `patch.object(client._client.chat.completions, ...)` style mocking with injecting a mock client at construction time:

```python
@pytest.fixture
def mock_openai_client():
    client = MagicMock()
    client.chat.completions.create = AsyncMock()
    return client

@pytest.fixture
def llm(mock_openai_client):
    return LLMClient(
        base_url="http://test",
        model="test-model",
        _client=mock_openai_client,
    )
```

Each test then sets `mock_openai_client.chat.completions.create.return_value` to a mock response.

**Step 6: Run LLM client tests**

```
uv run pytest tests/test_llm_client.py -v
```
Expected: all PASS.

**Step 7: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 8: Commit**

```bash
git add bearmemori/llm/client.py tests/test_llm_client.py
git commit -m "refactor: remove AsyncOpenAI wrapper classes, use injectable client in tests"
```

---

### Task 12: Deduplicate processor follow-up logic

`processor.py` has the same follow-up emission block in two places: the text path (lines 37-48) and the image caption path (lines 86-97).

**Files:**
- Modify: `bearmemori/core/processor.py:37-48, 86-97`

**Step 1: Read `processor.py` in full**

**Step 2: Extract `_emit_followup_required`**

Add this private method to `Processor`:

```python
async def _emit_followup_required(self, item: QueueItem, text: str) -> None:
    question = await self._llm.generate_followup(text, item.context)
    context = item.context or {"messages": []}
    context["messages"].append({"role": "user", "content": text})
    context["messages"].append({"role": "assistant", "content": question})
    await self._bus.emit(
        FollowUpRequired(
            question=question,
            source_chat_id=item.source_chat_id,
            context=context,
        )
    )
```

**Step 3: Replace both duplicate blocks**

In `process_item` (lines 37-48), replace the follow-up block with:
```python
await self._emit_followup_required(item, text)
return
```

In `_process_image` (lines 86-97), replace the follow-up block with:
```python
await self._emit_followup_required(item, caption)
return
```

**Step 4: Run processor tests**

```
uv run pytest tests/test_processor.py -v
```
Expected: all PASS.

**Step 5: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 6: Commit**

```bash
git add bearmemori/core/processor.py
git commit -m "refactor: extract _emit_followup_required to remove duplication in Processor"
```

---

## PHASE 3 — Structural Changes

---

### Task 13: Unify auth middleware

Two separate auth implementations protect the same single user:
- `WebappAuthMiddleware` (session cookie + HMAC) — `webapp/auth.py`
- `BearerAuthMiddleware` (Bearer token) — `mcp/server.py`

Consolidate to one middleware that accepts either.

**Files:**
- Modify: `bearmemori/webapp/auth.py`
- Modify: `bearmemori/mcp/server.py:15-30`
- Modify: `bearmemori/app.py`

**Step 1: Read `webapp/auth.py` and `mcp/server.py` lines 15-30 in full**

**Step 2: Extend `WebappAuthMiddleware.dispatch` to also accept Bearer tokens**

The MCP sub-app is mounted at `/mcp`. Update `WebappAuthMiddleware.dispatch` to handle `/mcp` paths with Bearer token auth:

```python
async def dispatch(self, request: Request, call_next):
    path = request.url.path

    # MCP paths: accept Bearer token
    if path.startswith("/mcp"):
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], self._secret):
            return await call_next(request)
        return Response("Unauthorized", status_code=401)

    # Webapp paths: existing cookie logic
    if not path.startswith("/webapp"):
        return await call_next(request)
    if path in ("/webapp/login",) or path.startswith("/webapp/static"):
        return await call_next(request)
    session_token = request.cookies.get("webapp_session")
    if not session_token or not hmac.compare_digest(session_token, self._token):
        return RedirectResponse(url="/webapp/login", status_code=302)
    return await call_next(request)
```

Note: import `Response` from `starlette.responses` (already available via FastAPI).

**Step 3: Delete `BearerAuthMiddleware` from `mcp/server.py`**

Remove lines 15-30. Remove its usage from `create_mcp_app` — since the unified middleware applied at the top level now handles `/mcp` paths, the sub-app no longer needs its own auth.

**Step 4: Update tests for unified auth**

Read `tests/test_webapp_auth.py` and add tests for the `/mcp` Bearer token path:

```python
def test_mcp_bearer_auth_accepted(test_app, secret):
    # Bearer token matches secret
    response = test_app.get("/mcp/health", headers={"Authorization": f"Bearer {secret}"})
    assert response.status_code != 401

def test_mcp_bearer_auth_rejected(test_app):
    response = test_app.get("/mcp/health", headers={"Authorization": "Bearer wrongsecret"})
    assert response.status_code == 401

def test_mcp_no_auth_rejected(test_app):
    response = test_app.get("/mcp/health")
    assert response.status_code == 401
```

**Step 5: Run auth tests**

```
uv run pytest tests/test_webapp_auth.py -v
```
Expected: all PASS.

**Step 6: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 7: Commit**

```bash
git add bearmemori/webapp/auth.py bearmemori/mcp/server.py tests/test_webapp_auth.py
git commit -m "refactor: unify webapp and MCP auth into single middleware"
```

---

### Task 14: Restructure CLI — keep serve and health only

The CLI contains ~300 lines of client commands that are thin HTTP wrappers around the REST API. Remove them. Keep only `serve` and `health`.

**Files:**
- Modify: `bearmemori/cli.py`
- Modify: `tests/test_cli.py`

**Step 1: Read `cli.py` in full**

**Step 2: Read `tests/test_cli.py` in full**

**Step 3: Delete all client command functions**

Remove from `cli.py`:
- `cmd_get`
- `cmd_list`
- `cmd_search`
- `cmd_briefing`
- `cmd_events`
- `cmd_create`
- `cmd_update`
- `cmd_delete`
- `cmd_triage`
- `_parse_bool`
- `api_request`
- `output`

Keep:
- `cmd_health` — useful minimal check
- `cmd_serve` — starts the server
- `get_base_url` — still used by `cmd_health`

**Step 4: Simplify `build_parser`**

Remove all subparsers except `health` and `serve`. The result should be:

```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bearmemori",
        description="BearMemori server management",
    )
    parser.add_argument("--url", default=None, help="Server URL (default: http://localhost:8100)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Check server health")

    p_serve = subparsers.add_parser("serve", help="Start the BearMemori server")
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--host", default="0.0.0.0")
    p_serve.add_argument("--no-telegram", action="store_true")

    return parser
```

**Step 5: Simplify `main`**

```python
def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    base_url = get_base_url(args.url)

    if args.command == "health":
        sys.exit(cmd_health(base_url))
    elif args.command == "serve":
        sys.exit(cmd_serve(args.port, args.host, args.no_telegram))
```

**Step 6: Update `tests/test_cli.py`**

Remove tests for deleted commands. Keep tests for `health` and `serve`. Add a test that removed commands are gone:

```python
def test_only_serve_and_health_remain():
    parser = build_parser()
    # health works
    args = parser.parse_args(["health"])
    assert args.command == "health"
    # serve works
    args = parser.parse_args(["serve"])
    assert args.command == "serve"
    # old commands are gone
    with pytest.raises(SystemExit):
        parser.parse_args(["search", "query"])
```

**Step 7: Run CLI tests**

```
uv run pytest tests/test_cli.py -v
```
Expected: all PASS.

**Step 8: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS.

**Step 9: Commit**

```bash
git add bearmemori/cli.py tests/test_cli.py
git commit -m "refactor: trim CLI to serve and health only, remove HTTP wrapper commands"
```

---

### Task 15: Fix event bus silent failure

`events/bus.py` swallows handler exceptions — logs them and continues. For a personal memory store, a broken handler (e.g. `confirm_handler.handle_confirmed`) silently discards data. Fix it to raise after logging.

**Files:**
- Modify: `bearmemori/events/bus.py:26-29`
- Modify: `tests/test_event_bus.py`

**Step 1: Read `tests/test_event_bus.py` in full**

**Step 2: Update the test to expect exception propagation**

Add a test for the new behavior:

```python
@pytest.mark.asyncio
async def test_handler_exception_propagates():
    bus = EventBus()

    async def failing_handler(event):
        raise ValueError("handler failed")

    bus.on(SomeEvent, failing_handler)  # use any event type that exists

    with pytest.raises(ValueError, match="handler failed"):
        await bus.emit(SomeEvent(...))
```

**Step 3: Run the test — expect failure**

```
uv run pytest tests/test_event_bus.py::test_handler_exception_propagates -v
```
Expected: FAIL (exception is currently swallowed).

**Step 4: Update `bus.py` to re-raise**

Replace lines 25-29:
```python
if tasks:
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            logger.error("Event handler error: %s", result)
```

With:
```python
if tasks:
    results = await asyncio.gather(*tasks, return_exceptions=True)
    errors = [r for r in results if isinstance(r, Exception)]
    for err in errors:
        logger.error("Event handler error: %s", err)
    if errors:
        raise errors[0]
```

This logs all errors before raising the first one.

**Step 5: Run event bus tests**

```
uv run pytest tests/test_event_bus.py -v
```
Expected: all PASS.

**Step 6: Run full test suite**

```
uv run pytest -x -q
```
Expected: all PASS. If any test was relying on silent swallowing, update it to expect the exception or fix the handler in that test.

**Step 7: Commit**

```bash
git add bearmemori/events/bus.py tests/test_event_bus.py
git commit -m "fix: propagate event handler exceptions instead of swallowing them"
```

---

## Done

All three phases complete. Run the full test suite one final time:

```
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

All should pass clean.
