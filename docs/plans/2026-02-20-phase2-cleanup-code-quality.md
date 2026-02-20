# Phase 2 Cleanup and Code Quality Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Resolve the 4 remaining code quality items and 1 minor cleanup from the Phase 2 bugfix plan, leaving the codebase clean for Phase 3.

**Architecture:** No behavioral changes. All tasks are refactors, deprecation fixes, or dead code removal.

**Tech Stack:** Python 3.12+, FastAPI, aiosqlite, FTS5

---

## Task 1: Extract `parse_db_datetime()` to shared utility module

**Why first:** Tasks 2 and 3 both touch the same router files. Extracting this function first avoids merge conflicts and means those later tasks modify files that already have the correct imports.

**Files:**
- Create: `core/core_svc/utils.py`
- Modify: `core/core_svc/routers/tasks.py` — remove local definition, add import
- Modify: `core/core_svc/routers/reminders.py` — remove local definition, add import
- Modify: `core/core_svc/routers/events.py` — remove local definition, add import
- Modify: `core/core_svc/routers/search.py` — remove local definition, add import
- Modify: `core/core_svc/routers/settings.py` — remove local definition, add import
- Modify: `core/core_svc/routers/audit.py` — remove local definition, add import
- Modify: `core/core_svc/routers/backup.py` — remove local definition, add import
- Modify: `core/core_svc/routers/llm_jobs.py` — remove local definition, add import
- Test: `tests/test_core/test_utils.py`

**Step 1: Write the test**

Create `tests/test_core/test_utils.py`:

```python
"""Tests for core_svc.utils."""

from datetime import datetime, timezone
from core_svc.utils import parse_db_datetime


class TestParseDbDatetime:
    def test_none_returns_none(self):
        assert parse_db_datetime(None) is None

    def test_empty_string_returns_none(self):
        assert parse_db_datetime("") is None

    def test_z_suffix(self):
        result = parse_db_datetime("2026-01-15T10:30:00Z")
        assert result == datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_plus_offset(self):
        result = parse_db_datetime("2026-01-15T10:30:00+00:00")
        assert result == datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_plus_offset_with_trailing_z(self):
        result = parse_db_datetime("2026-01-15T10:30:00+00:00Z")
        assert result == datetime(2026, 1, 15, 10, 30, 0, tzinfo=timezone.utc)

    def test_milliseconds(self):
        result = parse_db_datetime("2026-01-15T10:30:00.123Z")
        assert result.microsecond == 123000
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_core/test_utils.py -v`
Expected: FAIL — `core_svc.utils` does not exist

**Step 3: Create the utility module**

Create `core/core_svc/utils.py`:

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

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_core/test_utils.py -v`
Expected: PASS

**Step 5: Replace all 8 local definitions with imports**

In each of these files, remove the `def parse_db_datetime(...)` function (and its docstring/body) and add this import to the first-party import group:

```python
from core_svc.utils import parse_db_datetime
```

Files (with approximate line ranges of the function to remove):
- `core/core_svc/routers/tasks.py` — lines 24-34
- `core/core_svc/routers/reminders.py` — lines 19-29
- `core/core_svc/routers/events.py` — lines 19-29
- `core/core_svc/routers/search.py` — lines 18-28
- `core/core_svc/routers/settings.py` — lines 18-28
- `core/core_svc/routers/audit.py` — lines 19-29
- `core/core_svc/routers/backup.py` — lines 17-27
- `core/core_svc/routers/llm_jobs.py` — lines 20-30

**Step 6: Run full core test suite**

Run: `pytest tests/test_core/ -v`
Expected: All pass — no behavior change

**Step 7: Commit**

```bash
git add core/core_svc/utils.py tests/test_core/test_utils.py core/core_svc/routers/
git commit -m "refactor: extract parse_db_datetime to core_svc.utils, remove 8 duplicates"
```

---

## Task 2: Replace deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)`

