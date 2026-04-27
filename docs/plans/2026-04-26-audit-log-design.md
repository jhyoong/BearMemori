# Audit Log Design

**Date:** 2026-04-26
**Status:** Approved, ready for implementation plan

## Goal

Add a simple audit log so the user can see what memories were created, updated,
deleted, or archived, when, and by whom (Telegram, webapp, API/CLI, or the
automated reflection system).

## Scope

**Tracked actions:** create, update, delete, archive
**Tracked actors:** telegram, webapp, api, reflection
**Detail level:** minimal (action, actor, timestamp, plus title/category snapshot)
**Retention:** forever (single-user homelab, negligible storage)
**Access surfaces:** REST API endpoint and HTMX webapp page

## Approach

**Storage-layer hook.** Audit row writes happen inside
`MemoryDatabase.create / update / delete / delete_many`, in the same SQLite
transaction as the memory change. Every write path in the system already goes
through these methods, so this is the single bottleneck that guarantees
coverage. The `actor` is passed as a required parameter, so the type checker
flags any missed call site.

Considered alternatives:
- **Event-bus listener** (subscribe to `MemoryStored/Updated/Deleted`): rejected
  because not every write path emits domain events (CLI/API direct writes), and
  coverage would depend on every emit site remembering to set actor.
- **Hybrid with contextvar** (storage hook reads actor from an asyncio
  contextvar set at the interface boundary): rejected as too magical for a
  small system. Explicit parameter is simpler and easier to debug.

## Data model

New SQLite table in the existing memory database:

```sql
CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id TEXT NOT NULL,
    action TEXT NOT NULL,             -- 'create' | 'update' | 'delete' | 'archive'
    actor TEXT NOT NULL,              -- 'telegram' | 'webapp' | 'api' | 'reflection'
    timestamp TEXT NOT NULL,          -- UTC ISO 8601
    title_snapshot TEXT,
    category_snapshot TEXT
);
CREATE INDEX idx_audit_log_timestamp ON audit_log (timestamp DESC);
CREATE INDEX idx_audit_log_memory_id ON audit_log (memory_id);
CREATE INDEX idx_audit_log_actor ON audit_log (actor);
```

`title_snapshot` and `category_snapshot` are stored so audit entries remain
meaningful after a memory is deleted.

A new `Actor` string enum is added to `bearmemori/storage/models.py` with
values `telegram`, `webapp`, `api`, `reflection`. A new `AuditEntry` pydantic
model represents a row.

## Storage-layer changes

In `bearmemori/storage/database.py`:

- `create(record, actor: Actor)` — insert memory + insert audit row
  (`action='create'`) in one transaction.
- `update(record, actor: Actor)` — detect archive transition: if previous
  `archived=0` and new `archived=1`, write `action='archive'`; otherwise
  `action='update'`. Un-archiving stays as `update`.
- `delete(record_id, actor: Actor)` — fetch title/category, delete, insert
  audit row in one transaction.
- `delete_many(record_ids, actor: Actor)` — same, batched. Empty list is a
  no-op (no audit rows written).
- `list_audit(actor=None, action=None, memory_id=None, start=None, end=None,
  offset=0, limit=50)` — newest-first listing with optional filters.
- `_migrate()` creates the `audit_log` table for existing databases. No
  backfill of pre-existing memories.

`actor` is a required positional/keyword parameter (no default) so missed call
sites surface immediately.

## Caller updates

Every existing call site that writes to the database must pass an actor:

- `bearmemori/core/processor.py` — reflection pipeline → `actor='reflection'`
- `bearmemori/api/routes.py` — REST API (also serves CLI) → `actor='api'`
- `bearmemori/webapp/router.py` → `actor='webapp'`
- `bearmemori/interfaces/telegram*.py` direct write paths → `actor='telegram'`

## REST API

New endpoint in `bearmemori/api/routes.py`:

```
GET /audit?actor=&action=&memory_id=&start=&end=&offset=0&limit=50
```

Returns a JSON list of audit entries, newest first. All filters optional.
`limit` defaults to 50, max 500. Authentication uses the existing API auth
middleware.

New schema in `bearmemori/api/schemas.py`:

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

## Webapp

New routes in `bearmemori/webapp/router.py`:

```
GET /audit       -> renders templates/audit.html (full page)
GET /audit/rows  -> HTMX partial for filtered/paginated rows
```

The page shows a table: Timestamp | Action | Actor | Memory (linked title) |
Category. Filter controls at the top: actor dropdown, action dropdown, date
range. Pagination follows the existing webapp pattern.

If the referenced memory still exists, its title links to the detail page; if
deleted, the snapshot title is shown as plain text with a `(deleted)` tag.

Authentication uses the existing webapp auth middleware.

## Error handling

- Audit row insert is in the same SQLite transaction as the memory change. A
  failure rolls back both.
- `update` always writes an audit row, even when no fields actually changed.
  Simpler and rare in practice.
- Snapshot timing: `delete`/`delete_many` read snapshots before the delete;
  `create` snapshots from the inserted record; `update`/`archive` snapshot the
  post-update title/category.
- All timestamps use `datetime.now(UTC).isoformat()`.

## Testing

Tests live in `tests/`, using pytest + pytest-asyncio.

**Storage layer** (`tests/test_audit_log.py`):
- Each of `create`, `update`, `delete`, `delete_many` writes exactly one audit
  row per affected memory with the correct action and actor.
- `update` flipping `archived` 0→1 records `archive`; 1→0 records `update`.
- Deleted-memory audit rows preserve `title_snapshot` and `category_snapshot`.
- `list_audit` honors each filter and orders newest-first.
- Forced audit-insert failure rolls back the memory change (transactional).

**API tests** (extend existing API test file):
- `GET /audit` with each filter combination.
- Auth required.

**Webapp tests** (extend existing webapp test file):
- `/audit` renders the page.
- `/audit/rows` returns filtered rows.
- Deleted-memory rows show `(deleted)` and don't link.

**Migration test**:
- Existing database without `audit_log` is opened; `_migrate()` creates the
  table; existing memories are unaffected.

## Out of scope

- Backfilling audit rows for memories that existed before this feature.
- Diff or full-snapshot detail levels (only minimal snapshot now).
- Retention/purge logic (forever).
- CLI command for audit log (REST API + webapp page only).
- Tracking pending-memory lifecycle (only persisted memories).
