# Plan E: Implementation — LLM Intent Classification & Retry Overhaul

## Context

The LLM worker needs changes to support the queue-first text message flow. The intent handler must extract structured data (time, description) alongside intent classification. The retry system must shift from attempt-count-based to time-based expiry (14 days).

## Current State (from codebase exploration)

### `llm_worker/worker/handlers/intent.py`
- `IntentHandler(BaseHandler)` with `handle(job_id, payload, user_id)`.
- Extracts `query` from payload, formats `INTENT_CLASSIFY_PROMPT`, calls `self.llm.complete()`.
- Parses JSON result, extracts `intent` field (falls back to `"ambiguous"`).
- Returns `{"query": query, "intent": intent, "results": []}`.
- `results` is always empty — no actual search execution happens here.
- Does NOT extract any structured entities (time, description, action).

### `llm_worker/worker/prompts.py`
- `INTENT_CLASSIFY_PROMPT`: classifies `{query}` into `memory_search`, `task_lookup`, `reminder_check`, `event_search`, `ambiguous`. Returns JSON `{"intent": "...", "keywords": [...]}`.
- Current intent categories do not match the new flow's categories (reminder, task, search, general_note, ambiguous).

### `llm_worker/worker/retry.py`
- `RetryTracker` class with in-memory `_attempts` dict.
- `max_retries=5` (default). `should_retry()` checks `attempts < max_retries`.
- `backoff_seconds()` returns `min(2.0 ** (attempts - 1), 60.0)` — capped at 60 seconds.
- In-memory only — counts reset on worker restart.

### `llm_worker/worker/consumer.py`
- Main async loop. Reads Redis streams, dispatches to handlers.
- Stream-to-handler mapping includes `llm:intent` -> `IntentHandler`.
- Uses `RetryTracker` for retry decisions.
- On handler failure: records attempt, checks `should_retry()`, sleeps for backoff, then either re-queues or marks as failed.

---

## Changes Required

### 1. `llm_worker/worker/prompts.py` — Rewrite intent classification prompt

**Replace `INTENT_CLASSIFY_PROMPT` with a new prompt that:**
- Accepts `{message}` (the user's text) and `{original_timestamp}` (ISO 8601 timestamp of when the message was sent).
- Classifies into one of: `reminder`, `task`, `search`, `general_note`, `ambiguous`.
- Extracts structured entities alongside intent:
  - For `reminder`: `{"intent": "reminder", "action": "...", "time": "...", "resolved_time": "ISO8601"}`
  - For `task`: `{"intent": "task", "description": "...", "due_time": "...", "resolved_due_time": "ISO8601"}`
  - For `search`: `{"intent": "search", "query": "...", "keywords": [...]}`
  - For `general_note`: `{"intent": "general_note", "suggested_tags": [...]}`
  - For `ambiguous`: `{"intent": "ambiguous", "followup_question": "...", "possible_intents": ["reminder", "task"]}`
- The `resolved_time` / `resolved_due_time` fields should be absolute ISO 8601 datetimes, resolved relative to `{original_timestamp}`.
- Instruct the LLM to generate a natural follow-up question for ambiguous intents.

**Add a new prompt `RECLASSIFY_PROMPT`:**
- Accepts `{original_message}`, `{followup_question}`, `{user_answer}`, `{original_timestamp}`.
- Re-classifies with the full conversation context.
- Returns the same structured JSON as above.

### 2. `llm_worker/worker/handlers/intent.py` — Extract structured data + handle stale timestamps

**Modify `IntentHandler.handle()`:**
- Extract `message` (or `query`), `original_timestamp`, and optionally `followup_context` from payload.
- If `followup_context` is present, use `RECLASSIFY_PROMPT` instead of the standard prompt.
- Parse the full structured JSON response (not just `intent`).
- For `reminder` and `task` intents: check if `resolved_time` / `resolved_due_time` is in the past relative to the current time. If so, add `"stale": true` to the result.
- Return the full structured result (intent + entities + stale flag).

**Keep backward compatibility:**
- If the payload contains `query` (old format), handle it as before for existing callers.

### 3. `llm_worker/worker/retry.py` — Time-based expiry

**Modify `RetryTracker`:**
- Change from attempt-count-based to time-based expiry.
- Store `_first_attempt_time: dict[str, float]` alongside `_attempts`.
- New constructor: `__init__(self, max_age_seconds=14 * 24 * 3600)` (default: 14 days).
- `record_attempt(job_id)`: record the first attempt time if not already set; increment attempt count.
- `should_retry(job_id)`: return `True` if `time.time() - _first_attempt_time[job_id] < max_age_seconds`.
- `backoff_seconds(job_id)`: use tiered strategy:
  - Attempts 1-5: exponential `min(2.0 ** (attempts - 1), 16.0)` (1s, 2s, 4s, 8s, 16s)
  - Attempts 6+: fixed 1800 seconds (30 minutes)
- `is_expired(job_id)`: return `True` if the job has exceeded `max_age_seconds`.
- `clear(job_id)`: remove both `_attempts` and `_first_attempt_time` entries.

**Note:** The in-memory nature is acceptable since unacknowledged Redis messages are redelivered on restart. The first_attempt_time will reset on restart, effectively giving the job more time — but this is a safe-side failure mode. For true durability, the LLM job's `created_at` timestamp in the database should be checked.

### 4. `llm_worker/worker/consumer.py` — Use new retry logic + expiry notifications

**Update retry handling:**
- When `should_retry()` returns `False` and `is_expired()` returns `True`, mark the job as expired (not just failed).
- Publish an `llm_expiry` notification to `notify:telegram` stream with the original message text and timestamp, so the Telegram consumer can notify the user.

**Update intent result publishing:**
- Publish the full structured result (intent + entities + stale flag) to `notify:telegram` as the `llm_intent_result` message.
- Include the `memory_id` if a memory was created, or signal that no memory should be created (for search intent).

---

## Files to Edit

1. `llm_worker/worker/prompts.py` — rewrite INTENT_CLASSIFY_PROMPT, add RECLASSIFY_PROMPT
2. `llm_worker/worker/handlers/intent.py` — extract structured data, handle stale timestamps, support re-classification
3. `llm_worker/worker/retry.py` — time-based expiry, tiered backoff
4. `llm_worker/worker/consumer.py` — use new retry logic, publish enriched results, handle expiry notifications
5. `shared/shared_lib/enums.py` — possibly add `JobStatus.expired` if not already present

## Dependencies

- Plan A (PRD) should be completed first for reference.
- This plan can be implemented in parallel with Plan D (Text Message Queue Flow) but must be completed before Plan D's consumer changes can be tested end-to-end.

## Testing

- Update `tests/test_llm_worker/test_intent_handler.py`:
  - Test structured entity extraction for each intent type
  - Test re-classification with followup context
  - Test stale timestamp detection
- Update `tests/test_llm_worker/test_retry.py`:
  - Test time-based expiry (mock time)
  - Test tiered backoff strategy
  - Test `is_expired()` method
- Update `tests/test_llm_worker/test_consumer.py`:
  - Test expiry notification publishing
  - Test enriched intent result publishing
