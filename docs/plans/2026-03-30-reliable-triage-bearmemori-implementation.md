# BearMemori Reliable Triage Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the BearMemori triage LLM flow more consistent by adding confidence-based override, prompt hardening, and better error handling.

**Architecture:** Add an extraction-only prompt path for high-confidence hints that skips the should_save decision. Harden the existing triage prompt to bias toward saving. Add retry-on-failure and structured reason codes to the API response.

**Tech Stack:** Python 3.12+, FastAPI, pydantic, httpx, pytest + pytest-asyncio

---

### Task 1: Add extraction-only prompt template

**Files:**
- Modify: `bearmemori/core/triage.py:41-86`
- Test: `tests/test_triage.py`

**Step 1: Write the failing test**

Add to `tests/test_triage.py`:

```python
@pytest.mark.asyncio
async def test_triage_high_confidence_skips_should_save():
    """When memory_hint has confidence='high', triage should always save."""
    # LLM returns extraction-only fields (no should_save field)
    response_data = {
        "category": "reminder",
        "title": "Pack bag",
        "content": "Pack bag in 10 minutes",
        "tags": ["reminder"],
        "importance": 6,
        "event_fields": {"datetime": "2026-03-30T15:10:00", "status": "pending"},
    }
    with patch(
        "bearmemori.core.triage._llm_call",
        return_value={"choices": [{"message": {"content": json.dumps(response_data)}}]},
    ):
        result = await run_triage(
            [{"role": "user", "content": "Remind me to pack my bag in 10 minutes"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
            memory_hint={"likely_category": "reminder", "confidence": "high"},
        )
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.REMINDER
    assert result.draft.title == "Pack bag"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_triage.py::test_triage_high_confidence_skips_should_save -v`
Expected: FAIL — current code checks `data.get("should_save", False)` which returns False when no should_save field is present.

**Step 3: Add the extraction-only prompt template**

In `bearmemori/core/triage.py`, add after the existing `_TRIAGE_SYSTEM_TEMPLATE` (after line 86):

```python
_EXTRACTION_SYSTEM_TEMPLATE = """\
You are a memory extraction agent. The following conversation contains \
information that should be saved as a long-term memory.

Current date and time: {current_time}
When the user mentions relative times (e.g. "in 10 minutes", "tomorrow", "next week"), \
use the current date and time above to compute the absolute ISO 8601 datetime for event_fields.

Extract the memory details from the conversation. You MUST respond with a \
single valid JSON object and nothing else. No explanation, no commentary, \
no markdown formatting.

Categories:
- "profile": Stable facts about the user (preferences, identity, relationships)
- "general": Non-time-bound useful information (prices, recommendations, facts)
- "event": Time-bound commitments, reminders, appointments
- "location": Places, addresses, venues the user mentions
- "task": Action items, to-dos
- "reminder": Triggered notifications with scheduling

Importance (1-10 integer):
- 1-3: Low importance (trivial facts, casual mentions)
- 4-6: Medium importance (useful information, general preferences)
- 7-8: High importance (key personal facts, significant events, strong preferences)
- 9-10: Critical importance (core identity, health/safety, major life events)

Respond with:
{{"category": "<category>", "title": "<short title>", \
"content": "<key information>", "tags": ["tag1", "tag2"], \
"importance": <1-10>, "event_fields": null}}

For events/tasks/reminders, set event_fields to:
{{"datetime": "ISO 8601", "status": "pending", "recurrence": null}}

IMPORTANT: Reminders and events should have importance 5-8 for reminders, \
6-9 for events/tasks.

The conversation may contain information spread across multiple messages. \
Synthesize the full conversation to extract the complete memory, not just \
the last message.
"""
```

**Step 4: Add confidence check logic in `run_triage()`**

In `run_triage()`, after building the `messages` list (after line 153), replace the LLM call and response handling block (lines 156-207) with:

```python
    high_confidence = (
        memory_hint is not None
        and memory_hint.get("confidence") == "high"
    )

    if high_confidence:
        extraction_prompt = _EXTRACTION_SYSTEM_TEMPLATE.format(current_time=current_time)
        extraction_messages = [
            {"role": "system", "content": extraction_prompt},
            {"role": "user", "content": f"Conversation:\n{conv_text}{hint_text}"},
        ]
        result = await _try_extraction(
            extraction_messages, llm_base_url, llm_api_key, llm_model,
            llm_max_tokens, triage_timeout,
        )
        if result is not None:
            return result
        # Fallback: retry with full triage prompt
        logger.info("High-confidence extraction failed, falling back to full triage")

    # Full triage path (also serves as fallback for failed extraction)
    return await _run_full_triage(
        messages, llm_base_url, llm_api_key, llm_model,
        llm_max_tokens, triage_timeout,
    )
```

Add two helper functions before `run_triage()`:

```python
async def _try_extraction(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout: float,
) -> TriageResult | None:
    """Attempt extraction-only triage. Returns None on failure."""
    try:
        response = await _llm_call(messages, base_url, api_key, model, max_tokens, timeout)
        message = response["choices"][0]["message"]
        raw = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        logger.debug("Extraction LLM raw output: %s", raw)
        data = _extract_from_response(raw, reasoning)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Extraction LLM returned unparseable output: %s | raw: %s", e, (raw if 'raw' in dir() else "")[:500])
        return None
    except httpx.HTTPError as e:
        logger.error("Extraction LLM call failed (%s): %s", type(e).__name__, e)
        return None

    return _build_draft(data, raw)


async def _run_full_triage(
    messages: list[dict],
    base_url: str,
    api_key: str,
    model: str,
    max_tokens: int,
    timeout: float,
) -> TriageResult:
    """Run the full triage prompt (includes should_save decision)."""
    try:
        response = await _llm_call(messages, base_url, api_key, model, max_tokens, timeout)
        message = response["choices"][0]["message"]
        raw = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""
        logger.info("Triage LLM full message keys: %s", list(message.keys()))
        if not raw:
            logger.warning("Triage LLM returned empty content. Full message: %s", message)
        logger.debug("Triage LLM raw output: %s", raw)
        logger.debug("Triage LLM reasoning output: %s", reasoning[:200] if reasoning else "")
        data = _extract_from_response(raw, reasoning)
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.warning("Triage LLM returned unparseable output: %s", e)
        return TriageResult(should_save=False, reason="extraction_failed")
    except httpx.HTTPError as e:
        logger.error("Triage LLM call failed (%s): %s", type(e).__name__, e)
        return TriageResult(should_save=False, reason="extraction_failed")

    if not data.get("should_save", False):
        logger.info("Triage decision: should_save=False (from LLM data: %s)", data)
        return TriageResult(should_save=False, reason="llm_decided_no")

    result = _build_draft(data, raw)
    if result is None:
        return TriageResult(should_save=False, reason="validation_failed")
    return result


def _build_draft(data: dict, raw: str) -> TriageResult | None:
    """Build a MemoryDraft from parsed LLM data. Returns None on validation failure."""
    try:
        event_fields = None
        if data.get("event_fields"):
            event_fields = EventFields(**data["event_fields"])

        importance = max(1, min(10, int(data.get("importance", 5))))

        draft = MemoryDraft(
            category=MemoryCategory(data["category"]),
            title=data["title"],
            content=data["content"],
            tags=data.get("tags", []),
            importance=importance,
            event_fields=event_fields,
        )
        logger.info(
            "Triage decision: should_save=True, category=%s, title=%s, importance=%d",
            draft.category, draft.title, draft.importance,
        )
        return TriageResult(should_save=True, draft=draft)
    except (ValueError, KeyError, ValidationError) as e:
        logger.warning("Triage produced invalid draft: %s | raw: %s", e, raw[:500])
        return None
```

**Step 5: Add `reason` field to `TriageResult`**

Update the `TriageResult` dataclass:

