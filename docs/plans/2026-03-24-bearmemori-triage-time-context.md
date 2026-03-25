# BearMemori Triage Time Context

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give BearMemori's triage LLM the current date/time so it can compute correct `event_datetime` values for relative time expressions like "in 10 minutes," instead of hallucinating dates from training data.

**Architecture:** The `TriageRequest` schema accepts an optional `current_time` field (already sent by teleBearAI after the companion plan is applied). The triage system prompt is augmented with this timestamp. If `current_time` is not provided, BearMemori generates it server-side as a fallback. A `USER_TIMEZONE` config option is added for this fallback and for the scheduler.

**Tech Stack:** Python `zoneinfo` (stdlib), Pydantic, FastAPI, existing BearMemori codebase.

**Repository:** `https://github.com/jhyoong/BearMemori.git` (changes target the BearMemori codebase, not teleBearAI)

---

### Task 1: Add USER_TIMEZONE to BearMemori config

**Files:**
- Modify: `bearmemori/config.py`
- Modify: `.env.bearmemori.example` (in the teleBearAI repo, for documentation)

**Step 1: Write the failing test**

Create `tests/test_config_timezone.py`:

```python
"""Tests for USER_TIMEZONE config field."""

import os
from unittest.mock import patch


def test_settings_has_user_timezone_field():
    """Settings model should have a user_timezone field."""
    from bearmemori.config import Settings

    fields = Settings.model_fields
    assert "user_timezone" in fields, (
        f"Settings should have user_timezone field, has: {list(fields.keys())}"
    )


def test_user_timezone_defaults_to_utc():
    """USER_TIMEZONE defaults to UTC when not set."""
    with patch.dict(os.environ, {
        "TELEGRAM_BOT_TOKEN": "test",
        "TELEGRAM_ALLOWED_USER_ID": "123",
    }, clear=True):
        from bearmemori.config import Settings

        settings = Settings()
        assert settings.user_timezone == "UTC"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_timezone.py -v`
Expected: FAIL — `user_timezone` not in Settings

**Step 3: Add user_timezone to Settings**

In `bearmemori/config.py`, add the field to the `Settings` class:

```python
    user_timezone: str = "UTC"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_timezone.py -v`
Expected: PASS

**Step 5: Update .env.bearmemori.example in teleBearAI repo**

Add after the `WEBAPP_SECURE_COOKIE` line:

```
# User timezone (IANA format, e.g. Asia/Singapore, America/New_York)
# Used as fallback when triage requests don't include current_time
# Also used by the reminder scheduler for time comparisons
# Defaults to UTC if not set
USER_TIMEZONE=UTC
```

**Step 6: Commit**

```bash
git add bearmemori/config.py tests/test_config_timezone.py
git commit -m "feat: add USER_TIMEZONE config field (defaults to UTC)"
```

---

### Task 2: Accept current_time in TriageRequest schema

**Files:**
- Modify: `bearmemori/api/schemas.py`

**Step 1: Write the failing test**

Create `tests/test_triage_schema.py`:

```python
"""Tests for TriageRequest schema accepting current_time."""

from bearmemori.api.schemas import TriageRequest


def test_triage_request_accepts_current_time():
    """TriageRequest should accept an optional current_time field."""
    req = TriageRequest(
        conversation=[{"role": "user", "content": "hello"}],
        current_time="Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)",
    )
    assert req.current_time == "Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)"


def test_triage_request_current_time_defaults_to_none():
    """current_time should default to None when not provided."""
    req = TriageRequest(
        conversation=[{"role": "user", "content": "hello"}],
    )
    assert req.current_time is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_triage_schema.py -v`
Expected: FAIL — TriageRequest does not accept current_time

**Step 3: Add current_time to TriageRequest**

In `bearmemori/api/schemas.py`, update the `TriageRequest` class:

```python
class TriageRequest(BaseModel):
    conversation: list[dict] = Field(min_length=1)
    memory_hint: dict | None = None
    current_time: str | None = None
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_triage_schema.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add bearmemori/api/schemas.py tests/test_triage_schema.py
git commit -m "feat: accept optional current_time in TriageRequest"
```

---

### Task 3: Inject current time into triage system prompt

**Files:**
- Modify: `bearmemori/core/triage.py`

**Step 1: Write the failing test**

Create `tests/test_triage_time.py`:

