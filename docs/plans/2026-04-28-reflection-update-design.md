# Reflection Update — Design

Date: 2026-04-28
Branch: `feature/reflection-update`

## Problem

The current reflection feature in BearMemori commits state changes (archive, rerank) to memories without user review. When the user does not have time to review the system regularly, problems compound — duplicate memories accumulate elsewhere in the system, and reflection silently mutates records the user never inspected. Reflection should surface its decisions for human review instead of acting on them directly, and should also surface duplicate memories so they can be flagged out.

## Scope

- Rework `bearmemori/core/reflection.py` so it produces proposals instead of mutating memory state.
- Add duplicate detection as a first-class reflection output.
- Add a review surface (webapp page + REST endpoints) for the user to approve or reject proposals.
- Out of scope: changing how teleBearAI's heartbeat creates memories. Heartbeat-driven duplicates will be cleaned up by the new reflection flow after the fact.

## Decisions

| Decision | Choice |
|---|---|
| Behavior change | Reflection becomes propose-and-queue. No auto-commit on archive, rerank, or merge. |
| Detection method | Hybrid — vector similarity pre-filter, then LLM confirmation. |
| Proposal contents | Recommendation + reasoning. No synthesized merge draft. |
| Review surface | Webapp only. |
| Queue lifecycle | No expiry. Reflection skips memories already in a pending proposal. |
| Scan scope per run | First run: all active memories. Subsequent runs: new memories since last run. |
| Storage | New `reflection_proposals` table (and helper join table). |

## Architecture

No new modules. Existing files change:

- `bearmemori/core/reflection.py` — `ReflectionTask` becomes a proposal generator.
- `bearmemori/storage/database.py` — new tables, new CRUD methods.
- `bearmemori/storage/models.py` — new `ReflectionProposal` dataclass.
- `bearmemori/llm/client.py` — keep `reflect_memory()`; add `reflect_duplicates()`.
- `bearmemori/api/routes.py`, `bearmemori/api/schemas.py` — new `/reflection/proposals` endpoints.
- `bearmemori/webapp/` — new `proposals.html` template + route.
- `bearmemori/config.py` — new settings.

## Data model

### `reflection_proposals`

```
id                       TEXT PRIMARY KEY     -- uuid
proposal_type            TEXT NOT NULL        -- 'merge' | 'archive' | 'rerank'
status                   TEXT NOT NULL        -- 'pending' | 'approved' | 'rejected'
memory_ids               TEXT NOT NULL        -- JSON array of memory IDs
recommended_keep_id      TEXT                 -- merge: which memory to keep
recommended_importance   INTEGER              -- rerank: new importance
reasoning                TEXT                 -- LLM explanation
resolution_note          TEXT                 -- reject reason or override note
created_at               DATETIME NOT NULL
resolved_at              DATETIME             -- set when status leaves 'pending'

INDEX idx_proposals_status (status)
```

### `reflection_proposal_memories` (helper)

```
proposal_id  TEXT
memory_id    TEXT
PRIMARY KEY (proposal_id, memory_id)
FOREIGN KEY (proposal_id) REFERENCES reflection_proposals(id) ON DELETE CASCADE
INDEX idx_proposal_memories_memory (memory_id)
```

This makes "is this memory already in a pending proposal?" a fast lookup during the nightly run.

### `ReflectionProposal` dataclass

Mirrors the table. Fields:

- `id: str`
- `proposal_type: Literal["merge", "archive", "rerank"]`
- `status: Literal["pending", "approved", "rejected"]`
- `memory_ids: list[str]`
- `recommended_keep_id: str | None`
- `recommended_importance: int | None`
- `reasoning: str`
- `resolution_note: str | None`
- `created_at: datetime`
- `resolved_at: datetime | None`

## Detection pipeline (`ReflectionTask.run_once()`)

