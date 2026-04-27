# Audit Log Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a simple audit log that records every memory create/update/delete/archive with actor attribution (telegram, webapp, api, reflection), exposed via REST endpoint and webapp page.

**Architecture:** Storage-layer hook. `MemoryDatabase.create/update/delete/delete_many` take a required `actor` parameter and write an audit row in the same SQLite transaction. New `audit_log` table in the existing memory database. New `/audit` REST endpoint and `/webapp/audit` page surface the log.

**Tech Stack:** Python 3.12, SQLite (with WAL), FastAPI, Jinja2 + HTMX, pydantic, pytest + pytest-asyncio.

**Design doc:** `docs/plans/2026-04-26-audit-log-design.md`

---

## Conventions for every task

- Run tests inside the project venv: `uv run pytest <path> -v`
- Lint/format after each task: `uv run ruff check . && uv run ruff format .`
- One commit per task using `type: description` (feat/refactor/test/etc.)
- TDD: write failing test → run it → implement minimal code → run again → commit

---

### Task 1: Add Actor enum and AuditEntry model

**Files:**
- Modify: `bearmemori/storage/models.py`
- Create: `tests/test_audit_models.py`

**Step 1: Write the failing test**

Create `tests/test_audit_models.py`:

```python
from datetime import UTC, datetime

from bearmemori.storage.models import Actor, AuditEntry


def test_actor_values():
    assert Actor.TELEGRAM.value == "telegram"
    assert Actor.WEBAPP.value == "webapp"
    assert Actor.API.value == "api"
    assert Actor.REFLECTION.value == "reflection"


def test_audit_entry_roundtrip():
    entry = AuditEntry(
        id=1,
        memory_id="mem_abc",
        action="create",
        actor=Actor.API,
        timestamp=datetime(2026, 4, 26, tzinfo=UTC),
        title_snapshot="hello",
        category_snapshot="general",
    )
    dumped = entry.model_dump(mode="json")
    assert dumped["actor"] == "api"
    assert dumped["action"] == "create"
    assert dumped["title_snapshot"] == "hello"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_models.py -v`
Expected: ImportError (Actor / AuditEntry not defined).

**Step 3: Implement**

In `bearmemori/storage/models.py` add (next to `MemoryCategory`):

```python
class Actor(str, Enum):
    TELEGRAM = "telegram"
    WEBAPP = "webapp"
    API = "api"
    REFLECTION = "reflection"


class AuditAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    ARCHIVE = "archive"


class AuditEntry(BaseModel):
    id: int
    memory_id: str
    action: str  # AuditAction value
    actor: Actor
    timestamp: datetime
    title_snapshot: str | None = None
    category_snapshot: str | None = None
```

**Step 4: Run test**

Run: `uv run pytest tests/test_audit_models.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add bearmemori/storage/models.py tests/test_audit_models.py
git commit -m "feat: add Actor, AuditAction, and AuditEntry models"
```

---

### Task 2: Create audit_log table and migration

**Files:**
- Modify: `bearmemori/storage/database.py` (`initialize`, `_migrate`)
- Create: `tests/test_audit_log_schema.py`

**Step 1: Write the failing test**

Create `tests/test_audit_log_schema.py`:

```python
import sqlite3

from bearmemori.storage.database import MemoryDatabase


def test_audit_log_table_created(tmp_path):
    db = MemoryDatabase(str(tmp_path / "test.db"))
    db.initialize()
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    cols = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
    assert cols == {
        "id",
        "memory_id",
        "action",
        "actor",
        "timestamp",
        "title_snapshot",
        "category_snapshot",
    }
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(audit_log)")}
    assert "idx_audit_log_timestamp" in indexes
    assert "idx_audit_log_memory_id" in indexes
    assert "idx_audit_log_actor" in indexes


def test_audit_log_migration_on_existing_db(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        """CREATE TABLE memories (
            id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            raw_input TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            source TEXT,
            event_datetime TEXT,
            event_status TEXT,
            event_recurrence TEXT,
            metadata TEXT NOT NULL DEFAULT '{}'
        )"""
    )
    legacy.commit()
    legacy.close()

    db = MemoryDatabase(db_path)
    db.initialize()

    conn = sqlite3.connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)")}
    assert "memory_id" in cols
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_log_schema.py -v`
Expected: FAIL — `audit_log` table missing.

**Step 3: Implement**

In `bearmemori/storage/database.py` `initialize()`, after the existing memory table/index/trigger setup and before the final `self._conn.commit()`, add the audit table creation. Place this block right before the final `commit()`:

```python
self._conn.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_id TEXT NOT NULL,
        action TEXT NOT NULL,
        actor TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        title_snapshot TEXT,
        category_snapshot TEXT
    )
""")
self._conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp
    ON audit_log (timestamp DESC)
""")
self._conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_audit_log_memory_id
    ON audit_log (memory_id)
""")
self._conn.execute("""
    CREATE INDEX IF NOT EXISTS idx_audit_log_actor
    ON audit_log (actor)
""")
```

`CREATE TABLE IF NOT EXISTS` handles both fresh and legacy DBs; no separate `_migrate()` change is needed.

**Step 4: Run test**

Run: `uv run pytest tests/test_audit_log_schema.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add bearmemori/storage/database.py tests/test_audit_log_schema.py
git commit -m "feat: add audit_log table to memory database"
```

---

### Task 3: Add internal `_write_audit` helper and `list_audit` method