```python
"""Tests for current_time injection in triage prompt."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from bearmemori.core.triage import run_triage


@pytest.mark.asyncio
async def test_triage_includes_current_time_in_prompt():
    """When current_time is provided, it should appear in the LLM messages."""
    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps({"should_save": False}),
            }
        }]
    }

    with patch("bearmemori.core.triage._llm_call", new_callable=AsyncMock, return_value=mock_response) as mock_call:
        await run_triage(
            conversation=[{"role": "user", "content": "Remind me in 10 minutes"}],
            llm_base_url="http://fake",
            llm_api_key="key",
            llm_model="model",
            current_time="Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)",
        )

        messages = mock_call.call_args[0][0]
        system_msg = messages[0]["content"]
        assert "Monday, March 24, 2026, 07:33 PM +0800" in system_msg, (
            f"System prompt should contain current_time, got:\n{system_msg}"
        )


@pytest.mark.asyncio
async def test_triage_generates_fallback_time_when_not_provided():
    """When current_time is None, triage should generate a server-side time."""
    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps({"should_save": False}),
            }
        }]
    }

    with patch("bearmemori.core.triage._llm_call", new_callable=AsyncMock, return_value=mock_response) as mock_call:
        await run_triage(
            conversation=[{"role": "user", "content": "Remind me tomorrow"}],
            llm_base_url="http://fake",
            llm_api_key="key",
            llm_model="model",
            current_time=None,
        )

        messages = mock_call.call_args[0][0]
        system_msg = messages[0]["content"]
        assert "Current date and time:" in system_msg, (
            f"System prompt should contain fallback time, got:\n{system_msg}"
        )
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_triage_time.py -v`
Expected: FAIL — `run_triage` does not accept `current_time` parameter

**Step 3: Update run_triage to accept and inject current_time**

In `bearmemori/core/triage.py`:

1. Add imports at the top:

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
```

2. Add a helper function after the existing `TRIAGE_SYSTEM_PROMPT`:

```python
def _get_server_time(user_timezone: str = "UTC") -> str:
    """Generate a current time string server-side as fallback."""
    now_utc = datetime.now(timezone.utc)
    try:
        tz = ZoneInfo(user_timezone)
    except (KeyError, Exception):
        tz = timezone.utc
        user_timezone = "UTC"
    now_local = now_utc.astimezone(tz)
    tz_label = user_timezone if user_timezone != "UTC" else "UTC"
    return now_local.strftime(f"%A, %B %d, %Y, %I:%M %p %z ({tz_label})")
```

3. Update `TRIAGE_SYSTEM_PROMPT` — add a `{current_time}` placeholder. Change it from a plain string to a function:

Replace the `TRIAGE_SYSTEM_PROMPT` constant and update `run_triage`:

```python
_TRIAGE_SYSTEM_TEMPLATE = """\
/no_think
You are a memory triage agent. Given a conversation, decide if any information \
is worth saving as a long-term memory.

Current date and time: {current_time}

Categories:
- "profile": Stable facts about the user (preferences, identity, relationships)
- "general": Non-time-bound useful information (prices, recommendations, facts)
- "event": Time-bound commitments, reminders, appointments
- "location": Places, addresses, venues the user mentions
- "task": Action items, to-dos
- "reminder": Triggered notifications with scheduling

You MUST respond with a single valid JSON object and nothing else. No explanation, \
no commentary, no markdown formatting.

If the conversation contains memory-worthy information:
{{"should_save": true, "category": "<category>", "title": "<short title>", \
"content": "<key information>", "tags": ["tag1", "tag2"], "event_fields": null}}

For events/tasks/reminders, set event_fields to:
{{"datetime": "ISO 8601", "status": "pending", "recurrence": null}}
The datetime MUST be an absolute ISO 8601 timestamp calculated from the current \
date and time above. For relative expressions like "in 10 minutes" or "tomorrow \
at 3pm", compute the exact datetime. NEVER guess or use placeholder dates.

If nothing is worth saving:
{{"should_save": false}}

Be selective. Only save genuinely useful, specific information. Do not save:
- Greetings or small talk
- Questions without answers
- Temporary or trivial information
"""

