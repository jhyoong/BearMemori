# Group 4: Cross-Cutting Helpers (Audit + FTS5)

## Goal

Create the audit logging helper and FTS5 search module. These are used by all routers and the scheduler, so they must be built before those groups.

**Depends on:** Group 3 (database layer)
**Blocks:** Group 5 (routers), Group 6 (scheduler)

---

## Context

Every state change in the system is recorded in the `audit_log` table for debugging and traceability. The audit helper is called by every router and the scheduler.

Full-text search uses SQLite FTS5 with an external content table (`memories_fts` backed by `memories`). The search module manages FTS5 index sync and provides the query interface with pin boosting.

---

## Steps

### Step 4.1: Audit logging helper

**File:** `core/core/audit.py`

**Function:**

```python
async def log_audit(
    db: aiosqlite.Connection,
    entity_type: str,    # e.g., "memory", "task", "reminder", "event", "llm_job"
    entity_id: str,      # UUID of the entity
    action: str,         # e.g., "created", "updated", "deleted", "fired", "expired"
    actor: str,          # e.g., "user:123456", "system:scheduler", "system:llm_worker"
    detail: dict | None = None  # optional JSON-serializable context
) -> None:
```

**Implementation:**
1. Serialize `detail` to JSON string if provided (use `json.dumps`), else `None`
2. Execute: `INSERT INTO audit_log (entity_type, entity_id, action, actor, detail) VALUES (?, ?, ?, ?, ?)`
3. Commit the transaction

**Usage pattern in routers:**
```python
await log_audit(db, "memory", memory_id, "created", f"user:{user_id}")
await log_audit(db, "task", task_id, "updated", f"user:{user_id}", {"state": "DONE"})
await log_audit(db, "reminder", reminder_id, "fired", "system:scheduler")
```

---

### Step 4.2: FTS5 search module

**File:** `core/core/search.py`

**Functions:**

#### `async def index_memory(db: aiosqlite.Connection, memory_id: str) -> None`

Upserts the FTS5 entry for a memory. Only indexes confirmed memories.

1. Fetch the memory: `SELECT rowid, content, status FROM memories WHERE id = ?`
2. If not found or `status != 'confirmed'`, call `remove_from_index()` and return
3. Fetch confirmed tags: `SELECT tag FROM memory_tags WHERE memory_id = ? AND status = 'confirmed'`
4. Concatenate tags as space-separated string
5. Remove existing FTS5 entry (if any): `INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES ('delete', ?, ?, ?)`
   - For the delete command, you need the OLD content values. A safer approach: always delete first then insert.
   - Alternative: use the FTS5 delete command with the current indexed values
6. Insert new entry: `INSERT INTO memories_fts(rowid, content, tags) VALUES (?, ?, ?)`

**Important FTS5 external content sync pattern:**

For external content FTS5 tables, the recommended delete pattern is:
```sql
-- To delete: supply the OLD values that were indexed
INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES('delete', <old_rowid>, <old_content>, <old_tags>);
```

A simpler approach is to use the `rebuild` command occasionally, but for per-record updates:
1. Before updating, read the current memory content and tags from the `memories` table
2. Issue the FTS5 delete with those old values
3. Issue the FTS5 insert with the new values

Or, use a "delete + reinsert" pattern where you track what was last indexed. For simplicity in this project, use this approach:
1. Try to delete the old entry (may fail silently if not indexed)
2. Insert the new entry

Since we control all index operations through this function, we can maintain consistency.

#### `async def remove_from_index(db: aiosqlite.Connection, memory_id: str) -> None`

Removes the FTS5 entry for a memory.

1. Fetch: `SELECT rowid, content FROM memories WHERE id = ?`
2. Fetch confirmed tags for the memory
3. If found: `INSERT INTO memories_fts(memories_fts, rowid, content, tags) VALUES('delete', ?, ?, ?)`

#### `async def search_memories(db, query: str, owner_user_id: int, pinned_only: bool = False, limit: int = 20, offset: int = 0) -> list[dict]`

Queries FTS5 and returns results with pin boost.

1. Build the FTS5 query: `SELECT m.*, memories_fts.rank FROM memories_fts JOIN memories m ON m.rowid = memories_fts.rowid WHERE memories_fts MATCH ? AND m.owner_user_id = ? AND m.status = 'confirmed'`
2. If `pinned_only`: add `AND m.is_pinned = 1`
3. Order by: `ORDER BY m.is_pinned DESC, rank` (pinned items sort first, then by FTS5 relevance rank)
4. Apply `LIMIT ? OFFSET ?`
5. For each result, fetch its tags from `memory_tags`
6. Return list of dicts with memory fields, tags, and relevance score

**FTS5 query sanitization:** The user's search query should be passed through FTS5's query syntax. For safety, wrap each search term in double quotes to treat them as literal phrases, or use the `{column}:{term}` syntax. At minimum, escape special FTS5 characters.

---

## Design Notes

### FTS5 Rank

FTS5 provides a built-in `rank` column that scores results by relevance (negative values, closer to 0 = more relevant). The default ranking function is BM25. No configuration is needed.

### Pin Boost

Pin boost is implemented at query time by sorting `is_pinned DESC` before `rank`. This means all pinned results appear before non-pinned results, regardless of text relevance. This matches the PRD requirement.

### When to Call Index Functions

- `index_memory()`: after creating a confirmed memory, after updating a memory's content or status, after adding/removing confirmed tags
- `remove_from_index()`: before deleting a memory

These calls are made in the routers (Group 5) and scheduler (Group 6).

---

## Acceptance Criteria

1. `log_audit()` inserts a row into `audit_log` with correct fields
2. `log_audit()` with `detail=None` stores NULL
3. `log_audit()` with `detail={"key": "value"}` stores valid JSON string
4. `index_memory()` indexes a confirmed memory with its content and tags
5. `index_memory()` does not index a pending memory
6. `index_memory()` updates the index when called again after content change
7. `remove_from_index()` removes a memory from the FTS5 index
8. `search_memories()` returns matching results for a keyword query
9. `search_memories()` returns pinned results before non-pinned results
10. `search_memories()` only returns confirmed memories
11. `search_memories()` respects the `owner_user_id` filter
12. `search_memories()` respects `limit` and `offset` for pagination
