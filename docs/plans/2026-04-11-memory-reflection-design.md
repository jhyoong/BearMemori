# Memory Reflection Design

**Date:** 2026-04-11

## Overview

A background task (`ReflectionTask`) periodically reviews stored memories to rerank importance and archive low-value entries. It runs during a configurable off-hours window (e.g., 2–6am in the user's timezone) and can also be triggered on-demand via REST API or MCP tool. Each run produces a structured JSONL log entry and sends a Telegram summary when complete.

---

## Pre-filter Rules

Before any LLM call, rules produce a candidate list from active (non-archived) memories. A memory is a candidate if it meets **any** of these criteria:

- `importance <= 2` AND `created_at` older than `reflection_low_importance_age_days` (default: 30 days)
- `needs_review = true` AND `created_at` older than `reflection_needs_review_age_days` (default: 21 days)
- `importance` between 3–7 AND `created_at` older than `reflection_mid_importance_age_days` (default: 90 days)

All other memories are skipped.

---

## Per-memory LLM Review

For each candidate, a single LLM call is made via a new `reflect_memory()` method on `LLMClient`. The prompt includes the memory's title, content, tags, category, importance, age, and `needs_review` status.

The LLM returns a JSON decision:

```json
{
  "action": "archive" | "keep",
  "new_importance": 4,
  "reason": "outdated preference, superseded by newer entry"
}
```

- `action`: required. `archive` sets `archived = true`. `keep` leaves the record active.
- `new_importance`: optional. If present, overwrites current importance (clamped to 1–10).
- `reason`: required. Written to the log per decision.

Calls run sequentially, consistent with the existing sequential processing constraint.

---

## Database Changes

One new column on the `memories` table:

- `archived INTEGER NOT NULL DEFAULT 0` — boolean flag, added via migration in `_migrate()`

All existing read queries (`list_all`, `list_by_category`, `search_keyword`, vector search) gain a `WHERE archived = 0` filter. A new `list_archived()` method allows fetching archived memories explicitly.

`MemoryRecord` gains `archived: bool = False`.

---

## Components

### `bearmemori/core/reflection.py` (new)

`ReflectionTask` class:
- `__init__(db, vector_store, llm, bus, settings)`
- `run_once(triggered_by: str) -> ReflectionSummary` — pre-filter, per-memory LLM review, apply changes, write log entry, emit Telegram summary
- `run()` — async loop polling every `reflection_poll_interval_seconds`; checks current server time against the configured window before calling `run_once()`

### `bearmemori/llm/client.py`

New `reflect_memory(record: MemoryRecord) -> dict` method.

### `bearmemori/storage/database.py`

- `archived` column + migration
- `list_archived(offset, limit) -> list[MemoryRecord]`
- `WHERE archived = 0` added to all existing read queries

### `bearmemori/api/routes.py`

New endpoint: `POST /memory/reflection/run`
- Calls `run_once(triggered_by="api")` directly, bypassing the time window check
- Returns the `ReflectionSummary` as JSON

### `bearmemori/mcp/server.py`

New `run_reflection` tool — mirrors the REST endpoint. `ReflectionTask` passed into `create_mcp_app()`.

### `bearmemori/app.py`

Wire `ReflectionTask` into both API and MCP; start the background loop as a task alongside the existing scheduler and cleanup task.

---

## Configuration

New settings in `config.py`:

| Setting | Default | Description |
|---|---|---|
| `reflection_start_hour` | `2` | Start of allowed window (user's timezone) |
| `reflection_end_hour` | `6` | End of allowed window (user's timezone) |
| `reflection_poll_interval_seconds` | `3600` | How often the scheduler checks if it should run |
| `reflection_low_importance_age_days` | `30` | Age threshold for `importance <= 2` candidates |
| `reflection_needs_review_age_days` | `21` | Age threshold for `needs_review = true` candidates |
| `reflection_mid_importance_age_days` | `90` | Age threshold for `importance` 3–7 candidates |
| `reflection_log_path` | `data/reflection.log` | Path to the append-only JSONL log file |

If `reflection_start_hour == reflection_end_hour`, the window check is skipped and the scheduler runs freely. On-demand triggers (API, MCP) always bypass the window.

---

## Logging

Each run appends one JSON object (newline-delimited) to `reflection_log_path`:

```json
{
  "run_id": "ref_a1b2c3d4",
  "triggered_by": "scheduler" | "api" | "mcp",
  "started_at": "2026-04-11T03:00:00+00:00",
  "finished_at": "2026-04-11T03:01:42+00:00",
  "candidates_evaluated": 12,
  "archived": 3,
  "reranked": 5,
  "kept_unchanged": 4,
  "decisions": [
    {
      "memory_id": "mem_abc123",
      "action": "archive",
      "old_importance": 2,
      "new_importance": null,
      "reason": "outdated, no longer relevant"
    }
  ]
}
```

The Telegram summary includes: run ID, triggered-by, counts (archived / reranked / kept), and titles of archived memories.