```
1. Determine scan scope.
   - First run: all active, non-archived memories.
   - Subsequent runs: memories with created_at > last_run_timestamp.
   - last_run_timestamp persisted to data/reflection_state.json.

2. Load skip set.
   - Set of memory IDs that are referenced by any pending proposal.
   - Source: reflection_proposal_memories joined to reflection_proposals where status='pending'.
   - Skip these memories for both detection passes.

3. Duplicate detection pass.
   For each in-scope memory M (skip if M is in the skip set):
     a. Query ChromaDB for top-K (default 5) nearest neighbors with cosine similarity >= threshold (default 0.85).
     b. Filter neighbors: drop M itself, archived memories, memories in skip set, and memories in a different category.
     c. If at least one neighbor remains, form candidate group {M, ...neighbors}.
   Deduplicate candidate groups by sorted tuple of memory IDs (avoids proposing the same group twice in one run).
   For each unique group:
     - Skip the group if a 'merge' proposal with the same memory ID set was rejected within REFLECTION_REJECT_COOLDOWN_DAYS.
     - Call llm.reflect_duplicates(group). On is_duplicate=True, write a 'merge' proposal with memory_ids=sorted group, recommended_keep_id, reasoning.

4. Archive/rerank proposal pass.
   Use the existing age-based candidate criteria (REFLECTION_LOW_IMPORTANCE_AGE_DAYS, REFLECTION_NEEDS_REVIEW_AGE_DAYS, REFLECTION_MID_IMPORTANCE_AGE_DAYS).
   For each candidate not in the skip set and not consumed by a merge proposal in this run:
     - Call llm.reflect_memory(record).
     - action='archive': write 'archive' proposal (memory_ids=[id], reasoning).
     - action='keep' with new_importance != current: write 'rerank' proposal (memory_ids=[id], recommended_importance, reasoning).
     - action='keep' with same importance: no-op.

5. Update last_run_timestamp to now on success.

6. Append summary line to data/reflection.log (counts per proposal type, run duration, scope).
```

### Failure handling

If an LLM call fails for a single group or memory, log the error and continue. Do not bail the whole run.

## LLM contracts

### `reflect_memory(record)` (existing)

Unchanged. Returns `{"action": "archive"|"keep", "new_importance": <1-10|null>, "reason": "..."}`.

### `reflect_duplicates(group)` (new)

Input: list of `MemoryRecord` objects forming a candidate group.

System prompt: explain that the group was selected by similarity scan, ask the model to decide whether they describe the same fact, event, or entity. If yes, pick which to keep based on completeness, recency, and importance.

Output JSON: `{"is_duplicate": bool, "keep_id": "<id>", "reasoning": "..."}`.

The model can return `is_duplicate=False` to reject the group (no proposal written).

## REST API

```
GET  /reflection/proposals?status=pending&type=merge&limit=50&offset=0
     -> { proposals: [ProposalSummary], total: int }

GET  /reflection/proposals/{id}
     -> ProposalDetail (proposal fields + hydrated MemoryRecord per memory_id)

POST /reflection/proposals/{id}/approve
     body: optional { keep_id?: str, importance?: int }
     -> { status: 'approved', applied: { archived_ids: [...], updated_ids: [...] } }

POST /reflection/proposals/{id}/reject
     body: optional { reason?: str }
     -> { status: 'rejected' }

POST /memory/reflection/run     # existing path, new behavior
```

The existing `POST /memory/reflection/run` keeps its path so the scheduler and any manual triggers continue to work.

### Schemas

- `ProposalSummary` — id, type, status, created_at, memory count, short reasoning preview.
- `ProposalDetail` — full proposal + list of hydrated `MemoryRecord` objects.
- `ApproveProposalRequest` — optional `keep_id`, optional `importance`.
- `RejectProposalRequest` — optional `reason`.

## Webapp

New page at `/proposals` (HTMX, follows existing webapp patterns).

- Top bar: filters by `proposal_type` and `status`. Default view: pending, all types.
- One card per proposal:
  - **merge** — header "Possible duplicates". Side-by-side memory cards showing title, content, category, importance, created_at. Recommended-keep memory highlighted. LLM reasoning below. Buttons: `Approve as recommended`, `Approve, keep different memory` (radio selector), `Reject`.
  - **archive** — header "Suggested archive". Single memory card. Reasoning. Buttons: `Approve archive`, `Reject`.
  - **rerank** — header "Suggested importance change: 5 → 3". Single memory card. Reasoning. Buttons: `Approve`, `Reject`.
- After action, HTMX swaps the card with an in-place "Approved"/"Rejected" confirmation.

Auth: existing `WEBAPP_SECRET` cookie auth.

Add a navigation link to the new page.

## Proposal execution semantics

All execution runs inside a single SQLite transaction so proposal status and memory state remain consistent.

### Approve `merge`

1. Resolve `keep_id` — body override if present, else `recommended_keep_id`.
2. Validate `keep_id` is in the proposal's `memory_ids`. Return 400 otherwise.
3. Re-fetch every memory in `memory_ids` inside the transaction. If `keep_id` is already archived, return an error.
4. For each `memory_id` except `keep_id` (if not already archived):
   - `db.update(record, archived=True)`
   - `vector_store.delete(memory_id)`
5. Update proposal: `status='approved'`, `resolved_at=now()`. If user overrode `keep_id`, record that in `resolution_note`.
6. Append entry to `data/reflection.log`.