**Files:**
- Modify: `core/core_svc/routers/memories.py` — 5 occurrences (lines 51, 232, 362, 366, 493)
- Modify: `core/core_svc/routers/tasks.py` — 3 occurrences (lines 250, 257, 276)
- Modify: `core/core_svc/routers/reminders.py` — 2 occurrences (lines 130, 215)

**Step 1: Fix `memories.py`**

Add `timezone` to the datetime import if not already present:

```python
from datetime import datetime, timedelta, timezone
```

Then replace all 5 occurrences. The pattern is the same for each:

```python
# Before
datetime.utcnow()
# After
datetime.now(timezone.utc)
```

The 5 specific lines:
- Line 51: `pending_expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat() + "Z"`
- Line 232: `updated_at = datetime.now(timezone.utc).isoformat() + "Z"`
- Line 362: `suggested_at = datetime.now(timezone.utc).isoformat() + "Z"`
- Line 366: `confirmed_at = datetime.now(timezone.utc).isoformat() + "Z"`
- Line 493: `updated_at = datetime.now(timezone.utc).isoformat() + "Z"`

**Step 2: Fix `tasks.py`**

Add `timezone` to the datetime import:

```python
from datetime import datetime, timedelta, timezone
```

Replace all 3 occurrences:
- Line 250: `completed_at = datetime.now(timezone.utc).isoformat() + 'Z'`
- Line 257: `updated_at = datetime.now(timezone.utc).isoformat() + 'Z'`
- Line 276: `new_due_at = datetime.now(timezone.utc) + timedelta(minutes=row["recurrence_minutes"])`

**Step 3: Fix `reminders.py`**

Add `timezone` to the datetime import:

```python
from datetime import datetime, timezone
```

Replace both occurrences:
- Line 130: `now_str = datetime.now(timezone.utc).isoformat() + 'Z'`
- Line 215: `updated_at = datetime.now(timezone.utc).isoformat() + 'Z'`

**Step 4: Verify no occurrences remain**

Run: `grep -rn "datetime.utcnow" core/`
Expected: No output

**Step 5: Run tests**

Run: `pytest tests/test_core/ -v`
Expected: All pass, deprecation warnings gone

**Step 6: Commit**

```bash
git add core/core_svc/routers/memories.py core/core_svc/routers/tasks.py core/core_svc/routers/reminders.py
git commit -m "fix: replace deprecated datetime.utcnow() with datetime.now(timezone.utc)"
```

---

## Task 3: Improve FTS5 indexing with targeted row updates

**Why:** Every call to `index_memory()` or `remove_from_index()` currently rebuilds the entire FTS5 index. This is O(n) per write where n = total confirmed memories. Replace with targeted single-row operations.

**Files:**
- Modify: `core/core_svc/search.py`
- Test: `tests/test_core/test_search.py`

**Step 1: Write a targeted test**

Add a test to `tests/test_core/test_search.py` that:
1. Creates 3 confirmed memories
2. Indexes all 3
3. Searches and verifies all 3 appear
4. Removes one from the index
5. Searches again and verifies only 2 appear

This validates that targeted insert/delete works without a full rebuild.

**Step 2: Run test to verify it passes with current implementation**

Run: `pytest tests/test_core/test_search.py -v -k "targeted"`
Expected: PASS (the full rebuild still produces correct results)

**Step 3: Rewrite `index_memory()` and `remove_from_index()`**

Replace the contents of `core/core_svc/search.py` with:

```python
"""FTS5 full-text search module for memories."""

import aiosqlite


async def _get_memory_fts_data(
    db: aiosqlite.Connection, memory_id: str
) -> tuple[int, str, str] | None:
    """Fetch the rowid, content, and confirmed tags for a memory.

    Returns None if the memory does not exist.
    """
    cursor = await db.execute(
        "SELECT rowid, content FROM memories WHERE id = ?",
        (memory_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        return None

    memory_rowid = row[0]
    content = row[1] or ""

    tag_cursor = await db.execute(
        "SELECT tag FROM memory_tags WHERE memory_id = ? AND status = 'confirmed'",
        (memory_id,)
    )
    tag_rows = await tag_cursor.fetchall()
    tags = " ".join(t[0] for t in tag_rows)

    return memory_rowid, content, tags


async def _delete_fts_row(
    db: aiosqlite.Connection, rowid: int, content: str, tags: str
) -> None:
    """Delete a single row from the FTS5 index by rowid and original content."""
    await db.execute(
        "INSERT INTO memories_fts(memories_fts, rowid, content, tags) "
        "VALUES('delete', ?, ?, ?)",
        (rowid, content, tags),
    )


async def rebuild_fts_index(db: aiosqlite.Connection) -> None:
    """Full rebuild of the FTS5 index. Use as a maintenance fallback only."""
    await db.execute("INSERT INTO memories_fts(memories_fts) VALUES('delete-all')")

    cursor = await db.execute(
        "SELECT rowid, id, content FROM memories WHERE status = 'confirmed'"
    )
    memories = await cursor.fetchall()

    for memory_rowid, memory_id, content in memories:
        tag_cursor = await db.execute(
            "SELECT tag FROM memory_tags "
            "WHERE memory_id = ? AND status = 'confirmed'",
            (memory_id,),
        )
        tag_rows = await tag_cursor.fetchall()
        tags = " ".join(tag[0] for tag in tag_rows)

        await db.execute(
            "INSERT INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)",
            (memory_rowid, content or "", tags),
        )

    await db.commit()


async def index_memory(db: aiosqlite.Connection, memory_id: str) -> None:
    """Index or re-index a single memory in FTS5.

    Only indexes confirmed memories. If the memory is not confirmed,
    any existing FTS5 entry is removed.
    """
    # Check memory status
    status_cursor = await db.execute(
        "SELECT status FROM memories WHERE id = ?", (memory_id,)
    )
    status_row = await status_cursor.fetchone()
    if status_row is None:
        return

    if status_row[0] != "confirmed":
        await remove_from_index(db, memory_id)
        return

    data = await _get_memory_fts_data(db, memory_id)
    if data is None:
        return

    memory_rowid, content, tags = data

    # Remove old entry first (safe even if it does not exist in FTS5 —
    # the delete command is a no-op for non-existent rows in practice,
    # but we wrap in try/except to be safe)
    try:
        await _delete_fts_row(db, memory_rowid, content, tags)
    except Exception:
        pass

    # Insert fresh entry
    await db.execute(
        "INSERT INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)",
        (memory_rowid, content, tags),
    )
    await db.commit()


async def remove_from_index(db: aiosqlite.Connection, memory_id: str) -> None:
    """Remove a single memory from the FTS5 index."""
    data = await _get_memory_fts_data(db, memory_id)
    if data is None:
        return

    memory_rowid, content, tags = data

    try:
        await _delete_fts_row(db, memory_rowid, content, tags)
        await db.commit()
    except Exception:
        pass


async def search_memories(
    db: aiosqlite.Connection,
    query: str,
    owner_user_id: int,
    pinned_only: bool = False,
    limit: int = 20,
    offset: int = 0,
) -> list[dict]:
    """Query FTS5 and return results with pin boost."""
    terms = query.split()
    sanitized_query = " ".join(f'"{term}"' for term in terms if term)

    if not sanitized_query:
        return []

    sql = """
        SELECT m.*, memories_fts.rank
        FROM memories_fts
        JOIN memories m ON m.rowid = memories_fts.rowid
        WHERE memories_fts MATCH ?
        AND m.owner_user_id = ?
        AND m.status = 'confirmed'
    """

    params: list = [sanitized_query, owner_user_id]

    if pinned_only:
        sql += " AND m.is_pinned = 1"

    sql += " ORDER BY m.is_pinned DESC, rank"
    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(sql, params)
    rows = await cursor.fetchall()

    column_names = [description[0] for description in cursor.description]

    results = []
    for row in rows:
        memory_dict = dict(zip(column_names, row))

        tag_cursor = await db.execute(
            "SELECT tag FROM memory_tags "
            "WHERE memory_id = ? AND status = 'confirmed'",
            (memory_dict["id"],),
        )
        tag_rows = await tag_cursor.fetchall()
        memory_dict["tags"] = [tag[0] for tag in tag_rows]

        results.append(memory_dict)

    return results
```

