# Fix Message Concurrency and Time Resolution Issues

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix three issues discovered from production logs: (1) the user lock is released prematurely during followup flows, allowing queued messages to jump ahead of an active conversation; (2) the LLM resolves ambiguous time references to the past instead of the next future occurrence; (3) PEL busy-wait causes excessive INFO-level log spam.

**Architecture:** The per-user lock in the LLM worker prevents concurrent message processing. During ambiguous/followup flows, `receive_followup_answer` releases the lock before creating the reclassification job. Since PEL messages are processed before new stream messages, a queued job (message 2) gets picked up before the reclassification job (message 1's continuation). The fix: don't release the lock in `receive_followup_answer`, and allow reclassification jobs (those with `followup_context`) to bypass lock acquisition since the lock is already held by the same user's conversation. For time resolution, add a "next occurrence" rule to the LLM prompt. For log spam, move the processing log after the lock check.

**Tech Stack:** Python, asyncio, Redis, pytest, fakeredis

---

### Task 1: Allow reclassification jobs to bypass lock acquisition

The lock is currently held during a followup conversation. When `receive_followup_answer` creates a reclassification job, it must release the lock first so the worker can re-acquire it. But this creates a window where other queued jobs (in PEL) jump ahead.

Fix: Jobs with `followup_context` in their payload should skip lock acquisition, since the lock is already held by the same user's active conversation.

**Files:**
- Modify: `llm_worker/worker/consumer.py:100-212`
- Test: `tests/test_llm_worker/test_consumer.py`

**Step 1: Write the failing test**

Add to `tests/test_llm_worker/test_consumer.py`:

```python
@pytest.mark.asyncio
async def test_followup_job_skips_lock_acquisition(
    mock_redis, mock_handlers, mock_core_api, retry_tracker, config
):
    """A job with followup_context should skip lock acquisition and process
    even when the user lock is already held."""
    # Pre-set the user lock (simulating lock held from previous conversation)
    await mock_redis.set("llm:user_lock:42", "1", ex=604800)

    data = {
        "job_id": "job-followup",
        "job_type": "intent_classify",
        "user_id": 42,
        "payload": {
            "message": "remind me about courses",
            "original_timestamp": "2026-03-06T01:00:00+00:00",
            "user_timezone": "Asia/Singapore",
            "followup_context": {
                "followup_question": "When?",
                "user_answer": "at 3pm",
            },
        },
    }

    await _process_message(
        redis_client=mock_redis,
        stream_name="llm:intent",
        message_id="1234-0",
        data=data,
        handlers=mock_handlers,
        core_api=mock_core_api,
        retry_tracker=retry_tracker,
        config=config,
        from_pel=False,
    )

    # Handler should have been called despite lock being held
    mock_handlers["intent_classify"].handle.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_worker/test_consumer.py::test_followup_job_skips_lock_acquisition -v`
Expected: FAIL — handler is not called because lock acquisition fails.

**Step 3: Write minimal implementation**

In `llm_worker/worker/consumer.py`, modify the lock acquisition block in `_process_message` (around lines 204-212):

```python
    # Acquire per-user lock to prevent concurrent processing for the same user.
    # If the lock is held, return without acking so the message stays in the PEL
    # and is retried on the next consumer loop iteration.
    # Exception: followup/reclassification jobs (those with followup_context in payload)
    # bypass lock acquisition because the lock is already held by the same user's
    # active conversation flow.
    user_lock_acquired = False
    is_continuation = bool(payload.get("followup_context"))
    if user_id is not None and not is_continuation:
        user_lock_acquired = await acquire_user_lock(redis_client, str(user_id))
        if not user_lock_acquired:
            logger.debug("User %s lock held, deferring job %s", user_id, job_id)
            return
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm_worker/test_consumer.py::test_followup_job_skips_lock_acquisition -v`
Expected: PASS

**Step 5: Run all consumer tests**

Run: `pytest tests/test_llm_worker/test_consumer.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add llm_worker/worker/consumer.py tests/test_llm_worker/test_consumer.py
git commit -m "fix: allow reclassification jobs to bypass lock acquisition"
```

---

### Task 2: Stop releasing lock in receive_followup_answer

Now that reclassification jobs bypass lock acquisition, `receive_followup_answer` no longer needs to release the lock before creating the job. The lock will remain held throughout the entire conversation flow (original message -> ambiguous -> followup answer -> reclassification -> final intent -> user confirmation).

**Files:**
- Modify: `telegram/tg_gateway/handlers/conversation.py:362-369`
- Test: `tests/test_telegram/test_conversation.py`

**Step 1: Write the failing test**

Add to `tests/test_telegram/test_conversation.py`:

```python
@pytest.mark.asyncio
async def test_followup_answer_does_not_release_lock(mock_redis):
    """receive_followup_answer should NOT release the user lock.
    The lock stays held so queued messages can't jump ahead."""
    # Pre-set the lock
    await mock_redis.set("llm:user_lock:42", "1", ex=604800)

    # Build update and context mocks
    update = AsyncMock()
    update.message.from_user.id = 42
    update.message.text = "at 3pm"

    context = AsyncMock()
    context.user_data = {
        PENDING_LLM_CONVERSATION: {
            "memory_id": "mem-123",
            "original_text": "remind me about courses",
            "followup_question": "When?",
            "original_timestamp": "2026-03-06T01:00:00+00:00",
            "user_timezone": "Asia/Singapore",
        }
    }
    context.bot_data = {
        "core_client": AsyncMock(),
        "redis": mock_redis,
    }

    await receive_followup_answer(update, context)

    # Lock should still be held
    lock_value = await mock_redis.get("llm:user_lock:42")
    assert lock_value is not None, "Lock should NOT be released during followup"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_telegram/test_conversation.py::test_followup_answer_does_not_release_lock -v`
Expected: FAIL — lock is released (current behavior).

**Step 3: Remove lock release from receive_followup_answer**

In `telegram/tg_gateway/handlers/conversation.py`, remove lines 362-369 (the lock release block):

```python
    # REMOVED: Lock release moved out of followup flow.
    # The lock stays held so queued messages can't jump ahead of the
    # reclassification job. The reclassification job (with followup_context)
    # bypasses lock acquisition in the LLM worker.
```

Delete these lines:
```python
    # Release the per-user lock before creating the new job so the worker
    # can acquire it when processing the reclassification.
    redis_client = context.bot_data.get("redis")
    if redis_client:
        try:
            await release_user_lock(redis_client, str(user.id))
        except Exception:
            logger.exception("Failed to release user lock for user %s", user.id)
```

Also remove the `release_user_lock` import if it's no longer used elsewhere in the file. Check first — `release_user_lock` is NOT used elsewhere in `conversation.py`, so remove it from the import line.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_telegram/test_conversation.py::test_followup_answer_does_not_release_lock -v`
Expected: PASS

**Step 5: Run all telegram tests**

Run: `pytest tests/test_telegram/ -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add telegram/tg_gateway/handlers/conversation.py tests/test_telegram/test_conversation.py
git commit -m "fix: keep user lock held during followup flow to prevent message queue jumping"
```

---

### Task 3: Ensure lock is not released on error for continuation jobs

When a reclassification job fails (exception in handler), the error path in `_process_message` releases the lock. For continuation jobs (where we didn't acquire the lock), we must NOT release it — the lock belongs to the parent conversation.

**Files:**
- Modify: `llm_worker/worker/consumer.py:265-402`
- Test: `tests/test_llm_worker/test_consumer.py`

**Step 1: Write the failing test**

Add to `tests/test_llm_worker/test_consumer.py`:

```python
@pytest.mark.asyncio
async def test_followup_job_error_does_not_release_lock(
    mock_redis, mock_handlers, mock_core_api, retry_tracker, config
):
    """When a reclassification job fails, the lock should NOT be released
    because it was not acquired by this job (it belongs to the parent flow)."""
    # Pre-set the user lock
    await mock_redis.set("llm:user_lock:42", "1", ex=604800)

    mock_handlers["intent_classify"].handle.side_effect = ValueError("parse error")

    data = {
        "job_id": "job-fail",
        "job_type": "intent_classify",
        "user_id": 42,
        "payload": {
            "message": "remind me",
            "followup_context": {
                "followup_question": "When?",
                "user_answer": "tomorrow",
            },
        },
    }

    await _process_message(
        redis_client=mock_redis,
        stream_name="llm:intent",
        message_id="5678-0",
        data=data,
        handlers=mock_handlers,
        core_api=mock_core_api,
        retry_tracker=retry_tracker,
        config=config,
        from_pel=False,
    )

    # Lock must still be held
    lock_value = await mock_redis.get("llm:user_lock:42")
    assert lock_value is not None, "Lock should NOT be released for failed continuation jobs"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_worker/test_consumer.py::test_followup_job_error_does_not_release_lock -v`
Expected: FAIL — error path releases the lock.

**Step 3: Update error paths to check user_lock_acquired**

In `llm_worker/worker/consumer.py`, the error handling already checks `if user_lock_acquired:` before calling `release_user_lock`. Since `user_lock_acquired` stays `False` for continuation jobs (we skip acquisition), the lock should NOT be released. Verify this is the case in all error paths (lines ~301, 334, 373, 401).

If the existing code already guards with `if user_lock_acquired:`, this test should pass without changes. Run the test to confirm.

**Step 4: Run test to verify**

Run: `pytest tests/test_llm_worker/test_consumer.py::test_followup_job_error_does_not_release_lock -v`
Expected: PASS (the existing `if user_lock_acquired:` guards already protect this case)

**Step 5: Commit**

```bash
git add tests/test_llm_worker/test_consumer.py
git commit -m "test: verify lock is not released on error for continuation jobs"
```

---

### Task 4: Add "next occurrence" rule to INTENT_CLASSIFY_PROMPT

The LLM resolved "remind me to shower at 11" to 11:00 AM on the current day, even though that time had already passed in the user's timezone. The prompt needs an explicit rule: if the resolved time is in the past, resolve to the next future occurrence.

**Files:**
- Modify: `llm_worker/worker/prompts.py:50-58`

**Step 1: Update INTENT_CLASSIFY_PROMPT**

In `llm_worker/worker/prompts.py`, add to the CRITICAL timezone block (after the line "NEVER return the original_timestamp unchanged"):

```
If the resolved time would be in the past relative to the original_timestamp, resolve to
the NEXT future occurrence. For example, if it is 7pm on March 6 and the user says
"at 3pm", resolve to 3pm on March 7 (not March 6, which is already past).
Similarly, "at 11" when current time is 7pm should resolve to 11am the next day.
```

**Step 2: Update RECLASSIFY_PROMPT with the same rule**

In `llm_worker/worker/prompts.py`, add the same "next occurrence" rule to the RECLASSIFY_PROMPT's CRITICAL timezone block (after the timezone conversion example):

```
If the resolved time would be in the past relative to the original_timestamp, resolve to
the NEXT future occurrence. For example, if it is 7pm and the user says "at 3pm",
resolve to 3pm the next day.
```

**Step 3: Run all intent tests**

Run: `pytest tests/test_llm_worker/test_intent.py -v`
Expected: All PASS (prompt changes don't break mocked tests)

**Step 4: Commit**

```bash
git add llm_worker/worker/prompts.py
git commit -m "fix: add next-occurrence rule to prevent LLM resolving times to the past"
```

---

### Task 5: Fix PEL busy-wait log spam

When a message is in the PEL and the user lock is held, the consumer loop reads the message every ~100ms and logs "Processing message X from stream" at INFO level BEFORE the lock check. This produces hundreds of duplicate log lines per second.

Fix: Move the "Processing message" log inside `_process_message`, after the lock check succeeds.

**Files:**
- Modify: `llm_worker/worker/consumer.py:455-458`

**Step 1: Reduce log level for PEL message processing**

In `llm_worker/worker/consumer.py`, in the `run_consumer` loop (around line 455-458), change the log level for PEL messages:

```python
            for stream_name, message_id, data in all_messages:
                if from_pel:
                    logger.debug(
                        "Checking PEL message %s from %s", message_id, stream_name
                    )
                else:
                    logger.info(
                        "Processing message %s from %s", message_id, stream_name
                    )
                await _process_message(
                    redis_client=redis_client,
                    stream_name=stream_name,
                    message_id=message_id,
                    data=data,
                    handlers=handlers,
                    core_api=core_api,
                    retry_tracker=retry_tracker,
                    config=config,
                    from_pel=from_pel,
                )
```

**Step 2: Add an INFO log inside _process_message after lock check**

In `_process_message`, add a log AFTER the lock is successfully acquired (around line 213, before the handler call):

This is already covered by the existing log at line 216-221 (`"Calling handler %s for job %s"`), so no additional log is needed. The combination of DEBUG for PEL iteration + existing INFO for handler call gives proper visibility without spam.

**Step 3: Run all consumer tests**

Run: `pytest tests/test_llm_worker/test_consumer.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add llm_worker/worker/consumer.py
git commit -m "fix: reduce PEL message processing log level to DEBUG to prevent log spam"
```

---

### Task 6: Run full test suite and verify

**Step 1: Run all tests**

Run: `pytest -v`
Expected: All PASS

**Step 2: Run linting**

Run: `ruff check .`
Expected: No errors

**Step 3: Final commit (if any lint fixes needed)**

```bash
git add -A
git commit -m "fix: lint fixes for message concurrency changes"
```
