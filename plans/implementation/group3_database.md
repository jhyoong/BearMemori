# Group 3: Database Layer

## Goal

Create the database module with a migration system and write the initial migration containing the full schema. At the end of this group, the Core service initializes a SQLite database on startup with all tables, indexes, and the FTS5 virtual table.

**Depends on:** Group 1 (shared package), Group 2 (core scaffolding)
**Blocks:** Groups 4-6 (helpers, routers, scheduler)

---

## Context

The Life Organiser uses a single SQLite database file owned exclusively by the Core service. All other services interact with data through Core's REST API. The database uses WAL mode for concurrent read performance and FTS5 for full-text search.

Migrations are numbered SQL files applied in order. The current schema version is tracked via SQLite's `PRAGMA user_version`.

---

## Steps

### Step 3.1: Create migration system

**File:** `core/core/database.py`

**Functions to implement:**

#### `init_db(db_path: str) -> aiosqlite.Connection`

1. Ensure parent directory exists (`os.makedirs(os.path.dirname(db_path), exist_ok=True)`)
2. Open connection: `aiosqlite.connect(db_path)`
3. Enable WAL mode: `PRAGMA journal_mode=WAL`
4. Enable foreign keys: `PRAGMA foreign_keys=ON`
5. Set `row_factory = aiosqlite.Row`
6. Read current version: `PRAGMA user_version` (returns 0 for fresh DB)
7. Scan `core/migrations/` directory for files matching `NNN_*.sql` pattern (e.g., `001_initial_schema.sql`)
8. Sort by number, filter to migrations with number > current version
9. For each pending migration:
   - Read the SQL file content
   - Execute via `executescript()` (handles multiple statements)
   - Update `PRAGMA user_version = <migration_number>`
   - Log which migration was applied
10. Return the connection

**Migration file discovery:** Use `pathlib.Path` to find the migrations directory relative to the `database.py` file. Pattern: `Path(__file__).parent.parent / "migrations"`. Sort files by the numeric prefix extracted from the filename.

#### `get_db(request: Request) -> aiosqlite.Connection`

FastAPI dependency that retrieves the database connection from `request.app.state.db`.

```python
async def get_db(request: Request) -> aiosqlite.Connection:
    return request.app.state.db
```

**Directory to create:** `core/migrations/` (with an empty `__init__.py` is NOT needed -- this is a plain directory of SQL files)

---

### Step 3.2: Write initial migration

**File:** `core/migrations/001_initial_schema.sql`

This file contains the complete database schema. All table definitions come from the PRD Plan 0 section 0.5.

**Tables:**