**Files:**
- Modify: `bearmemori/storage/database.py`
- Create: `tests/test_audit_log_list.py`

**Step 1: Write the failing test**

Create `tests/test_audit_log_list.py`:

```python
from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _seed(db, memory_id, action, actor, ts, title="t", category="general"):
    db._conn.execute(
        """INSERT INTO audit_log
           (memory_id, action, actor, timestamp, title_snapshot, category_snapshot)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (memory_id, action, actor.value, ts, title, category),
    )
    db._conn.commit()


def test_list_audit_newest_first(db):
    _seed(db, "m1", "create", Actor.API, "2026-04-26T00:00:00+00:00")
    _seed(db, "m2", "create", Actor.WEBAPP, "2026-04-26T01:00:00+00:00")
    entries = db.list_audit()
    assert [e.memory_id for e in entries] == ["m2", "m1"]


def test_list_audit_filter_by_actor(db):
    _seed(db, "m1", "create", Actor.API, "2026-04-26T00:00:00+00:00")
    _seed(db, "m2", "create", Actor.WEBAPP, "2026-04-26T01:00:00+00:00")
    entries = db.list_audit(actor=Actor.WEBAPP)
    assert len(entries) == 1
    assert entries[0].memory_id == "m2"


def test_list_audit_filter_by_action_and_memory(db):
    _seed(db, "m1", "create", Actor.API, "2026-04-26T00:00:00+00:00")
    _seed(db, "m1", "delete", Actor.API, "2026-04-26T01:00:00+00:00")
    _seed(db, "m2", "create", Actor.API, "2026-04-26T02:00:00+00:00")
    entries = db.list_audit(action="delete")
    assert [e.memory_id for e in entries] == ["m1"]
    entries = db.list_audit(memory_id="m1")
    assert len(entries) == 2


def test_list_audit_filter_by_date_range(db):
    _seed(db, "m1", "create", Actor.API, "2026-04-25T00:00:00+00:00")
    _seed(db, "m2", "create", Actor.API, "2026-04-26T12:00:00+00:00")
    _seed(db, "m3", "create", Actor.API, "2026-04-27T00:00:00+00:00")
    entries = db.list_audit(
        start=datetime(2026, 4, 26, tzinfo=UTC),
        end=datetime(2026, 4, 26, 23, 59, tzinfo=UTC),
    )
    assert [e.memory_id for e in entries] == ["m2"]


def test_list_audit_pagination(db):
    for i in range(10):
        _seed(db, f"m{i}", "create", Actor.API, f"2026-04-26T{i:02d}:00:00+00:00")
    entries = db.list_audit(limit=3, offset=2)
    # Newest first: m9, m8, m7, m6, m5, ... offset 2 -> m7, m6, m5
    assert [e.memory_id for e in entries] == ["m7", "m6", "m5"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_log_list.py -v`
Expected: FAIL — `list_audit` method missing.

**Step 3: Implement**

Add to `bearmemori/storage/database.py` (inside `MemoryDatabase`, before the final method):

```python
def _write_audit(
    self,
    memory_id: str,
    action: str,
    actor: "Actor",
    title_snapshot: str | None,
    category_snapshot: str | None,
) -> None:
    self._conn.execute(
        """INSERT INTO audit_log
           (memory_id, action, actor, timestamp, title_snapshot, category_snapshot)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            memory_id,
            action,
            actor.value,
            datetime.now(UTC).isoformat(),
            title_snapshot,
            category_snapshot,
        ),
    )

def list_audit(
    self,
    actor: "Actor | None" = None,
    action: str | None = None,
    memory_id: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    offset: int = 0,
    limit: int = 50,
) -> list["AuditEntry"]:
    limit = min(limit, 500)
    clauses: list[str] = []
    params: list = []
    if actor is not None:
        clauses.append("actor = ?")
        params.append(actor.value)
    if action is not None:
        clauses.append("action = ?")
        params.append(action)
    if memory_id is not None:
        clauses.append("memory_id = ?")
        params.append(memory_id)
    if start is not None:
        clauses.append("timestamp >= ?")
        params.append(start.isoformat())
    if end is not None:
        clauses.append("timestamp <= ?")
        params.append(end.isoformat())
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.extend([limit, offset])
    rows = self._conn.execute(
        f"SELECT * FROM audit_log{where} ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    return [
        AuditEntry(
            id=r["id"],
            memory_id=r["memory_id"],
            action=r["action"],
            actor=Actor(r["actor"]),
            timestamp=datetime.fromisoformat(r["timestamp"]),
            title_snapshot=r["title_snapshot"],
            category_snapshot=r["category_snapshot"],
        )
        for r in rows
    ]
```

Add the imports at the top of `database.py`:

```python
from bearmemori.storage.models import (
    Actor,
    AuditEntry,
    EventFields,
    MemoryCategory,
    MemoryRecord,
    MemorySource,
)
```

**Step 4: Run test**

Run: `uv run pytest tests/test_audit_log_list.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add bearmemori/storage/database.py tests/test_audit_log_list.py
git commit -m "feat: add list_audit and _write_audit helpers"
```

---

### Task 4: Wire `actor` into `MemoryDatabase.create` and write audit row

**Files:**
- Modify: `bearmemori/storage/database.py` (`create`)
- Create: `tests/test_audit_log_create.py`

**Step 1: Write the failing test**

Create `tests/test_audit_log_create.py`:

```python
from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryRecord


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _record(record_id="mem_x", title="hello", category=MemoryCategory.GENERAL):
    return MemoryRecord(
        id=record_id,
        category=category,
        title=title,
        content="content",
        created_at=datetime.now(UTC),
    )


def test_create_writes_audit_row(db):
    db.create(_record("mem_a", title="alpha"), actor=Actor.API)
    entries = db.list_audit()
    assert len(entries) == 1
    e = entries[0]
    assert e.memory_id == "mem_a"
    assert e.action == "create"
    assert e.actor == Actor.API
    assert e.title_snapshot == "alpha"
    assert e.category_snapshot == "general"


def test_create_actor_required(db):
    with pytest.raises(TypeError):
        db.create(_record())  # missing actor
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_log_create.py -v`
Expected: FAIL — `create()` does not accept `actor`.

**Step 3: Implement**

Change the signature and body of `MemoryDatabase.create` in `bearmemori/storage/database.py`. Add `actor` as a required keyword-only argument and call `_write_audit` before `commit`:

```python
def create(self, record: MemoryRecord, *, actor: Actor) -> None:
    event_dt = None
    event_status = None
    event_recurrence = None
    if record.event_fields:
        event_dt = _normalize_to_utc(record.event_fields.datetime)
        event_status = record.event_fields.status
        event_recurrence = record.event_fields.recurrence

    source_json = record.source.model_dump_json() if record.source else None
    now = datetime.now(UTC).isoformat()

    self._conn.execute(
        """INSERT INTO memories
           (id, category, title, content, raw_input, created_at, updated_at,
            tags, source, event_datetime, event_status, event_recurrence,
            metadata, needs_review, image_path, importance, archived)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            1 if record.archived else 0,
        ),
    )
    self._write_audit(
        memory_id=record.id,
        action="create",
        actor=actor,
        title_snapshot=record.title,
        category_snapshot=record.category.value,
    )
    self._conn.commit()
```

**Step 4: Update existing callers (compile-only — tests will be fixed in later tasks)**

Search and update every direct caller of `db.create` with a placeholder actor so the existing test suite still imports cleanly. Use:

```bash
grep -rn "\.create(" bearmemori/ tests/ --include="*.py" | grep -i "db\.create\|database\.create\|memory_db\.create"
```

