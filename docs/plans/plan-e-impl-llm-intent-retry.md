# Plan E: Implementation — LLM Intent Classification & Retry Overhaul

## Context

The LLM worker needs changes to support the queue-first text message flow. The intent handler must extract structured data (time, description) alongside intent classification. The retry system must differentiate between two distinct failure types: **invalid responses** (LLM returned malformed output) and **unavailability** (LLM service not reachable). Each failure type has its own retry strategy and user notification.

**Relevant BDD scenarios:** 53 (invalid response backoff), 54 (unreachable queue paused), 55 (different notifications), 56 (unavailable during image), 58 (queue persists across restarts), 62 (all retries exhausted).

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

### 3. `llm_worker/worker/retry.py` — Failure type differentiation + separate strategies

**Replace `RetryTracker` with `RetryManager` that handles two failure types:**

The BDD scenarios (53, 54, 55) require the retry system to distinguish between:
- **Invalid response** (LLM returned a response but it was malformed/unparseable): exponential backoff, max 5 attempts, then mark as failed.
- **Unavailable** (LLM service not reachable — connection refused, timeout, HTTP 5xx): pause the queue, periodically check availability, resume when reachable. Hard expiry after 14 days from original queue time.

**`RetryManager` class:**

```python
class FailureType(Enum):
    INVALID_RESPONSE = "invalid_response"
    UNAVAILABLE = "unavailable"
```

**For invalid responses (`FailureType.INVALID_RESPONSE`):**
- Track `_attempts: dict[str, int]` per job.
- `max_retries = 5`.
- `should_retry(job_id)`: return `True` if `attempts < 5`.
- `backoff_seconds(job_id)`: exponential `min(2.0 ** (attempts - 1), 16.0)` — 1s, 2s, 4s, 8s, 16s.
- On exhaustion: mark job as failed. Publish notification to Telegram with message: "I couldn't process your [image/message] after multiple attempts. You can add tags manually." (BDD Scenario 53)

**For unavailability (`FailureType.UNAVAILABLE`):**
- Track `_queue_paused: bool` flag.
- Track `_first_unavailable_time: dict[str, float]` per job.
- `max_age_seconds = 14 * 24 * 3600` (14 days).
- On first unavailability: set `_queue_paused = True`. Publish notification to Telegram with message: "I couldn't generate tags — I'll retry when the service is available." (BDD Scenario 54)
- `should_retry(job_id)`: return `True` if `time.time() - _first_unavailable_time[job_id] < max_age_seconds`.
- Periodic availability check: attempt a lightweight health check or retry the job at fixed intervals (e.g., every 30 minutes).
- When LLM becomes reachable: set `_queue_paused = False`, resume processing.
- On 14-day expiry: mark job as expired. Publish notification to Telegram with message: "Your [image/message] from [date] could not be processed because the service was unavailable and has expired." (BDD Scenario 54, step 8)

**Failure type classification in the consumer:**
- Connection errors, timeouts, HTTP 5xx → `FailureType.UNAVAILABLE`
- Successful HTTP response but unparseable/invalid JSON, missing required fields → `FailureType.INVALID_RESPONSE`

**Durability note:** The in-memory nature is acceptable since unacknowledged Redis messages are redelivered on restart. For true durability of the 14-day window, the LLM job's `created_at` timestamp in the database should be checked against the current time on restart.

### 4. `llm_worker/worker/consumer.py` — Use differentiated retry logic + expiry notifications

**Update error handling to classify failure type:**
- Wrap LLM calls in try/except that distinguishes between:
  - Connection/timeout errors → `FailureType.UNAVAILABLE`
  - Successful response but invalid content → `FailureType.INVALID_RESPONSE`
- Pass the failure type to `RetryManager` for appropriate handling.

**Update retry flow:**

For `INVALID_RESPONSE`:
- Record attempt via `RetryManager`.
- If `should_retry()` is True: sleep for backoff, re-queue.
- If `should_retry()` is False (5 attempts exhausted): mark job as failed, publish failure notification to `notify:telegram`. (BDD Scenario 62)

For `UNAVAILABLE`:
- Record unavailability via `RetryManager`.
- If first occurrence: publish "service unavailable, will retry" notification to `notify:telegram`.
- Pause queue for this job type.
- Periodically check availability (every 30 minutes or configurable).
- When available: unpause, reprocess.
- If 14-day expiry reached: mark as expired, publish expiry notification to `notify:telegram`. (BDD Scenario 54)

**Update intent result publishing:**
- Publish the full structured result (intent + entities + stale flag) to `notify:telegram` as the `llm_intent_result` message.
- Do NOT include `memory_id` — memory creation happens on the Telegram consumer side after receiving the result, since all memories start as pending.

**Handle expiry notifications:**
- New notification type `llm_expiry` published to `notify:telegram` with original message text, timestamp, and failure type (for appropriate user-facing message).
- New notification type `llm_failure` published to `notify:telegram` with original message text and failure type (for invalid response exhaustion).

---

## Files to Edit

1. `llm_worker/worker/prompts.py` — rewrite INTENT_CLASSIFY_PROMPT, add RECLASSIFY_PROMPT
2. `llm_worker/worker/handlers/intent.py` — extract structured data, handle stale timestamps, support re-classification
3. `llm_worker/worker/retry.py` — replace RetryTracker with RetryManager, separate strategies for invalid response vs unavailable
4. `llm_worker/worker/consumer.py` — classify failure types, use differentiated retry logic, publish enriched results, handle expiry/failure notifications
5. `shared/shared_lib/enums.py` — possibly add `JobStatus.expired` if not already present

## Dependencies

- Plan A (PRD) should be completed first for reference.
- This plan can be implemented in parallel with Plan D (Text Message Queue Flow) but must be completed before Plan D's consumer changes can be tested end-to-end.

## Testing

- Update `tests/test_llm_worker/test_intent_handler.py`:
  - Test structured entity extraction for each intent type
  - Test re-classification with followup context
  - Test stale timestamp detection
- Update or replace `tests/test_llm_worker/test_retry.py`:
  - Test invalid response backoff (exponential, 5 attempts max)
  - Test unavailability detection and queue pause
  - Test 14-day expiry for unavailable jobs (mock time)
  - Test queue resume when LLM becomes reachable
  - Test failure type classification (connection error vs invalid JSON)
  - Test different notification payloads for each failure type
- Update `tests/test_llm_worker/test_consumer.py`:
  - Test failure type routing (invalid response vs unavailable)
  - Test expiry notification publishing
  - Test failure notification publishing
  - Test enriched intent result publishing