```sql
-- Users
CREATE TABLE users (
    telegram_user_id  INTEGER PRIMARY KEY,
    display_name      TEXT NOT NULL,
    is_allowed        INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- User settings
CREATE TABLE user_settings (
    telegram_user_id      INTEGER PRIMARY KEY REFERENCES users(telegram_user_id),
    default_reminder_time TEXT NOT NULL DEFAULT '09:00',
    timezone              TEXT NOT NULL DEFAULT 'Asia/Singapore'
);

-- Memories (core entity)
CREATE TABLE memories (
    id                  TEXT PRIMARY KEY,
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    source_chat_id      INTEGER,
    source_message_id   INTEGER,
    content             TEXT,
    media_type          TEXT,
    media_file_id       TEXT,
    media_local_path    TEXT,
    status              TEXT NOT NULL DEFAULT 'confirmed',
    pending_expires_at  TEXT,
    is_pinned           INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Memory tags
CREATE TABLE memory_tags (
    memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    tag         TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'confirmed',
    suggested_at TEXT,
    confirmed_at TEXT,
    PRIMARY KEY (memory_id, tag)
);

-- Tasks
CREATE TABLE tasks (
    id                  TEXT PRIMARY KEY,
    memory_id           TEXT NOT NULL REFERENCES memories(id),
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    description         TEXT NOT NULL,
    state               TEXT NOT NULL DEFAULT 'NOT_DONE',
    due_at              TEXT,
    recurrence_minutes  INTEGER,
    completed_at        TEXT,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Reminders
CREATE TABLE reminders (
    id                  TEXT PRIMARY KEY,
    memory_id           TEXT NOT NULL REFERENCES memories(id),
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    fire_at             TEXT NOT NULL,
    recurrence_minutes  INTEGER,
    fired               INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Events
CREATE TABLE events (
    id                  TEXT PRIMARY KEY,
    memory_id           TEXT REFERENCES memories(id),
    owner_user_id       INTEGER NOT NULL REFERENCES users(telegram_user_id),
    description         TEXT NOT NULL,
    event_date          TEXT NOT NULL,
    source_type         TEXT NOT NULL,
    source_ref          TEXT,
    status              TEXT NOT NULL DEFAULT 'pending',
    pending_since       TEXT,
    reminder_id         TEXT REFERENCES reminders(id),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Audit log
CREATE TABLE audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL,
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- LLM jobs
CREATE TABLE llm_jobs (
    id              TEXT PRIMARY KEY,
    job_type        TEXT NOT NULL,
    payload         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'queued',
    attempts        INTEGER NOT NULL DEFAULT 0,
    max_attempts    INTEGER NOT NULL DEFAULT 5,
    result          TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Backup metadata
CREATE TABLE backup_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- FTS5 index (external content, synced from memories table)
CREATE VIRTUAL TABLE memories_fts USING fts5(
    content,
    tags,
    content='memories',
    content_rowid='rowid'
);
```

**Indexes:**

```sql
CREATE INDEX idx_memories_owner ON memories(owner_user_id);
CREATE INDEX idx_memories_status ON memories(status);
CREATE INDEX idx_memories_pending_expires ON memories(pending_expires_at) WHERE pending_expires_at IS NOT NULL;
CREATE INDEX idx_tasks_state ON tasks(state);
CREATE INDEX idx_tasks_owner ON tasks(owner_user_id);
CREATE INDEX idx_reminders_fire ON reminders(fire_at) WHERE fired = 0;
CREATE INDEX idx_events_status ON events(status);
CREATE INDEX idx_audit_entity ON audit_log(entity_type, entity_id);
```

---

## Design Decisions

### FTS5 External Content Table

The FTS5 table uses `content='memories'` which means it does not store its own copy of the content. This saves space but requires manual sync:

- **On INSERT:** after inserting into `memories`, insert into `memories_fts` using the rowid from the `memories` table
- **On DELETE:** before deleting from `memories`, delete from `memories_fts` using the matching rowid
- **On UPDATE:** delete old entry, insert new entry

The `content_rowid='rowid'` means the FTS5 table's rowid must match the `memories` table's implicit `rowid` column (not the TEXT `id` column). When inserting, you must:
1. Insert the memory into `memories`
2. Fetch the rowid: `SELECT rowid FROM memories WHERE id = ?`
3. Insert into FTS5: `INSERT INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)`

This is handled in Group 4 (search.py), not in the migration itself.

### WAL Mode

WAL (Write-Ahead Logging) mode allows readers to continue reading while a writer is writing. Since Core is the only writer but handles concurrent HTTP requests (some read-only), WAL prevents read requests from blocking on writes.

---

## Acceptance Criteria

1. `init_db()` creates a fresh database with all tables when the DB file does not exist
2. `init_db()` applies pending migrations when the DB file exists but has an older version
3. `init_db()` does nothing when the DB is already at the latest version (idempotent)
4. `PRAGMA user_version` is set to `1` after the initial migration
5. All tables exist and have the correct columns
6. All indexes exist
7. The FTS5 virtual table `memories_fts` exists
8. Foreign key constraints are enforced (e.g., inserting a memory with a non-existent user fails)
9. WAL mode is active (`PRAGMA journal_mode` returns `wal`)