For each match in **production code only** (we'll fix tests in their own tasks), inject the correct actor:

- `bearmemori/core/memory_service.py:103` — `self._db.create(record, actor=actor)` (actor will be passed in via `MemoryService.create` signature change in Task 8)
- `bearmemori/api/routes.py:122` (confirm_pending) — `db.create(record, actor=Actor.API)` and add `from bearmemori.storage.models import ... Actor`

For test files that call `db.create(...)` directly (e.g., `tests/test_storage.py`, `tests/test_database_archived.py`, `tests/test_reflection.py`, etc.), add `, actor=Actor.API` to each call so the suite still passes after Task 4. Import `Actor` where needed.

**Step 5: Run tests**

Run: `uv run pytest -v`
Expected: PASS for the new test plus the entire existing suite.

**Step 6: Commit**

```bash
git add bearmemori/ tests/
git commit -m "feat: require actor on MemoryDatabase.create and write audit row"
```

---

### Task 5: Wire `actor` into `MemoryDatabase.delete` and `delete_many`

**Files:**
- Modify: `bearmemori/storage/database.py` (`delete`, `delete_many`)
- Create: `tests/test_audit_log_delete.py`

**Step 1: Write the failing test**

Create `tests/test_audit_log_delete.py`:

```python
from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryRecord


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _seed(db, mid, title, cat=MemoryCategory.GENERAL):
    db.create(
        MemoryRecord(
            id=mid,
            category=cat,
            title=title,
            content="c",
            created_at=datetime.now(UTC),
        ),
        actor=Actor.API,
    )


def test_delete_writes_audit_row_with_snapshot(db):
    _seed(db, "mem_x", "to-delete", MemoryCategory.EVENT)
    db.delete("mem_x", actor=Actor.WEBAPP)
    entries = db.list_audit(memory_id="mem_x")
    assert [e.action for e in entries] == ["delete", "create"]
    delete_entry = entries[0]
    assert delete_entry.actor == Actor.WEBAPP
    assert delete_entry.title_snapshot == "to-delete"
    assert delete_entry.category_snapshot == "event"


def test_delete_missing_memory_writes_no_audit(db):
    deleted = db.delete("does_not_exist", actor=Actor.API)
    assert deleted is False
    entries = db.list_audit(action="delete")
    assert entries == []


def test_delete_many_writes_one_audit_per_id(db):
    _seed(db, "m1", "one")
    _seed(db, "m2", "two")
    _seed(db, "m3", "three")
    deleted = db.delete_many(["m1", "m2", "missing"], actor=Actor.REFLECTION)
    assert deleted == 2
    entries = db.list_audit(action="delete")
    assert {e.memory_id for e in entries} == {"m1", "m2"}
    assert all(e.actor == Actor.REFLECTION for e in entries)
    titles = {e.memory_id: e.title_snapshot for e in entries}
    assert titles == {"m1": "one", "m2": "two"}


def test_delete_many_empty_list(db):
    assert db.delete_many([], actor=Actor.API) == 0
    assert db.list_audit(action="delete") == []
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_log_delete.py -v`
Expected: FAIL — `delete()` and `delete_many()` do not accept `actor`.

**Step 3: Implement**

Replace `delete` and `delete_many` in `bearmemori/storage/database.py`:

```python
def delete(self, record_id: str, *, actor: Actor) -> bool:
    row = self._conn.execute(
        "SELECT title, category FROM memories WHERE id = ?",
        (record_id,),
    ).fetchone()
    if row is None:
        return False
    cursor = self._conn.execute("DELETE FROM memories WHERE id = ?", (record_id,))
    self._write_audit(
        memory_id=record_id,
        action="delete",
        actor=actor,
        title_snapshot=row["title"],
        category_snapshot=row["category"],
    )
    self._conn.commit()
    return cursor.rowcount > 0

def delete_many(self, record_ids: list[str], *, actor: Actor) -> int:
    if not record_ids:
        return 0
    placeholders = ", ".join("?" * len(record_ids))
    rows = self._conn.execute(
        f"SELECT id, title, category FROM memories WHERE id IN ({placeholders})",
        record_ids,
    ).fetchall()
    snapshots = {r["id"]: (r["title"], r["category"]) for r in rows}
    cursor = self._conn.execute(
        f"DELETE FROM memories WHERE id IN ({placeholders})", record_ids
    )
    for mid, (title, category) in snapshots.items():
        self._write_audit(
            memory_id=mid,
            action="delete",
            actor=actor,
            title_snapshot=title,
            category_snapshot=category,
        )
    self._conn.commit()
    return cursor.rowcount
```

**Step 4: Update existing callers**

Update production callers to pass `actor`:
- `bearmemori/core/memory_service.py:142` — `self._db.delete(record_id, actor=actor)` (actor wired up in Task 8)
- `bearmemori/api/routes.py` — only via `memory_service.delete` (covered)
- Anywhere `delete_many` is called (search `grep -rn "delete_many" bearmemori/ tests/`).

For tests calling `db.delete(...)` or `db.delete_many(...)` directly, add `, actor=Actor.API`.

**Step 5: Run tests**

Run: `uv run pytest -v`
Expected: PASS for new test + existing suite.

**Step 6: Commit**

```bash
git add bearmemori/ tests/
git commit -m "feat: require actor on MemoryDatabase.delete/delete_many and write audit rows"
```

---

### Task 6: Wire `actor` into `MemoryDatabase.update` with archive detection

**Files:**
- Modify: `bearmemori/storage/database.py` (`update`)
- Create: `tests/test_audit_log_update.py`

**Step 1: Write the failing test**

Create `tests/test_audit_log_update.py`:

```python
from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryRecord


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def _seed(db, mid="mem_x", title="t", cat=MemoryCategory.GENERAL, archived=False):
    record = MemoryRecord(
        id=mid,
        category=cat,
        title=title,
        content="c",
        created_at=datetime.now(UTC),
        archived=archived,
    )
    db.create(record, actor=Actor.API)
    return record


def test_update_writes_update_audit(db):
    record = _seed(db, title="old")
    record.title = "new"
    db.update(record, actor=Actor.WEBAPP)
    entries = db.list_audit(memory_id=record.id)
    actions = [e.action for e in entries]
    assert actions == ["update", "create"]
    update_entry = entries[0]
    assert update_entry.actor == Actor.WEBAPP
    assert update_entry.title_snapshot == "new"


def test_update_archive_transition_writes_archive_action(db):
    record = _seed(db, archived=False)
    record.archived = True
    db.update(record, actor=Actor.API)
    entries = db.list_audit(memory_id=record.id)
    assert entries[0].action == "archive"


def test_update_unarchive_transition_writes_update_action(db):
    record = _seed(db, archived=True)
    record.archived = False
    db.update(record, actor=Actor.API)
    entries = db.list_audit(memory_id=record.id)
    assert entries[0].action == "update"


def test_update_actor_required(db):
    record = _seed(db)
    with pytest.raises(TypeError):
        db.update(record)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_audit_log_update.py -v`
Expected: FAIL — `update()` does not accept `actor`.

**Step 3: Implement**

Replace `update` in `bearmemori/storage/database.py`:

```python
def update(self, record: MemoryRecord, *, actor: Actor) -> None:
    prev = self._conn.execute(
        "SELECT archived FROM memories WHERE id = ?", (record.id,)
    ).fetchone()
    prev_archived = bool(prev["archived"]) if prev else False
    becoming_archived = (not prev_archived) and record.archived
    action = "archive" if becoming_archived else "update"

    event_dt = None
    event_status = None
    event_recurrence = None
    if record.event_fields:
        event_dt = _normalize_to_utc(record.event_fields.datetime)
        event_status = record.event_fields.status
        event_recurrence = record.event_fields.recurrence

    source_json = record.source.model_dump_json() if record.source else None
    now = datetime.now(UTC).isoformat()

    self._conn.execute(
        """UPDATE memories SET category=?, title=?, content=?, raw_input=?,
           updated_at=?, tags=?, source=?, event_datetime=?, event_status=?,
           event_recurrence=?, metadata=?, needs_review=?, image_path=?,
           importance=?, archived=?
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
            1 if record.archived else 0,
            record.id,
        ),
    )
    self._write_audit(
        memory_id=record.id,
        action=action,
        actor=actor,
        title_snapshot=record.title,
        category_snapshot=record.category.value,
    )
    self._conn.commit()
```

**Step 4: Update existing callers**

Production callers of `db.update`:
- `bearmemori/core/memory_service.py:136` — `self._db.update(record, actor=actor)` (wired in Task 8)
- `bearmemori/api/routes.py:339` (PUT /memory/{id}) — `db.update(updated_record, actor=Actor.API)`
- `bearmemori/webapp/router.py:295` (memory_update) — `db.update(record, actor=Actor.WEBAPP)`
- `bearmemori/webapp/router.py:488` (toggle_occurrence) — `db.update(record, actor=Actor.WEBAPP)`

Add the `Actor` import at the top of `routes.py` and `webapp/router.py` if not already present.

For test files calling `db.update(...)` directly, add `, actor=Actor.API`.

**Step 5: Run tests**

Run: `uv run pytest -v`
Expected: PASS.

**Step 6: Commit**

```bash
git add bearmemori/ tests/
git commit -m "feat: require actor on MemoryDatabase.update and detect archive transition"
```

---

### Task 7: Verify audit rows roll back with failed memory write

**Files:**
- Create: `tests/test_audit_log_transaction.py`

**Step 1: Write the failing test**

Create `tests/test_audit_log_transaction.py`:

```python
from datetime import UTC, datetime

import pytest

from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryRecord


@pytest.fixture
def db(tmp_path):
    d = MemoryDatabase(str(tmp_path / "test.db"))
    d.initialize()
    return d


def test_audit_row_not_committed_when_memory_insert_fails(db, monkeypatch):
    record = MemoryRecord(
        id="mem_dup",
        category=MemoryCategory.GENERAL,
        title="t",
        content="c",
        created_at=datetime.now(UTC),
    )
    db.create(record, actor=Actor.API)

    duplicate = MemoryRecord(
        id="mem_dup",  # PK collision
        category=MemoryCategory.GENERAL,
        title="t2",
        content="c",
        created_at=datetime.now(UTC),
    )
    with pytest.raises(Exception):
        db.create(duplicate, actor=Actor.WEBAPP)

    entries = db.list_audit(memory_id="mem_dup")
    actors = {e.actor for e in entries}
    # only the original create's audit row exists
    assert actors == {Actor.API}
    assert len([e for e in entries if e.action == "create"]) == 1
```

**Step 2: Run test to verify it passes**

Run: `uv run pytest tests/test_audit_log_transaction.py -v`
Expected: PASS — because the failing INSERT raises before `_write_audit` is called and before `commit()`. If it does NOT pass, investigate ordering (audit must be written *after* the memory insert succeeds, which the implementation already does).

**Step 3: Commit**

```bash
git add tests/test_audit_log_transaction.py
git commit -m "test: verify audit row not written when memory insert fails"
```

---

### Task 8: Thread `actor` through `MemoryService`

**Files:**
- Modify: `bearmemori/core/memory_service.py`
- Modify: `tests/test_*` that call `MemoryService.create/update/delete/bulk_*`
- Create: `tests/test_memory_service_actor.py`

**Step 1: Write the failing test**

Create `tests/test_memory_service_actor.py`:

```python
from bearmemori.core.memory_service import MemoryService
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryDraft
from bearmemori.storage.vector_store import VectorStore


def _make_service(tmp_path):
    db = MemoryDatabase(str(tmp_path / "t.db"))
    db.initialize()
    vec = VectorStore(persist_dir=str(tmp_path / "chroma"), collection_name="t")
    vec.initialize()
    return MemoryService(db=db, vector_store=vec), db


def test_service_create_propagates_actor(tmp_path):
    service, db = _make_service(tmp_path)
    draft = MemoryDraft(
        category=MemoryCategory.GENERAL, title="hi", content="c"
    )
    record = service.create(draft, actor=Actor.TELEGRAM)
    entries = db.list_audit(memory_id=record.id)
    assert entries[0].actor == Actor.TELEGRAM


def test_service_update_propagates_actor(tmp_path):
    service, db = _make_service(tmp_path)
    record = service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title="x", content="c"),
        actor=Actor.API,
    )
    service.update(record.id, {"title": "y"}, actor=Actor.WEBAPP)
    entries = db.list_audit(memory_id=record.id, action="update")
    assert entries[0].actor == Actor.WEBAPP


def test_service_delete_propagates_actor(tmp_path):
    service, db = _make_service(tmp_path)
    record = service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title="x", content="c"),
        actor=Actor.API,
    )
    service.delete(record.id, actor=Actor.REFLECTION)
    entries = db.list_audit(memory_id=record.id, action="delete")
    assert entries[0].actor == Actor.REFLECTION


def test_service_bulk_delete_propagates_actor(tmp_path):
    service, db = _make_service(tmp_path)
    ids = []
    for i in range(3):
        rec = service.create(
            MemoryDraft(
                category=MemoryCategory.GENERAL, title=f"t{i}", content="c"
            ),
            actor=Actor.API,
        )
        ids.append(rec.id)
    service.bulk_delete(ids, actor=Actor.WEBAPP)
    entries = db.list_audit(action="delete")
    assert {e.actor for e in entries} == {Actor.WEBAPP}
    assert len(entries) == 3
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_memory_service_actor.py -v`
Expected: FAIL — `actor` parameter missing on service methods.

**Step 3: Implement**

In `bearmemori/core/memory_service.py`, add `actor` (required, keyword-only) to `create`, `update`, `delete`, `bulk_delete`, `bulk_update`:

```python
def create(self, draft: MemoryDraft, *, actor: Actor) -> MemoryRecord:
    record_id = f"mem_{uuid.uuid4().hex[:12]}"
    record = MemoryRecord.from_draft(draft, record_id=record_id)
    self._db.create(record, actor=actor)
    self._vector_store.add(record)
    logger.info("Created memory: %s", record_id)
    return record

def update(self, record_id: str, updates: dict, *, actor: Actor) -> MemoryRecord | None:
    record = self._db.get(record_id)
    if record is None:
        return None
    # ... existing field-merging logic unchanged ...
    self._db.update(record, actor=actor)
    self._vector_store.update(record)
    return record

def delete(self, record_id: str, *, actor: Actor) -> bool:
    self._delete_image(record_id)
    deleted = self._db.delete(record_id, actor=actor)
    if deleted:
        self._vector_store.delete(record_id)
    return deleted

def bulk_delete(self, record_ids: list[str], *, actor: Actor) -> int:
    count = 0
    for record_id in record_ids:
        if self.delete(record_id, actor=actor):
            count += 1
    return count

def bulk_update(self, record_ids: list[str], updates: dict, *, actor: Actor) -> int:
    count = 0
    for record_id in record_ids:
        if self.update(record_id, updates, actor=actor) is not None:
            count += 1
    return count
```

Add `from bearmemori.storage.models import Actor, ...` to the imports.

**Step 4: Update callers**

Pass actor at every `MemoryService` call site:

- `bearmemori/api/routes.py`:
  - `confirm_pending` → `db.create(record, actor=Actor.API)` (already in Task 4)
  - `delete_memory` → `memory_service.delete(record_id, actor=Actor.API)`
  - `create_memory_direct` → `memory_service.create(draft, actor=Actor.API)`
  - `bulk_delete` → `memory_service.bulk_delete(request.record_ids, actor=Actor.API)`
  - `bulk_update` → `memory_service.bulk_update(..., actor=Actor.API)`
- `bearmemori/webapp/router.py`:
  - `create_memory_submit` → `memory_service.create(draft, actor=Actor.WEBAPP)`
  - `bulk_delete` → `memory_service.bulk_delete(record_ids, actor=Actor.WEBAPP)`
  - `bulk_clear_review` → `memory_service.bulk_update(record_ids, {"needs_review": False}, actor=Actor.WEBAPP)`
  - `bulk_approve` → same with `Actor.WEBAPP`
  - `memory_delete` → `memory_service.delete(record_id, actor=Actor.WEBAPP)`
- `bearmemori/core/processor.py` and `bearmemori/core/reflection.py` — search with `grep -rn "memory_service\." bearmemori/core/` and pass `actor=Actor.REFLECTION` for any reflection-driven create/update/delete; `actor=Actor.TELEGRAM` for direct telegram-driven writes inside processor (review each call site to decide).
- `bearmemori/interfaces/telegram.py` — same: `grep -n "memory_service\.\|db\." bearmemori/interfaces/telegram.py` and pass `actor=Actor.TELEGRAM`.

For every existing test that calls `service.create/update/delete/bulk_*`, add `actor=Actor.API` (or whichever fits the test scenario). Run the suite to surface them all:

```bash
uv run pytest -v 2>&1 | grep -E "TypeError|missing"
```

**Step 5: Run tests**

Run: `uv run pytest -v`
Expected: full suite PASS.

**Step 6: Commit**

```bash
git add bearmemori/ tests/
git commit -m "feat: thread actor parameter through MemoryService and all callers"
```

---

### Task 9: Add REST `GET /audit` endpoint

**Files:**
- Modify: `bearmemori/api/routes.py`
- Modify: `bearmemori/api/schemas.py`
- Create: `tests/api/test_audit_endpoint.py`

**Step 1: Write the failing test**

Create `tests/api/test_audit_endpoint.py`:

```python
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app
from bearmemori.core.memory_service import MemoryService
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryDraft
from bearmemori.storage.pending_store import PendingStore
from bearmemori.storage.vector_store import VectorStore


@pytest.fixture
def client(tmp_path):
    db = MemoryDatabase(str(tmp_path / "t.db"))
    db.initialize()
    vec = VectorStore(persist_dir=str(tmp_path / "chroma"), collection_name="t")
    vec.initialize()
    pending = PendingStore(ttl_seconds=300)
    service = MemoryService(db=db, vector_store=vec)
    app = create_app(
        db=db,
        vector_store=vec,
        pending_store=pending,
        memory_service=service,
    )
    return TestClient(app), service, db


def _seed(service, title="t"):
    return service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title=title, content="c"),
        actor=Actor.API,
    )


def test_get_audit_returns_entries(client):
    api, service, db = client
    rec = _seed(service, title="hello")
    resp = api.get("/audit")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert any(
        e["memory_id"] == rec.id and e["action"] == "create" for e in data["entries"]
    )


def test_get_audit_filter_by_actor(client):
    api, service, db = client
    rec = _seed(service)
    service.delete(rec.id, actor=Actor.WEBAPP)
    resp = api.get("/audit?actor=webapp")
    assert resp.status_code == 200
    actions = {e["action"] for e in resp.json()["entries"]}
    assert actions == {"delete"}


def test_get_audit_filter_by_action(client):
    api, service, db = client
    rec = _seed(service)
    service.delete(rec.id, actor=Actor.API)
    resp = api.get("/audit?action=delete")
    assert resp.status_code == 200
    assert all(e["action"] == "delete" for e in resp.json()["entries"])


def test_get_audit_filter_by_memory_id(client):
    api, service, db = client
    rec1 = _seed(service)
    rec2 = _seed(service)
    resp = api.get(f"/audit?memory_id={rec1.id}")
    ids = {e["memory_id"] for e in resp.json()["entries"]}
    assert ids == {rec1.id}


def test_get_audit_invalid_actor_returns_400(client):
    api, _, _ = client
    resp = api.get("/audit?actor=invalid")
    assert resp.status_code == 400


def test_get_audit_pagination(client):
    api, service, _ = client
    for i in range(5):
        _seed(service, title=f"t{i}")
    resp = api.get("/audit?limit=2&offset=1")
    data = resp.json()
    assert len(data["entries"]) == 2
    assert data["limit"] == 2
    assert data["offset"] == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_audit_endpoint.py -v`
Expected: FAIL — `/audit` route missing.

**Step 3: Implement**

Add to `bearmemori/api/schemas.py`:

```python
class AuditEntryResponse(BaseModel):
    id: int
    memory_id: str
    action: str
    actor: str
    timestamp: str
    title_snapshot: str | None
    category_snapshot: str | None
```

Add to `bearmemori/api/routes.py` inside `create_app`, near other GET routes:

```python
@app.get("/audit")
def list_audit(
    actor: str | None = None,
    action: str | None = None,
    memory_id: str | None = None,
    start: str | None = None,
    end: str | None = None,
    offset: int = 0,
    limit: int = 50,
):
    actor_enum = None
    if actor is not None:
        try:
            actor_enum = Actor(actor)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid actor: {actor}")
    if action is not None and action not in {"create", "update", "delete", "archive"}:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    start_dt = None
    end_dt = None
    if start is not None:
        try:
            start_dt = datetime.fromisoformat(start)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'start' datetime")
    if end is not None:
        try:
            end_dt = datetime.fromisoformat(end)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'end' datetime")

    limit = min(limit, 500)
    entries = db.list_audit(
        actor=actor_enum,
        action=action,
        memory_id=memory_id,
        start=start_dt,
        end=end_dt,
        offset=offset,
        limit=limit,
    )
    return {
        "entries": [
            {
                "id": e.id,
                "memory_id": e.memory_id,
                "action": e.action,
                "actor": e.actor.value,
                "timestamp": e.timestamp.isoformat(),
                "title_snapshot": e.title_snapshot,
                "category_snapshot": e.category_snapshot,
            }
            for e in entries
        ],
        "offset": offset,
        "limit": limit,
    }
```

Make sure `Actor` is imported at the top of `routes.py`.

**Step 4: Run tests**

Run: `uv run pytest tests/api/test_audit_endpoint.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add bearmemori/api/ tests/api/test_audit_endpoint.py
git commit -m "feat: add GET /audit endpoint with filters and pagination"
```

---

### Task 10: Add webapp `/audit` page

**Files:**
- Create: `bearmemori/webapp/templates/audit.html`
- Create: `bearmemori/webapp/templates/partials/audit_table.html`
- Modify: `bearmemori/webapp/router.py`
- Create: `tests/test_webapp_audit.py`

**Step 1: Write the failing test**

Create `tests/test_webapp_audit.py`:

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bearmemori.core.memory_service import MemoryService
from bearmemori.storage.database import MemoryDatabase
from bearmemori.storage.models import Actor, MemoryCategory, MemoryDraft
from bearmemori.storage.vector_store import VectorStore
from bearmemori.webapp.auth import WebappAuthMiddleware
from bearmemori.webapp.router import create_webapp_router


@pytest.fixture
def client(tmp_path):
    db = MemoryDatabase(str(tmp_path / "t.db"))
    db.initialize()
    vec = VectorStore(persist_dir=str(tmp_path / "chroma"), collection_name="t")
    vec.initialize()
    service = MemoryService(db=db, vector_store=vec)
    auth = WebappAuthMiddleware(secret="s", session_cookie_name="sid")
    app = FastAPI()
    app.include_router(create_webapp_router(db=db, vector_store=vec, auth=auth, memory_service=service))
    api = TestClient(app)
    # bypass auth: insert valid session cookie
    api.cookies.set("sid", auth.create_session_token())
    return api, service, db


def test_audit_page_renders(client):
    api, service, db = client
    rec = service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title="hello", content="c"),
        actor=Actor.API,
    )
    resp = api.get("/webapp/audit")
    assert resp.status_code == 200
    assert "hello" in resp.text
    assert rec.id in resp.text


