# Refactor & Simplification Design

**Date:** 2026-04-14
**Scope:** Full codebase — API, Webapp, MCP, Core, Events, Storage, LLM, CLI, Config

## Background

A critical analysis of the codebase identified significant complexity that is not justified for a single-user homelab deployment. The main themes are:

- Business logic duplicated across three transport layers (API, Webapp, MCP)
- Dead code and unused config settings accumulating
- Small bugs and confusing patterns that add maintenance burden
- Structural issues (auth fragmentation, CLI redundancy, silent failures) that affect reliability

This document covers a three-phase simplification plan ordered by risk.

---

## Phase 1 — Safe Cleanup

No behavior changes. Pure deletion and consolidation.

### Dead code deletion

| Symbol | File | Action |
|---|---|---|
| `cleanup()` | `storage/pending_store.py` | Delete. Update test that calls it to use `cleanup_with_details()` instead. |
| `size()` | `core/queue.py` | Delete. No callers. |
| `has_active_followup()` | `core/followup.py` | Delete. Tests only; no production usage. |

### Unused config settings

Delete from `config.py`. These settings exist but the code hardcodes the values elsewhere and ignores the config:

- `importance_high_threshold`
- `importance_low_threshold`
- `importance_relevance_weight`
- `importance_weight`
- `retrieval_top_k` — hardcoded as `5` in `api/routes.py`; leave the hardcoded value
- `upcoming_events_days`

### Small bug fixes

**`app.py:173`** — `WebappAuthMiddleware` is instantiated and immediately discarded before being re-instantiated via `add_middleware`. Remove the first instantiation; keep only the `add_middleware` call.

**`core/reflection.py:163`** — `now_local_hour` is assigned the UTC hour, then immediately overwritten with the local hour. The UTC assignment creates a misleading variable name. Remove the initial assignment; let the variable be set only inside the try block with UTC as the fallback default before the block.

### System prompt deduplication (`llm/client.py`)

- Extract `_CATEGORY_ENUM` and `_IMPORTANCE_SCALE` as module-level string constants
- Replace the 3+ inline definitions of each with references to those constants
- Merge `_EXTRACT_SYSTEM_TEMPLATE` and `_EXTRACTION_SYSTEM_TEMPLATE` — they define the same instructions; keep one, delete the other
- Remove the backward-compat `EXTRACT_SYSTEM_PROMPT` alias (line 95)

---

## Phase 2 — Internal Refactoring

No external behavior changes. Same API surface, same data model, same outputs. Internals restructured.

### Extract MemoryService

**Problem:** `api/routes.py`, `webapp/router.py`, and `mcp/server.py` all implement the same database and vector store operations independently. The `retrieve_context` scoring algorithm (`0.5 * similarity + 0.5 * importance`) is copy-pasted verbatim across API and MCP.

**Solution:** Create `bearmemori/core/memory_service.py` with a `MemoryService` class that owns all memory business logic. It takes `db`, `vector_store`, and `settings` at construction time and is instantiated once in `app.py`.

Methods:

```
search(query, top_k, category) -> list[MemoryRecord]
retrieve_context(query, top_k, category) -> list[dict]   # scoring logic defined here only
list(category, needs_review, archived, offset, limit) -> list[MemoryRecord]
get(record_id) -> MemoryRecord | None
create(draft: MemoryDraft) -> MemoryRecord
update(record_id, updates: dict) -> MemoryRecord | None
delete(record_id) -> bool                                # includes image file cleanup
bulk_delete(record_ids) -> int
bulk_update(record_ids, updates: dict) -> int
```

API, Webapp, and MCP become thin transport layers: parse input → call service → format response.

### Schema consolidation

Remove `CreateMemoryRequest` from `api/schemas.py`. It mirrors `MemoryDraft` from `storage/models.py` with only minor type differences. Have the API endpoint accept `MemoryDraft` directly.

### Fix metadata/source_chat_id dual source of truth

`scheduler.py._get_chat_id()` has a fallback: tries `record.source.chat_id`, falls back to `record.metadata["source_chat_id"]`. This exists because some records were created without a `source` field populated.

- Audit all record creation paths to ensure `source` is always set with `chat_id`
- Once confirmed, remove the fallback and simplify `_get_chat_id()` to `return record.source.chat_id`
- Or inline it entirely since it becomes a one-liner

### Simplify Application container

The `Application` class in `app.py` holds 12 references to components but has no methods — it is a pure data holder passed to `FastAPI.state`.

Replace with individual attributes on `api.state`:

```python
api.state.db = db
api.state.vector_store = vector_store
# etc.
```

`__main__.py` accesses components directly from `api.state`. Remove the `Application` class entirely.

### Remove LLM wrapper classes

`llm/client.py` defines three nested wrapper classes (`_AsyncCompletionsWrapper`, `_ChatWrapper`, `_ClientWrapper`) solely to make `AsyncOpenAI.chat.completions.create` patchable in tests. This is acknowledged in a comment as a workaround.

- Delete the three wrapper classes
- Refactor affected tests to inject a mock `LLMClient` at the boundary (pass the mock into the classes that use it) rather than patching OpenAI SDK internals

### Processor follow-up deduplication

`processor.py` has identical follow-up emission logic in two places: the text processing path and the image caption path. Extract a `_emit_followup_required(item, text)` private method called by both.

---

## Phase 3 — Structural Changes

Observable behavior changes. Same functionality, but auth surface, error visibility, and CLI surface change.

### Unify auth systems

Two separate auth implementations protect the same single user:
- `WebappAuthMiddleware` (session cookie + HMAC) — applied to webapp routes
- `BearerAuthMiddleware` (Bearer token) — applied to MCP sub-app

**Solution:** Replace both with a single `AuthMiddleware` that accepts either a valid session cookie or a Bearer token, both verified against the same shared secret. Apply it once to the full app. Delete `BearerAuthMiddleware` from `mcp/server.py`.

### CLI restructure

The CLI contains ~300 lines of client commands (`search`, `list`, `get`, `create`, `update`, `delete`, `briefing`, `events`, `triage`) that are thin wrappers around HTTP requests to the REST API. They duplicate the API's maintenance surface with no added value for a single-user system.

**Solution:** Remove all client commands from the CLI. Keep only:
- `serve` — starts the server
- `health` — single lightweight check to verify the server is up

Users interact with the system via the webapp or direct API calls. The `bearmemori` command becomes a server management tool only.

### Fix event bus silent failure

`events/bus.py` catches all handler exceptions, logs them, and continues. For a personal memory store, a broken handler (e.g. `confirm_handler.handle_confirmed`) can silently discard a memory with no user feedback.

**Solution:** After logging, re-raise the exception (or raise a summary exception if multiple handlers failed). A visible crash is preferable to silent data loss for this use case.

---

## What is explicitly out of scope

- **FTS5 vs ChromaDB consolidation** — deferred; decision pending
- No new features
- No API surface changes (Phase 1 and 2)
- No data model migrations