Key changes:
- `index_memory()` now deletes only the target row then re-inserts it — O(1) instead of O(n)
- `remove_from_index()` now deletes only the target row — O(1) instead of O(n)
- `rebuild_fts_index()` is kept as a public function for maintenance/admin use but is no longer called on every write

**Step 4: Run all search tests**

Run: `pytest tests/test_core/test_search.py -v`
Expected: All pass

**Step 5: Run full test suite to check for regressions**

Run: `pytest tests/test_core/ -v`
Expected: All pass

**Step 6: Commit**

```bash
git add core/core_svc/search.py tests/test_core/test_search.py
git commit -m "perf: use targeted FTS5 row updates instead of full rebuild per write"
```

---

## Task 4: Move inline `import uuid` to top-level in scheduler.py

**Files:**
- Modify: `core/core_svc/scheduler.py` (move line 65 to top-level imports)

**Step 1: Fix the import**

At the top of `core/core_svc/scheduler.py`, add `uuid` to the imports (after `import os`):

```python
import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta
```

Then remove the `import uuid` on line 65 (inside `_fire_due_reminders`).

**Step 2: Run tests**

Run: `pytest tests/test_core/ -v`
Expected: All pass

**Step 3: Commit**

```bash
git add core/core_svc/scheduler.py
git commit -m "refactor: move uuid import to module top level in scheduler.py"
```

---

## Task 5: Fix duplicate PENDING_* constants in command.py

**Problem:** `command.py` re-defines the 3 `PENDING_*` constants locally (lines 16-18) with a comment "same as in conversation.py" instead of importing them from the canonical source.

**Files:**
- Modify: `telegram/tg_gateway/handlers/command.py` (lines 15-18)

**Step 1: Fix the import**

Replace the local constant definitions:

```python
# Before (lines 15-18)
# Conversation pending state keys (same as in conversation.py)
PENDING_TAG_MEMORY_ID = "pending_tag_memory_id"
PENDING_TASK_MEMORY_ID = "pending_task_memory_id"
PENDING_REMINDER_MEMORY_ID = "pending_reminder_memory_id"

# After
from tg_gateway.handlers.conversation import (
    PENDING_TAG_MEMORY_ID,
    PENDING_TASK_MEMORY_ID,
    PENDING_REMINDER_MEMORY_ID,
)
```

**Step 2: Run tests**

Run: `pytest tests/test_telegram/ -v`
Expected: All pass

**Step 3: Commit**

```bash
git add telegram/tg_gateway/handlers/command.py
git commit -m "refactor: import PENDING_* constants from conversation.py instead of duplicating"
```

---

## Execution Order Summary

| Task | What it does |
|------|-------------|
| 1 | Extract `parse_db_datetime()` to `core_svc.utils` (do first — avoids conflicts with Tasks 2-3) |
| 2 | Replace `datetime.utcnow()` (eliminates 385 deprecation warnings) |
| 3 | Targeted FTS5 updates (O(1) per write instead of O(n)) |
| 4 | Move `import uuid` to top-level |
| 5 | Import `PENDING_*` constants instead of duplicating |

After all tasks, run the full suite:

```bash
pytest -v
```

Expected: 159+ tests pass, 0 deprecation warnings from `datetime.utcnow()`.
