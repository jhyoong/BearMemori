# Triage Rework Design

Date: 2026-04-11

## Goal

Add `triage_conversation` as an MCP tool so AI agents can use it, and unify the triage LLM call path with the rest of the system (`LLMClient`).

## Background

The triage feature analyses a conversation and decides whether any information is worth saving as a memory. It currently has two entry points:

- **REST API** (`POST /memory/triage`): external callers submit a conversation, triage runs via LLM, a draft is stored in `PendingStore`, and a `pending_id` is returned. The caller then confirms via `POST /memory/confirm`.
- **CLI** (`bearmemori triage`): thin wrapper around the REST endpoint.

The MCP server has no triage tool. AI agents have no way to ask "is this worth saving?"

There is also a structural inconsistency: `run_triage()` in `core/triage.py` makes its own raw `httpx.AsyncClient` calls to the LLM endpoint, bypassing `LLMClient` which is the intended interface for all LLM interaction in the system.

## Design

### Approach

Unify the triage LLM call path through `LLMClient`, then expose triage as an MCP tool. The REST endpoint behaviour is unchanged. The pending/review flow is preserved for both REST and MCP callers — all triaged memories go into `PendingStore` for user review via the webapp or Telegram.

### Section 1: LLM Client

Two new methods are added to `LLMClient` in `bearmemori/llm/client.py`:

- `async triage(conversation_text, hint_text, current_time) -> dict` — runs the full triage prompt (should_save decision + extraction in one call). Returns the parsed JSON dict.
- `async extract_triage(conversation_text, current_time) -> dict` — runs the extraction-only prompt (high-confidence path, skips should_save decision). Returns the parsed JSON dict.

The triage-specific prompt templates (`_TRIAGE_SYSTEM_TEMPLATE`, `_EXTRACTION_SYSTEM_TEMPLATE`) move from `core/triage.py` into `llm/client.py` alongside the other prompts. The backward-compatible `TRIAGE_SYSTEM_PROMPT` alias is removed.

### Section 2: core/triage.py

`run_triage()` signature changes from accepting individual LLM connection params (`llm_base_url`, `llm_api_key`, `llm_model`, `llm_max_tokens`, `triage_timeout`) to accepting a single `LLMClient` instance.

The internal decision logic is unchanged:
- High-confidence path calls `llm.extract_triage()`, falls back to full triage on failure.
- Full triage path calls `llm.triage()`.
- `_build_draft()`, `TriageResult`, `_extract_from_response()`, `_run_full_triage()`, `_try_extraction()` all stay in `core/triage.py`.

The `_llm_call()` helper is deleted.

`api/routes.py` is updated: `create_app()` replaces the five LLM connection params with a single `llm: LLMClient` parameter. `run_triage()` is called with the shared client.

`app.py` is updated accordingly.

### Section 3: MCP tool

`create_mcp_app()` in `bearmemori/mcp/server.py` gains two new parameters: `llm: LLMClient` and `pending_store: PendingStore`.

A new `triage_conversation` async tool is added:

- **Input:** `conversation` (list of role/content dicts), `memory_hint` (optional dict), `current_time` (optional ISO string)
- **Behaviour:** calls `run_triage()` with the shared `LLMClient`. If `should_save=True`, adds the draft to `pending_store` and returns `{should_save: true, pending_id, draft}`. If `should_save=False`, returns `{should_save: false, reason?}`.

No confirm tool is added to MCP. The user reviews pending memories via the webapp or Telegram.

`app.py` passes `llm` and `pending_store` into `create_mcp_app()`.

### Section 4: Testing

Existing `run_triage()` tests switch from patching `httpx.AsyncClient` to patching `LLMClient.triage()` and `LLMClient.extract_triage()`.

New tests:
- `LLMClient.triage()` and `LLMClient.extract_triage()` — verify prompt formatting and response parsing.
- MCP `triage_conversation` tool — verify correct `pending_store` interaction and response shape for both `should_save=True` and `should_save=False`.

## Files Changed

| File | Change |
|------|--------|
| `bearmemori/llm/client.py` | Add `triage()` and `extract_triage()` methods; move triage prompt templates here |
| `bearmemori/core/triage.py` | Change `run_triage()` to accept `LLMClient`; remove `_llm_call()`; remove prompt templates |
| `bearmemori/mcp/server.py` | Add `triage_conversation` async tool; add `llm` and `pending_store` params to `create_mcp_app()` |
| `bearmemori/api/routes.py` | Replace individual LLM params with `llm: LLMClient` in `create_app()` |
| `bearmemori/app.py` | Pass `llm` and `pending_store` to `create_mcp_app()`; pass `llm` to `create_app()` |
| `tests/` | Update existing triage tests; add new LLM client and MCP tool tests |