```python
@dataclass
class TriageResult:
    should_save: bool
    draft: MemoryDraft | None = None
    reason: str | None = None
```

**Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_triage.py -v`
Expected: All tests PASS including the new `test_triage_high_confidence_skips_should_save`.

**Step 7: Commit**

```bash
git add bearmemori/core/triage.py tests/test_triage.py
git commit -m "feat: add confidence-based extraction override in triage"
```

---

### Task 2: Add fallback from extraction to full triage

**Files:**
- Modify: `bearmemori/core/triage.py` (already modified in Task 1)
- Test: `tests/test_triage.py`

**Step 1: Write the failing test**

Add to `tests/test_triage.py`:

```python
@pytest.mark.asyncio
async def test_triage_high_confidence_falls_back_on_extraction_failure():
    """When extraction-only fails, should fall back to full triage prompt."""
    extraction_response = {"choices": [{"message": {"content": "not json at all"}}]}
    full_triage_response_data = {
        "should_save": True,
        "category": "reminder",
        "title": "Pack bag",
        "content": "Pack bag in 10 minutes",
        "tags": ["reminder"],
        "importance": 6,
        "event_fields": {"datetime": "2026-03-30T15:10:00", "status": "pending"},
    }
    full_triage_response = {
        "choices": [{"message": {"content": json.dumps(full_triage_response_data)}}]
    }

    call_count = 0
    async def mock_llm_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return extraction_response  # First call: extraction fails
        return full_triage_response  # Second call: full triage succeeds

    with patch("bearmemori.core.triage._llm_call", side_effect=mock_llm_call):
        result = await run_triage(
            [{"role": "user", "content": "Remind me to pack my bag in 10 minutes"}],
            llm_base_url="http://localhost:11434/v1",
            llm_api_key="test",
            llm_model="test",
            memory_hint={"likely_category": "reminder", "confidence": "high"},
        )
    assert call_count == 2  # Both extraction and full triage were called
    assert result.should_save is True
    assert result.draft is not None
    assert result.draft.category == MemoryCategory.REMINDER
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_triage.py::test_triage_high_confidence_falls_back_on_extraction_failure -v`
Expected: Should PASS if Task 1 was implemented correctly (the fallback logic is already in the code from Task 1). If it fails, debug the fallback path.

**Step 3: Run all tests**

Run: `uv run pytest tests/test_triage.py -v`
Expected: All PASS.

**Step 4: Commit**

```bash
git add tests/test_triage.py
git commit -m "test: add fallback test for extraction-to-full-triage path"
```

---

### Task 3: Harden the full triage prompt

**Files:**
- Modify: `bearmemori/core/triage.py:41-86` (the `_TRIAGE_SYSTEM_TEMPLATE`)
- Test: `tests/test_triage.py`

**Step 1: Write a test to verify the prompt content**

Add to `tests/test_triage.py`:

```python
def test_triage_prompt_contains_when_in_doubt_save():
    """The full triage prompt should bias toward saving."""
    from bearmemori.core.triage import _TRIAGE_SYSTEM_TEMPLATE
    assert "when in doubt" in _TRIAGE_SYSTEM_TEMPLATE.lower()
    assert "Be selective" not in _TRIAGE_SYSTEM_TEMPLATE


def test_triage_prompt_contains_multi_turn_guidance():
    """The full triage prompt should guide multi-turn synthesis."""
    from bearmemori.core.triage import _TRIAGE_SYSTEM_TEMPLATE
    assert "multiple messages" in _TRIAGE_SYSTEM_TEMPLATE


