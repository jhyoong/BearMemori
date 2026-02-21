# Phase 2 Bugfix and Alignment Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all runtime-breaking bugs and important issues found during the Phase 2 review, so the Telegram bot and Core service work correctly end-to-end.

**Architecture:** No architectural changes. All fixes are targeted corrections to existing code — wrong variable references, mismatched schemas, missing endpoints, and a few code quality issues.

**Tech Stack:** Python 3.12+, FastAPI, aiosqlite, python-telegram-bot v20+, Pydantic v2, Redis Streams

---

## Group 1: Critical Runtime Bugs (will crash at runtime)

These three issues will cause immediate exceptions when users interact with the bot. Fix these first.

### Task 1: Fix `context.bot_data["user_id"]` KeyError in callback handlers

**Problem:** Three callback handlers read `context.bot_data["user_id"]` but this key is never set. This will raise a `KeyError` when a user taps Task, Remind, or enters a due date / reminder time.

**Files:**
- Modify: `telegram/tg_gateway/handlers/callback.py` (lines 198, 240, 314)

**Step 1: Write failing tests**

Add tests to `tests/test_telegram/test_callback.py` that verify the Task, Remind, and due date callbacks use `update.effective_user.id` instead of `context.bot_data["user_id"]`. The tests should call each handler with a mock update that has `effective_user.id = 12345` and verify the correct user ID is passed to the Core client.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram/test_callback.py -v -k "user_id"`
Expected: FAIL with KeyError or assertion error

**Step 3: Fix the code**

In `telegram/tg_gateway/handlers/callback.py`, replace all three occurrences:

Line 198 in `handle_memory_action` (`add_tag` branch):
```python
# Before
user_id = context.bot_data["user_id"]
# After — remove this line entirely, it is unused in the add_tag branch
```

Line 240 in `handle_due_date_choice`:
```python
# Before
user_id = context.bot_data["user_id"]
# After
user_id = update.effective_user.id
```

Line 314 in `handle_reminder_time_choice`:
```python
# Before
user_id = context.bot_data["user_id"]
# After
user_id = update.effective_user.id
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram/test_callback.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telegram/tg_gateway/handlers/callback.py tests/test_telegram/test_callback.py
git commit -m "fix: use update.effective_user.id instead of bot_data['user_id'] in callbacks"
```

---

### Task 2: Set conversation state in callback handlers for multi-step flows

**Problem:** When a user taps "Edit Tags", "Custom" date, or "Custom" reminder, the callback handler prompts the user for input but never sets the `user_data` key that `handle_text` checks to route the next message to the conversation handler. The user's response gets captured as a new memory instead.

**Files:**
- Modify: `telegram/tg_gateway/handlers/callback.py` (lines 196-201, 243-247, 317-322)

**Step 1: Write failing tests**

Add tests that verify after each callback handler runs, the corresponding `context.user_data` key is set:
- `add_tag` action sets `context.user_data["pending_tag_memory_id"]` to the memory ID
- `custom` due date sets `context.user_data["pending_task_memory_id"]` to the memory ID
- `custom` reminder sets `context.user_data["pending_reminder_memory_id"]` to the memory ID

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram/test_callback.py -v -k "pending"`
Expected: FAIL — user_data keys are not set

**Step 3: Fix the code**

Add the state key imports at the top of `callback.py`:
```python
from tg_gateway.handlers.conversation import (
    PENDING_TAG_MEMORY_ID,
    PENDING_TASK_MEMORY_ID,
    PENDING_REMINDER_MEMORY_ID,
)
```

In `handle_memory_action`, `add_tag` branch (around line 196):
```python
elif action == "add_tag":
    context.user_data[PENDING_TAG_MEMORY_ID] = memory_id
    await callback_query.edit_message_text(
        "Please send the tags for this memory as a comma-separated list "
        "(e.g., work, important, project)."
    )
```
Remove the unused `user_id = context.bot_data["user_id"]` line from this branch entirely.

In `handle_due_date_choice`, `custom` branch (around line 243):
```python
if choice == "custom":
    context.user_data[PENDING_TASK_MEMORY_ID] = memory_id
    await callback_query.edit_message_text(
        "Please enter a custom due date in YYYY-MM-DD format (e.g., 2024-12-31):"
    )
    return
```