### Approve `archive`

1. `memory_id = memory_ids[0]`.
2. Re-fetch memory. If already archived, treat as no-op but still resolve the proposal.
3. Otherwise: `db.update(record, archived=True)`; `vector_store.delete(memory_id)`.
4. Resolve proposal, log.

### Approve `rerank`

1. `memory_id = memory_ids[0]`. New importance = body override if present, else `recommended_importance`.
2. Validate importance is 1-10.
3. Re-fetch memory. If archived, fail with a clear error (can't rerank an archived memory).
4. `db.update(record, importance=new)`; `vector_store.update_metadata(memory_id, importance=new)`.
5. Resolve proposal, log.

### Reject (any type)

1. Update proposal: `status='rejected'`, `resolved_at=now()`, `resolution_note=body.reason` if present.
2. Append log entry.
3. No memory state change.

## Reject cooldown

Once a `merge` proposal is rejected, the same memory ID set should not be re-proposed for `REFLECTION_REJECT_COOLDOWN_DAYS` (default 30). Implementation: during step 3.c of the detection pipeline, look up rejected merge proposals via the helper table and check `resolved_at`.

Archive and rerank rejections do not have a cooldown — once rejected, the memory falls out of the skip set and is eligible for re-evaluation. The age-based candidate criteria already provide a natural pace.

## Configuration

New settings in `bearmemori/config.py`:

- `REFLECTION_DUPLICATE_SIMILARITY_THRESHOLD: float = 0.85`
- `REFLECTION_DUPLICATE_TOP_K: int = 5`
- `REFLECTION_REJECT_COOLDOWN_DAYS: int = 30`
- `REFLECTION_STATE_PATH: str = "data/reflection_state.json"`

Existing settings unchanged: `REFLECTION_START_HOUR`, `REFLECTION_END_HOUR`, `REFLECTION_POLL_INTERVAL_SECONDS`, `REFLECTION_LOW_IMPORTANCE_AGE_DAYS`, `REFLECTION_NEEDS_REVIEW_AGE_DAYS`, `REFLECTION_MID_IMPORTANCE_AGE_DAYS`, `REFLECTION_LOG_PATH`.

Add the four new variables to `.env.example`.

## Migration

Schema changes ship via `CREATE TABLE IF NOT EXISTS` in `database.py` on startup — the existing pattern. No standalone migration script needed.

No data migration is required. Memories already archived by the old reflection behavior remain archived. Memories with `needs_review=True` set by user actions are unaffected.

The behavior change is total — no feature flag. The branch `feature/reflection-update` ships as one cohesive change.

## Testing

Extend the existing `tests/` directory.

`tests/test_reflection.py` — rewrite to cover the new flow:

- First run scans all memories; subsequent run scans only memories created since last run.
- Skip set excludes memories already in pending proposals.
- Vector similarity above threshold forms a group; below does not.
- Categorical mismatch filters neighbors.
- LLM `is_duplicate=False` drops the group.
- LLM `is_duplicate=True` writes a merge proposal with correct fields.
- The same group is not proposed twice in one run.
- A rejected merge group is not re-proposed within the cooldown.
- Archive and rerank proposals are written, not auto-applied.
- LLM failures on one item do not break the run.

`tests/test_reflection_proposals.py` (new) — proposal CRUD, status transitions, helper table behavior, cascade delete.

`tests/test_reflection_api.py` (new) — list/get/approve/reject endpoints, overrides, validation errors (e.g. `keep_id` not in group), pagination.

`tests/test_reflection_execution.py` (new):

- Approve merge archives the right memories, keeps the right one, deletes from vector store.
- Approve archive flips `archived`, deletes from vector store.
- Approve rerank updates `importance` in DB and ChromaDB metadata.
- Reject changes nothing on the memories.
- Race: memory was already archived externally — execution treats it as a no-op and resolves the proposal.
- Race: `keep_id` already archived — approve returns an error.

`tests/test_reflection_config.py` — add cases for the new settings.

Webapp smoke test — `/proposals` renders with auth, for each proposal type.

Use `pytest-asyncio` for async paths. Mock the LLM client with deterministic JSON responses.

## Documentation

- Update the reflection paragraph in `CLAUDE.md` to describe the new propose-and-queue flow.
- Update `README.md` only if it currently mentions reflection.

## Out of scope

- teleBearAI heartbeat dedup. Tracked separately.
- Telegram review interface for proposals. Webapp-only for this rework.
- Synthesized merge drafts. Recommendation + reasoning only.
- Proposal expiry / TTL. Queue is bounded by the skip-set mechanism.