def test_triage_prompt_contains_mixed_topic_guidance():
    """The full triage prompt should guide mixed-topic focus."""
    from bearmemori.core.triage import _TRIAGE_SYSTEM_TEMPLATE
    assert "multiple unrelated topics" in _TRIAGE_SYSTEM_TEMPLATE
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_triage.py::test_triage_prompt_contains_when_in_doubt_save tests/test_triage.py::test_triage_prompt_contains_multi_turn_guidance tests/test_triage.py::test_triage_prompt_contains_mixed_topic_guidance -v`
Expected: FAIL — current prompt has "Be selective" and lacks the new guidance.

**Step 3: Update `_TRIAGE_SYSTEM_TEMPLATE`**

Replace lines 77-86 of `bearmemori/core/triage.py` (the IMPORTANT block and the "Be selective" section) with:

```python
IMPORTANT: Reminders and events are always worth saving. A reminder about a
future action (e.g., "pack my bag in 10 minutes") is valuable user
information - do NOT treat it as trivial. Set importance 5-8 for
reminders, 6-9 for events/tasks.

When in doubt, lean toward saving. It is better to save something \
the user can dismiss than to lose information they wanted kept.

The conversation may contain information spread across multiple messages. \
Synthesize the full conversation to extract the complete memory, not just \
the last message.

If the conversation covers multiple unrelated topics, focus on the most \
recent topic that contains memory-worthy information.

Save specific, actionable information. Skip only:
- Greetings or small talk
- Questions without answers
- Truly trivial information (e.g., casual mentions without context)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_triage.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add bearmemori/core/triage.py tests/test_triage.py
git commit -m "feat: harden triage prompt to bias toward saving"
```

---

### Task 4: Add reason field to API response

**Files:**
- Modify: `bearmemori/api/schemas.py:4-7`
- Modify: `bearmemori/api/routes.py:84-85`
- Test: `tests/test_triage_schema.py`

**Step 1: Write the failing test**

Add to `tests/test_triage_schema.py`:

```python
def test_triage_response_includes_reason_when_not_saved():
    """The triage API should return a reason when should_save is False."""
    from unittest.mock import patch, AsyncMock
    from fastapi.testclient import TestClient
    from bearmemori.core.triage import TriageResult

    # We need to test the route, so create a minimal app
    from bearmemori.api.routes import create_app
    from bearmemori.storage.database import MemoryDatabase
    from bearmemori.storage.vector_store import VectorStore
    from bearmemori.storage.pending_store import PendingStore

    db = MemoryDatabase(":memory:")
    vs = VectorStore.__new__(VectorStore)
    ps = PendingStore()

    app = create_app(
        db, vs, ps,
        llm_base_url="http://localhost/v1",
        llm_api_key="test",
        llm_model="test",
    )
    client = TestClient(app)

    with patch(
        "bearmemori.api.routes.run_triage",
        new_callable=AsyncMock,
        return_value=TriageResult(should_save=False, reason="llm_decided_no"),
    ):
        resp = client.post("/memory/triage", json={
            "conversation": [{"role": "user", "content": "hello"}],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["should_save"] is False
    assert data["reason"] == "llm_decided_no"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_triage_schema.py::test_triage_response_includes_reason_when_not_saved -v`
Expected: FAIL — current route returns `{"should_save": False}` without reason.

**Step 3: Update the route to pass through reason**

In `bearmemori/api/routes.py`, replace line 84-85:

```python
        if not result.should_save or result.draft is None:
            return {"should_save": False}
```

With:

```python
        if not result.should_save or result.draft is None:
            response = {"should_save": False}
            if result.reason:
                response["reason"] = result.reason
            return response
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_triage_schema.py -v`
Expected: All PASS.

**Step 5: Run the full test suite**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 6: Commit**

```bash
git add bearmemori/api/routes.py bearmemori/api/schemas.py bearmemori/core/triage.py tests/test_triage_schema.py
git commit -m "feat: add reason field to triage API response"
```

---

### Task 5: Final verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 2: Run linter**

Run: `uv run ruff check .`
Expected: No errors.

**Step 3: Run formatter**

Run: `uv run ruff format --check .`
Expected: No formatting issues, or run `uv run ruff format .` to fix.

**Step 4: Commit any formatting fixes**

```bash
git add -A
git commit -m "chore: fix formatting"
```