In `handle_reminder_time_choice`, `custom` branch (around line 317):
```python
if choice == "custom":
    context.user_data[PENDING_REMINDER_MEMORY_ID] = memory_id
    await callback_query.edit_message_text(
        "Please enter a custom reminder time in YYYY-MM-DD HH:MM format "
        "(e.g., 2024-12-31 14:30):"
    )
    return
```

Also in `handle_tag_confirm`, `edit` branch (around line 563):
```python
elif action == "edit":
    context.user_data[PENDING_TAG_MEMORY_ID] = memory_id
    await callback_query.edit_message_text(
        "Please send the tags for this memory as a comma-separated list "
        "(e.g., work, important, project)."
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram/test_callback.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telegram/tg_gateway/handlers/callback.py tests/test_telegram/test_callback.py
git commit -m "fix: set user_data conversation state in callback handlers for multi-step flows"
```

---

### Task 3: Fix wrong import path in consumer.py

**Problem:** `consumer.py` imports `from shared.shared_lib.redis_streams import ...` but the installed package name is `shared_lib`, not `shared.shared_lib`. This will fail on import at runtime.

**Files:**
- Modify: `telegram/tg_gateway/consumer.py` (line 13)

**Step 1: Write a test**

Add a test to `tests/test_telegram/test_consumer.py` that imports the consumer module and verifies it loads without error.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_telegram/test_consumer.py -v -k "test_import"`
Expected: FAIL with ModuleNotFoundError

**Step 3: Fix the import**

In `telegram/tg_gateway/consumer.py` line 13, change:
```python
# Before
from shared.shared_lib.redis_streams import (
# After
from shared_lib.redis_streams import (
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_telegram/test_consumer.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telegram/tg_gateway/consumer.py tests/test_telegram/test_consumer.py
git commit -m "fix: correct import path from shared.shared_lib to shared_lib in consumer.py"
```

---

## Group 2: Important Bugs (will cause visible failures in specific flows)

These issues won't crash the whole bot but will cause specific features to fail.

### Task 4: Fix `/pinned` command sending empty query to search endpoint

**Problem:** `pinned_command` calls `core_client.search(query="", ...)` but the search endpoint returns HTTP 400 for empty queries. The `/pinned` command always fails.

**Files:**
- Modify: `core/core_svc/routers/search.py` (line 47 — allow empty query when `pinned=True`)

**Approach:** Modify the search endpoint to allow an empty query when `pinned=True`. When query is empty and pinned is true, skip the FTS5 search and query the memories table directly for pinned, confirmed memories.

**Step 1: Write failing test**

Add a test to `tests/test_core/test_search.py` that calls `GET /search?q=&owner=12345&pinned=true` and expects a 200 response with pinned memories.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core/test_search.py -v -k "pinned_empty"`
Expected: FAIL with 400 status

**Step 3: Fix the search endpoint**

In `core/core_svc/routers/search.py`, modify the validation to only reject empty queries when `pinned` is false:

```python
# Before
if not q or not q.strip():
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Search query cannot be empty or whitespace"
    )

# After
if (not q or not q.strip()) and not pinned:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Search query cannot be empty or whitespace"
    )
```

Then add a branch for the pinned-only case (before the existing FTS5 search logic):

```python
# If query is empty but pinned=True, fetch pinned memories directly
if not q or not q.strip():
    cursor = await db.execute(
        """
        SELECT * FROM memories
        WHERE owner_user_id = ? AND is_pinned = 1 AND status = 'confirmed'
        ORDER BY updated_at DESC
        LIMIT 20
        """,
        (owner,)
    )
    search_results = [dict(row) for row in await cursor.fetchall()]
    # Add a dummy rank for consistency
    for r in search_results:
        r["rank"] = 0.0
else:
    search_results = await search_memories(...)
```

The rest of the function (tag fetching, response building) stays the same.

**Step 4: Run tests**

Run: `pytest tests/test_core/test_search.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add core/core_svc/routers/search.py tests/test_core/test_search.py
git commit -m "fix: allow empty query in search endpoint when pinned=true"
```

---

### Task 5: Fix `list_tasks` sending wrong parameter name

**Problem:** `core_client.list_tasks()` sends `{"owner": owner_user_id}` but the Core API expects `owner_user_id` as the query parameter name. Owner filtering is silently ignored.

**Files:**
- Modify: `telegram/tg_gateway/core_client.py` (line 216)

**Step 1: Write failing test**

Add a test that verifies the correct parameter name is sent.

**Step 2: Fix the code**

In `telegram/tg_gateway/core_client.py` line 216, change:
```python
# Before
params: dict = {"owner": owner_user_id}
# After
params: dict = {"owner_user_id": owner_user_id}
```

**Step 3: Run tests**

Run: `pytest tests/test_telegram/ -v -k "list_tasks"`
Expected: PASS

**Step 4: Commit**

```bash
git add telegram/tg_gateway/core_client.py
git commit -m "fix: use correct parameter name owner_user_id in list_tasks"
```

---

### Task 6: Fix `search()` in CoreClient returning wrong schema

**Problem:** `CoreClient.search()` returns `list[SearchResult]` but the Core API returns `list[MemorySearchResult]`. `SearchResult` has `entity_type`, `entity_id`, `content` fields; `MemorySearchResult` has a nested `memory` object and a `score`. The `/find` command accesses `result.content` and `result.entity_id` which don't exist on the actual response.

**Files:**
- Modify: `telegram/tg_gateway/core_client.py` (lines 287-309 — change return type and deserialization)
- Modify: `telegram/tg_gateway/handlers/command.py` (lines 106-113 — update field access)

**Step 1: Write failing test**

Add a test that creates a memory, searches for it through the Core API, and verifies the response matches `MemorySearchResult` schema.

**Step 2: Fix CoreClient.search()**

In `telegram/tg_gateway/core_client.py`:

Update import at top of file:
```python
# Add MemorySearchResult to the import list from shared_lib.schemas
from shared_lib.schemas import (
    ...
    MemorySearchResult,
    ...
)
```

Change the `search()` method signature and return:
```python
async def search(
    self, query: str, owner: int, pinned: bool = False
) -> list[MemorySearchResult]:
    """Search memories."""
    ...
    return [MemorySearchResult.model_validate(item) for item in response.json()]
```

**Step 3: Fix find_command and pinned_command**

In `telegram/tg_gateway/handlers/command.py`, update the `find_command` to access fields through the nested `memory` object:

```python
# Before (lines 108-113)
for result in results[:5]:
    content = result.content
    label = content[:50] + "..." if len(content) > 50 else content
    keyboard_results.append((label, result.entity_id))

# After
for result in results[:5]:
    content = result.memory.content or "Memory"
    label = content[:50] + "..." if len(content) > 50 else content
    keyboard_results.append((label, result.memory.id))
```

Similarly update `pinned_command`:
```python
# Before (lines 219-223)
for result in results[:10]:
    content = result.content
    label = content[:50] + "..." if len(content) > 50 else content
    keyboard_results.append((label, result.entity_id))

# After
for result in results[:10]:
    content = result.memory.content or "Memory"
    label = content[:50] + "..." if len(content) > 50 else content
    keyboard_results.append((label, result.memory.id))
```

**Step 4: Run tests**

Run: `pytest tests/test_telegram/ -v -k "search or find or pinned"`
Expected: PASS

**Step 5: Commit**

```bash
git add telegram/tg_gateway/core_client.py telegram/tg_gateway/handlers/command.py
git commit -m "fix: align CoreClient.search() return type with Core API MemorySearchResult schema"
```

---

### Task 7: Fix `handle_tag_confirm` passing wrong type to `add_tags`

**Problem:** `handle_tag_confirm` passes `TagAdd(memory_id=..., tag_name=...)` to `core_client.add_tags()`, but `add_tags()` expects `TagsAddRequest(tags=[...], status="confirmed")`. Different fields — will cause a validation error.

**Files:**
- Modify: `telegram/tg_gateway/handlers/callback.py` (lines 539-553)

**Step 1: Write failing test**

Add a test that mocks a memory with suggested tags and calls `handle_tag_confirm` with `action="confirm_all"`. Verify that `core_client.add_tags` is called with a `TagsAddRequest` containing all suggested tags in one batch call.

**Step 2: Fix the code**

In `handle_tag_confirm`, replace the per-tag loop with a single batch call:

```python
if action == "confirm_all":
    memory = await core_client.get_memory(memory_id)
    if memory is None:
        await callback_query.edit_message_text("Memory not found.")
        return

    suggested_tags = [t.tag for t in memory.tags if t.status == "suggested"]

    if suggested_tags:
        tags_request = TagsAddRequest(tags=suggested_tags, status="confirmed")
        await core_client.add_tags(memory_id, tags_request)

    await core_client.update_memory(
        memory_id, MemoryUpdate(status=MemoryStatus.confirmed)
    )

    tags_str = ", ".join(suggested_tags) if suggested_tags else "all tags"
    await callback_query.edit_message_text(f"Tags confirmed: {tags_str}")
```

Also remove the unused `TagAdd` import from the top of `callback.py` if it is no longer used elsewhere.

**Step 3: Run tests**

Run: `pytest tests/test_telegram/test_callback.py -v -k "tag_confirm"`
Expected: PASS

**Step 4: Commit**

```bash
git add telegram/tg_gateway/handlers/callback.py
git commit -m "fix: use TagsAddRequest instead of TagAdd in handle_tag_confirm"
```

---

### Task 8: Add image upload endpoint to Core API

**Problem:** `CoreClient.upload_image()` calls `POST /memories/{id}/image` but this endpoint does not exist in the Core routers. Image uploads from the Telegram gateway will fail with 404.

**Files:**
- Modify: `core/core_svc/routers/memories.py` — add `POST /{id}/image` endpoint
- Test: `tests/test_core/test_memories.py` — add upload test

**Step 1: Write failing test**

Add a test that creates a memory and then uploads image bytes to `POST /memories/{id}/image`. Expect a 200 response with a `local_path` field.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core/test_memories.py -v -k "upload_image"`
Expected: FAIL with 404 or 405

**Step 3: Implement the endpoint**

Add to `core/core_svc/routers/memories.py`:

```python
from fastapi import UploadFile, File

@router.post("/{id}/image")
async def upload_memory_image(
    id: str,
    file: UploadFile = File(...),
    db: aiosqlite.Connection = Depends(get_db),
) -> dict:
    """Upload an image file for a memory and store it locally."""
    # Fetch memory; 404 if not found
    cursor = await db.execute("SELECT * FROM memories WHERE id = ?", (id,))
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Memory not found")

    # Read image bytes
    image_bytes = await file.read()

    # Determine storage path from config
    image_storage_path = os.environ.get("IMAGE_STORAGE_PATH", "/data/images")
    os.makedirs(image_storage_path, exist_ok=True)

    # Save to disk
    local_path = os.path.join(image_storage_path, f"{id}.jpg")
    with open(local_path, "wb") as f:
        f.write(image_bytes)

    # Update memory with local path
    await db.execute(
        "UPDATE memories SET media_local_path = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
        (local_path, id),
    )
    await db.commit()

    # Audit log
    await log_audit(
        db, "memory", id, "updated",
        f"user:{row['owner_user_id']}",
        detail={"media_local_path": local_path},
    )

    return {"local_path": local_path}
```

**Step 4: Run tests**

Run: `pytest tests/test_core/test_memories.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add core/core_svc/routers/memories.py tests/test_core/test_memories.py
git commit -m "feat: add POST /memories/{id}/image endpoint for image uploads"
```

---

### Task 9: Fix scheduler not copying `text` field for recurring reminders

**Problem:** When the scheduler creates the next instance of a recurring reminder, the INSERT statement omits the `text` column. The new reminder will have NULL for text.

**Files:**
- Modify: `core/core_svc/scheduler.py` (lines 71-77)

**Step 1: Write failing test**

Add a test to `tests/test_core/test_scheduler.py` that creates a recurring reminder with `text="Buy groceries"`, fires it, and verifies the newly created recurring instance also has `text="Buy groceries"`.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core/test_scheduler.py -v -k "recurring_text"`
Expected: FAIL — new reminder has NULL text

**Step 3: Fix the INSERT statement**

In `core/core_svc/scheduler.py`, update the recurring reminder INSERT (around line 71):

First, read the `text` field from the original reminder earlier in the loop (add after line 37):
```python
reminder_text = reminder.get('text', '')
```

Then update the INSERT:
```python
# Before
await db.execute(
    """
    INSERT INTO reminders (id, memory_id, owner_user_id, fire_at, recurrence_minutes, fired)
    VALUES (?, ?, ?, ?, ?, 0)
    """,
    (new_reminder_id, memory_id, owner_user_id, next_fire_at_str, recurrence_minutes)
)

# After
await db.execute(
    """
    INSERT INTO reminders (id, memory_id, owner_user_id, text, fire_at, recurrence_minutes, fired)
    VALUES (?, ?, ?, ?, ?, ?, 0)
    """,
    (new_reminder_id, memory_id, owner_user_id, reminder_text, next_fire_at_str, recurrence_minutes)
)
```

**Step 4: Run tests**

Run: `pytest tests/test_core/test_scheduler.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add core/core_svc/scheduler.py tests/test_core/test_scheduler.py
git commit -m "fix: copy text field when creating recurring reminder instances"
```

---

## Group 3: Code Quality (non-breaking, but should clean up)

### Task 10: Replace `datetime.utcnow()` with `datetime.now(timezone.utc)`

**Problem:** Several files use the deprecated `datetime.utcnow()` (Python 3.12+). The test suite shows 370 deprecation warnings. Some files already use the correct form.

**Files:**
- Modify: `core/core_svc/routers/memories.py` (lines 48, 213, 339, 343)
- Modify: `core/core_svc/routers/tasks.py` (lines where `datetime.utcnow()` is used)
- Modify: `core/core_svc/routers/reminders.py` (lines where `datetime.utcnow()` is used)

**Step 1: Find all occurrences**

Run: `grep -rn "datetime.utcnow" core/`

**Step 2: Replace all occurrences**

In each file, ensure `from datetime import datetime, timezone` is imported (add `timezone` if missing), then replace:
```python
# Before
datetime.utcnow()
# After
datetime.now(timezone.utc)
```

**Step 3: Run tests**

Run: `pytest tests/test_core/ -v`
Expected: PASS with fewer deprecation warnings

**Step 4: Commit**

```bash
git add core/
git commit -m "fix: replace deprecated datetime.utcnow() with datetime.now(timezone.utc)"
```

---

### Task 11: Extract `parse_db_datetime()` to shared utility

**Problem:** The `parse_db_datetime()` helper is copy-pasted identically into 8 router files.

**Files:**
- Create: `core/core_svc/utils.py` — new file with the shared function
- Modify: All router files that define `parse_db_datetime()` — remove local copies, import from `core_svc.utils`

**Step 1: Create the utility module**

Create `core/core_svc/utils.py` with:
```python
"""Shared utility functions for the Core service."""

from datetime import datetime


def parse_db_datetime(dt_str: str | None) -> datetime | None:
    """Parse datetime string from database, handling 'Z' and '+00:00' formats."""
    if not dt_str:
        return None
    if "+" in dt_str and dt_str.endswith("Z"):
        dt_str = dt_str[:-1]
    elif dt_str.endswith("Z"):
        dt_str = dt_str.replace("Z", "+00:00")
    return datetime.fromisoformat(dt_str)
```

**Step 2: Update all router files**

In each file that defines `parse_db_datetime()` locally, remove the function definition and add:
```python
from core_svc.utils import parse_db_datetime
```

Files to update:
- `core/core_svc/routers/tasks.py`
- `core/core_svc/routers/reminders.py`
- `core/core_svc/routers/events.py`
- `core/core_svc/routers/search.py`
- `core/core_svc/routers/settings.py`
- `core/core_svc/routers/audit.py`
- `core/core_svc/routers/backup.py`
- `core/core_svc/routers/llm_jobs.py`

**Step 3: Run tests**

Run: `pytest tests/test_core/ -v`
Expected: PASS — no behavior change

**Step 4: Commit**

```bash
git add core/core_svc/utils.py core/core_svc/routers/
git commit -m "refactor: extract parse_db_datetime to shared utility module"
```

---

### Task 12: Fix FTS5 full rebuild performance

**Problem:** Every call to `index_memory()` or `remove_from_index()` does a full `delete-all` + re-insert of the entire FTS5 index. This works for small datasets but degrades as data grows.

**Files:**
- Modify: `core/core_svc/search.py`

**Step 1: Write a test**

Add a test that creates 5 memories, indexes each one, and verifies FTS5 search still returns correct results. This ensures the targeted approach works.

**Step 2: Implement targeted FTS5 updates**

Replace the full rebuild with targeted row operations:

```python
async def index_memory(db: aiosqlite.Connection, memory_id: str) -> None:
    """Upsert the FTS5 entry for a single memory."""
    # Get the memory's rowid
    cursor = await db.execute(
        "SELECT rowid, content, status FROM memories WHERE id = ?",
        (memory_id,)
    )
    row = await cursor.fetchone()
    if row is None or row["status"] != "confirmed":
        # Not confirmed — remove if present
        await remove_from_index(db, memory_id)
        return

    memory_rowid = row["rowid"]
    content = row["content"]

    # Get confirmed tags
    tag_cursor = await db.execute(
        "SELECT tag FROM memory_tags WHERE memory_id = ? AND status = 'confirmed'",
        (memory_id,)
    )
    tags = " ".join(t[0] for t in await tag_cursor.fetchall())

    # Remove old entry if it exists (external content table requires manual delete)
    await db.execute(
        "INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES('delete', ?, ?, ?)",
        (memory_rowid, content, tags)
    )

    # Insert new entry
    await db.execute(
        "INSERT INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)",
        (memory_rowid, content, tags)
    )
    await db.commit()


async def remove_from_index(db: aiosqlite.Connection, memory_id: str) -> None:
    """Remove the FTS5 entry for a single memory."""
    cursor = await db.execute(
        "SELECT rowid, content FROM memories WHERE id = ?",
        (memory_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        return

    memory_rowid = row["rowid"]
    content = row["content"]

    # Get current tags for the delete command
    tag_cursor = await db.execute(
        "SELECT tag FROM memory_tags WHERE memory_id = ? AND status = 'confirmed'",
        (memory_id,)
    )
    tags = " ".join(t[0] for t in await tag_cursor.fetchall())

    await db.execute(
        "INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES('delete', ?, ?, ?)",
        (memory_rowid, content, tags)
    )
    await db.commit()
```

Note: For external content FTS5 tables, the `delete` command requires passing the original content that was indexed. This approach needs careful testing — if the content has changed between index and delete, the delete may not work correctly. Keep `_rebuild_fts_index()` as a fallback and add a `POST /admin/rebuild-fts` endpoint for manual rebuilds if needed.

**Step 3: Run tests**

Run: `pytest tests/test_core/test_search.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add core/core_svc/search.py tests/test_core/test_search.py
git commit -m "perf: use targeted FTS5 updates instead of full rebuild on every change"
```

---

### Task 13: Move `import uuid` to top-level in scheduler.py

**Problem:** `import uuid` is inside the `_fire_due_reminders` function body instead of at module top level.

**Files:**
- Modify: `core/core_svc/scheduler.py`

**Step 1: Fix**

Move `import uuid` from line 67 to the top-level imports (after `import os`). Remove the inline import.

**Step 2: Run tests**

Run: `pytest tests/test_core/test_scheduler.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add core/core_svc/scheduler.py
git commit -m "refactor: move uuid import to module top level in scheduler.py"
```

---

## Execution Order Summary

| Priority | Tasks | What it fixes |
|----------|-------|---------------|
| **First** | Tasks 1-3 | Critical runtime crashes — bot won't work without these |
| **Second** | Tasks 4-9 | Important bugs — specific features will fail |
| **Third** | Tasks 10-13 | Code quality — deprecation warnings, duplication, performance |

After all tasks are done, run the full test suite:
```bash
pytest -v
```
All 155+ tests should pass with no new failures.