def test_audit_rows_partial(client):
    api, service, db = client
    service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title="hello", content="c"),
        actor=Actor.WEBAPP,
    )
    resp = api.get("/webapp/audit/rows?actor=webapp", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "hello" in resp.text


def test_audit_rows_deleted_memory_marked(client):
    api, service, db = client
    rec = service.create(
        MemoryDraft(category=MemoryCategory.GENERAL, title="goodbye", content="c"),
        actor=Actor.API,
    )
    service.delete(rec.id, actor=Actor.API)
    resp = api.get("/webapp/audit", headers={"HX-Request": "true"})
    assert "(deleted)" in resp.text
```

> If `WebappAuthMiddleware` does not expose a `create_session_token` method or session cookies are produced differently, mirror the pattern used by `tests/test_webapp.py` for authenticated requests (read that file first).

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_webapp_audit.py -v`
Expected: FAIL — `/webapp/audit` route missing.

**Step 3: Implement template**

Create `bearmemori/webapp/templates/audit.html`:

```html
{% extends "base.html" %}
{% block content %}
<h2>Audit Log</h2>
<form id="audit-filters"
      hx-get="/webapp/audit/rows"
      hx-target="#audit-rows"
      hx-trigger="change, submit"
      hx-swap="innerHTML">
  <label>Actor:
    <select name="actor">
      <option value="">all</option>
      {% for a in actors %}<option value="{{ a }}" {% if a == actor %}selected{% endif %}>{{ a }}</option>{% endfor %}
    </select>
  </label>
  <label>Action:
    <select name="action">
      <option value="">all</option>
      {% for a in actions %}<option value="{{ a }}" {% if a == action %}selected{% endif %}>{{ a }}</option>{% endfor %}
    </select>
  </label>
  <label>Start: <input type="datetime-local" name="start" value="{{ start or '' }}"></label>
  <label>End: <input type="datetime-local" name="end" value="{{ end or '' }}"></label>
</form>
<div id="audit-rows">
  {% include "partials/audit_table.html" %}
</div>
{% endblock %}
```

Create `bearmemori/webapp/templates/partials/audit_table.html`:

```html
<table>
  <thead>
    <tr>
      <th>Timestamp</th>
      <th>Action</th>
      <th>Actor</th>
      <th>Memory</th>
      <th>Category</th>
    </tr>
  </thead>
  <tbody>
    {% for e in entries %}
    <tr>
      <td>{{ e.timestamp.isoformat() }}</td>
      <td>{{ e.action }}</td>
      <td>{{ e.actor.value }}</td>
      <td>
        {% if e.memory_id in existing_ids %}
          <a href="/webapp/memories/{{ e.memory_id }}">{{ e.title_snapshot or e.memory_id }}</a>
        {% else %}
          {{ e.title_snapshot or e.memory_id }} <small>(deleted)</small>
        {% endif %}
      </td>
      <td>{{ e.category_snapshot or "" }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
```

**Step 4: Implement routes**

Add to `bearmemori/webapp/router.py` inside `create_webapp_router`. Place these alongside the other GET routes:

```python
ACTORS = [a.value for a in Actor]
AUDIT_ACTIONS = ["create", "update", "delete", "archive"]

def _audit_context(
    actor: str | None,
    action: str | None,
    start: str | None,
    end: str | None,
) -> dict:
    actor_enum = Actor(actor) if actor else None
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None
    entries = db.list_audit(
        actor=actor_enum,
        action=action or None,
        start=start_dt,
        end=end_dt,
        limit=200,
    )
    existing_ids = {e.memory_id for e in entries if db.get(e.memory_id) is not None}
    return {
        "entries": entries,
        "existing_ids": existing_ids,
        "actors": ACTORS,
        "actions": AUDIT_ACTIONS,
        "actor": actor or "",
        "action": action or "",
        "start": start or "",
        "end": end or "",
    }

@r.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    actor: str | None = None,
    action: str | None = None,
    start: str | None = None,
    end: str | None = None,
):
    ctx = _audit_context(actor, action, start, end)
    return templates.TemplateResponse(request, "audit.html", ctx)

@r.get("/audit/rows", response_class=HTMLResponse)
async def audit_rows(
    request: Request,
    actor: str | None = None,
    action: str | None = None,
    start: str | None = None,
    end: str | None = None,
):
    ctx = _audit_context(actor, action, start, end)
    return templates.TemplateResponse(request, "partials/audit_table.html", ctx)
```

Add `from bearmemori.storage.models import Actor, ...` if not already there.

**Step 5: Run tests**

Run: `uv run pytest tests/test_webapp_audit.py -v`
Expected: PASS.

**Step 6: Add nav link (optional polish)**

If `base.html` has a nav, add a link to `/webapp/audit`. Read `bearmemori/webapp/templates/base.html` first to confirm the nav structure before editing.

**Step 7: Commit**

```bash
git add bearmemori/webapp/ tests/test_webapp_audit.py
git commit -m "feat: add /webapp/audit page with HTMX filtering"
```

---

### Task 11: Final verification

**Step 1: Full suite**

Run: `uv run pytest -v`
Expected: PASS (no failures, no errors).

**Step 2: Lint and format**

Run: `uv run ruff check . && uv run ruff format .`
Expected: clean.

**Step 3: Smoke test the running app**

Run: `uv run python -m bearmemori serve --port 8100 --no-telegram` in one terminal.

In another:
```bash
curl -s http://localhost:8100/health
curl -s -X POST http://localhost:8100/memory/create \
  -H "content-type: application/json" \
  -d '{"category":"general","title":"smoke","content":"x"}'
curl -s http://localhost:8100/audit | python -m json.tool
```

Expected: the create call appears in `/audit` with `actor=api`, `action=create`.

Open `http://localhost:8100/webapp/audit` in a browser, log in, and verify the page renders the entry and that filters work.

Stop the server.

**Step 4: Commit any final cleanup**

If anything was tweaked during smoke testing:

```bash
git add -A
git commit -m "chore: polish from audit log smoke test"
```

---

## Out of scope (do not implement)

- Backfilling audit rows for memories that existed before the feature.
- Detailed diffs / full snapshots.
- Retention/purge logic.
- CLI command for audit log.
- Tracking pending-memory lifecycle.