# Keep the old name as an alias for backward compatibility in tests
TRIAGE_SYSTEM_PROMPT = _TRIAGE_SYSTEM_TEMPLATE.format(current_time="(not provided)")
```

4. Update `run_triage` signature and body to accept `current_time` and `user_timezone`:

```python
async def run_triage(
    conversation: list[dict],
    llm_base_url: str,
    llm_api_key: str,
    llm_model: str,
    llm_max_tokens: int = 4096,
    memory_hint: dict | None = None,
    current_time: str | None = None,
    user_timezone: str = "UTC",
) -> TriageResult:
    if not current_time:
        current_time = _get_server_time(user_timezone)

    system_prompt = _TRIAGE_SYSTEM_TEMPLATE.format(current_time=current_time)

    hint_text = ""
    if memory_hint:
        hint_text = f"\n\nMemory hint from chatbot: {json.dumps(memory_hint)}"

    # ... rest of the function unchanged, except replace TRIAGE_SYSTEM_PROMPT
    # with the local system_prompt variable in the messages list:

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Conversation:\n{conv_text}{hint_text}"},
    ]
    # ... rest unchanged
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_triage_time.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add bearmemori/core/triage.py tests/test_triage_time.py
git commit -m "feat: inject current_time into triage system prompt"
```

---

### Task 4: Wire current_time through the API route

**Files:**
- Modify: `bearmemori/api/routes.py`

**Step 1: Write the failing test**

Create `tests/test_routes_triage_time.py`:

```python
"""Tests for current_time passthrough in triage route."""

import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from bearmemori.api.routes import create_app


@pytest.fixture
def client():
    db = MagicMock()
    vector_store = MagicMock()
    pending_store = MagicMock()
    app = create_app(
        db=db,
        vector_store=vector_store,
        pending_store=pending_store,
        llm_base_url="http://fake",
        llm_api_key="key",
        llm_model="model",
    )
    return TestClient(app)


def test_triage_route_passes_current_time(client):
    """POST /memory/triage should forward current_time to run_triage."""
    with patch("bearmemori.api.routes.run_triage", new_callable=AsyncMock) as mock_triage:
        from bearmemori.core.triage import TriageResult

        mock_triage.return_value = TriageResult(should_save=False)

        response = client.post("/memory/triage", json={
            "conversation": [{"role": "user", "content": "Remind me in 10 minutes"}],
            "current_time": "Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)",
        })

        assert response.status_code == 200
        call_kwargs = mock_triage.call_args.kwargs
        assert call_kwargs.get("current_time") == "Monday, March 24, 2026, 07:33 PM +0800 (Asia/Singapore)"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_routes_triage_time.py -v`
Expected: FAIL — `current_time` not forwarded

**Step 3: Update the triage route to pass current_time**

In `bearmemori/api/routes.py`, update the `/memory/triage` handler:

```python
    @app.post("/memory/triage")
    async def triage_conversation(request: TriageRequest):
        result = await run_triage(
            request.conversation,
            llm_base_url=llm_base_url,
            llm_api_key=llm_api_key,
            llm_model=llm_model,
            llm_max_tokens=llm_max_tokens,
            memory_hint=request.memory_hint,
            current_time=request.current_time,
        )
        # ... rest unchanged
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_routes_triage_time.py -v`
Expected: PASS

**Step 5: Run full test suite**

Run: `pytest tests/ -v`
Expected: PASS

**Step 6: Commit**

```bash
git add bearmemori/api/routes.py tests/test_routes_triage_time.py
git commit -m "feat: forward current_time from triage route to run_triage"
```

---

### Task 5: Add USER_TIMEZONE to .env.bearmemori and documentation

**Files:**
- Modify: `.env.bearmemori` (user's actual BearMemori env — in teleBearAI repo)
- Modify: `.env.bearmemori.example` (already done in Task 1)

**Step 1: Add USER_TIMEZONE to .env.bearmemori**

Add at the end of `.env.bearmemori`:

```
# User timezone (IANA format)
USER_TIMEZONE=Asia/Singapore
```

**Step 2: Rebuild and test manually**

Run:
```bash
docker compose build bearmemori
docker compose up -d bearmemori
docker compose logs --tail 20 bearmemori
```

Expected: BearMemori starts cleanly, scheduler log shows startup.

**Step 3: Send a test reminder via Telegram**

Send "Remind me in 5 minutes to check the logs" via Telegram. After saving, check the DB:

```bash
docker exec $(docker compose ps -q bearmemori) python3 -c "
import sqlite3
conn = sqlite3.connect('/data/bearmemori.db')
cursor = conn.cursor()
cursor.execute(\"SELECT id, event_datetime, created_at FROM memories WHERE category='reminder' ORDER BY created_at DESC LIMIT 1\")
print(cursor.fetchone())
conn.close()
"
```

Expected: `event_datetime` should be approximately 5 minutes after `created_at`, NOT a date in 2024.

**Step 4: Commit (env example only)**

```bash
git add .env.bearmemori.example
git commit -m "docs: add USER_TIMEZONE to BearMemori env example"
```

Note: Do NOT commit `.env.bearmemori` itself — it contains secrets.
