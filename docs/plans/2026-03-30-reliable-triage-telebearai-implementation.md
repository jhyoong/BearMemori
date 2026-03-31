# telebearAI Smart Conversation Windowing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the fixed 10-message triage window in telebearAI with smart windowing that sends only messages since the last triage trigger, reducing context noise for the BearMemori triage LLM.

**Architecture:** Track the last triage trigger index per chat_id in the context manager. When triage is triggered, slice the conversation from that index instead of using a fixed window. Cap at 10 messages.

**Tech Stack:** Python 3.12+, python-telegram-bot, pytest

**Working directory:** `/Users/macminijh/projects/telebearAI`

---

### Task 1: Add last triage index tracking to context manager

**Files:**
- Modify: `bot/context_manager.py`
- Test: `tests/test_context_manager.py`

**Step 1: Write the failing tests**

Add to `tests/test_context_manager.py`:

```python
from bot.context_manager import (
    get_last_triage_index,
    set_last_triage_index,
    clear_history,
)


class TestTriageIndex:
    """Tests for triage index tracking."""

    def test_get_last_triage_index_default_is_none(self):
        chat_id = 88888
        clear_history(chat_id)
        assert get_last_triage_index(chat_id) is None

    def test_set_and_get_last_triage_index(self):
        chat_id = 88887
        clear_history(chat_id)
        set_last_triage_index(chat_id, 5)
        assert get_last_triage_index(chat_id) == 5

    def test_clear_history_resets_triage_index(self):
        chat_id = 88886
        clear_history(chat_id)
        set_last_triage_index(chat_id, 3)
        clear_history(chat_id)
        assert get_last_triage_index(chat_id) is None

    def test_set_triage_index_updates_existing(self):
        chat_id = 88885
        clear_history(chat_id)
        set_last_triage_index(chat_id, 2)
        set_last_triage_index(chat_id, 7)
        assert get_last_triage_index(chat_id) == 7
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_context_manager.py::TestTriageIndex -v`
Expected: FAIL — `get_last_triage_index` and `set_last_triage_index` don't exist.

**Step 3: Implement triage index tracking**

In `bot/context_manager.py`, add a new module-level dict and two functions:

```python
_last_triage_indices: dict[int, int | None] = {}


def get_last_triage_index(chat_id: int) -> int | None:
    return _last_triage_indices.get(chat_id)


def set_last_triage_index(chat_id: int, index: int) -> None:
    _last_triage_indices[chat_id] = index
```

Also update `clear_history()` to reset the triage index. Add this line inside `clear_history()`, before the `return`:

```python
    _last_triage_indices.pop(chat_id, None)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_context_manager.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add bot/context_manager.py tests/test_context_manager.py
git commit -m "feat: add last triage index tracking to context manager"
```

---

### Task 2: Add triage window calculation helper

**Files:**
- Modify: `bot/main_agent.py`
- Test: `tests/test_main_agent.py`

**Step 1: Write the failing tests**

Add to `tests/test_main_agent.py`:

```python
class TestTriageWindow:
    """Tests for smart conversation windowing."""

    def test_window_no_previous_triage_uses_last_n(self):
        """Without a previous triage index, use last MEMORY_TRIAGE_WINDOW messages."""
        from bot.main_agent import _get_triage_window

        history = [{"role": "system", "content": "sys"}] + [
            {"role": "user", "content": f"msg {i}"} for i in range(15)
        ]
        # No previous triage index (None)
        result = _get_triage_window(history, last_triage_index=None)
        # Should return last 10 user/assistant messages (skipping system)
        assert len(result) <= 10
        assert all(m.get("role") in ("user", "assistant") for m in result)

    def test_window_with_previous_triage_slices_from_index(self):
        """With a previous triage index, only include messages after it."""
        from bot.main_agent import _get_triage_window

        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "trip to tokyo"},       # index 1
            {"role": "assistant", "content": "noted tokyo"},     # index 2
            {"role": "user", "content": "what hotel?"},          # index 3
            {"role": "assistant", "content": "which hotel?"},    # index 4
            {"role": "user", "content": "park hyatt"},           # index 5
            {"role": "assistant", "content": "noted park hyatt"},# index 6
        ]
        # Last triage was at index 2 (assistant response about tokyo)
        result = _get_triage_window(history, last_triage_index=2)
        # Should only include messages after index 2
        assert len(result) == 4
        assert result[0]["content"] == "what hotel?"
        assert result[-1]["content"] == "noted park hyatt"

    def test_window_caps_at_max(self):
        """Window should never exceed MEMORY_TRIAGE_WINDOW messages."""
        from bot.main_agent import _get_triage_window

        history = [{"role": "system", "content": "sys"}] + [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(20)
        ]
        # Last triage was at index 1 (very early), so many messages since
        result = _get_triage_window(history, last_triage_index=1)
        assert len(result) <= 10

    def test_window_filters_non_user_assistant_roles(self):
        """Window should only include user and assistant messages."""
        from bot.main_agent import _get_triage_window

        history = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "search something"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "search results", "tool_call_id": "1"},
            {"role": "assistant", "content": "here are results"},
            {"role": "user", "content": "remind me to review"},
            {"role": "assistant", "content": "will do"},
        ]
        result = _get_triage_window(history, last_triage_index=None)
        assert all(m.get("role") in ("user", "assistant") for m in result)
        # tool messages should be excluded
        assert not any(m.get("role") == "tool" for m in result)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_main_agent.py::TestTriageWindow -v`
Expected: FAIL — `_get_triage_window` doesn't exist.

**Step 3: Implement `_get_triage_window`**

Add to `bot/main_agent.py`, after the existing imports:

```python
from bot.constants import MEMORY_TRIAGE_WINDOW
from bot.context_manager import get_last_triage_index, set_last_triage_index
```

Note: `MEMORY_TRIAGE_WINDOW` is already imported. Add `get_last_triage_index` and `set_last_triage_index` to the existing `context_manager` import line.

Add the helper function (before `_trigger_memory_triage`):

```python
def _get_triage_window(
    history: list[dict], last_triage_index: int | None
) -> list[dict]:
    """Get the conversation window for triage.

    If there's a previous triage index, return messages after that index.
    Otherwise, return the last MEMORY_TRIAGE_WINDOW messages.
    Filters to only user and assistant messages. Caps at MEMORY_TRIAGE_WINDOW.
    """
    start = (last_triage_index or 0) + 1 if last_triage_index is not None else 0
    candidates = [
        m for m in history[start:]
        if m.get("role") in ("user", "assistant")
    ]
    return candidates[-MEMORY_TRIAGE_WINDOW:]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_main_agent.py::TestTriageWindow -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add bot/main_agent.py tests/test_main_agent.py
git commit -m "feat: add smart triage window calculation helper"
```

---

### Task 3: Wire smart windowing into triage trigger

**Files:**
- Modify: `bot/main_agent.py:74-152` (`_trigger_memory_triage` and its call site)

**Step 1: Write the failing test**

Add to `tests/test_main_agent.py`:

```python
class TestTriageWindowIntegration:
    """Tests that handle_message uses smart windowing for triage."""

    @pytest.mark.asyncio
    async def test_triage_uses_smart_window(self, clean_history):
        """Triage should use _get_triage_window instead of fixed last-N."""
        from bot.main_agent import handle_message
        from bot.context_manager import set_last_triage_index, get_last_triage_index

        chat_id = clean_history

        # Simulate: first message was already triaged
        # We need to set up history as if a prior conversation happened
        from bot.context_manager import append_message, get_history
        history = get_history(chat_id)
        history.append({"role": "system", "content": "system prompt"})
        append_message(chat_id, {"role": "user", "content": "trip to tokyo"})
        append_message(chat_id, {"role": "assistant", "content": '{"message": "noted", "intent_state": "resolved", "memory_hint": null}'})
        # Mark that triage happened at index 2 (the assistant response)
        set_last_triage_index(chat_id, 2)

        # Now the user sends a new message that triggers triage
        envelope_response = '{"message": "will save", "intent_state": "resolved", "memory_hint": {"likely_category": "reminder", "confidence": "high"}}'
        response = {"choices": [{"message": {"content": envelope_response}}]}

        triage_payload_captured = {}

        async def mock_memory_post(url, json=None, **kwargs):
            if "/memory/triage" in url:
                triage_payload_captured.update(json)
            mock_resp = AsyncMock()
            mock_resp.raise_for_status = lambda: None
            mock_resp.json.return_value = {"should_save": False}
            return mock_resp

        with patch("bot.main_agent.chat_completion", new_callable=AsyncMock, return_value=response):
            with patch("bot.main_agent._fetch_memory_context", new_callable=AsyncMock, return_value=""):
                with patch("bot.main_agent.memory_post", side_effect=mock_memory_post):
                    with patch("bot.main_agent.MEMORY_SERVICE_URL", "http://localhost:5123"):
                        await handle_message(chat_id, "remind me to pack", memory_confirmation_callback=AsyncMock())

        # The triage conversation should NOT include "trip to tokyo" (index 1-2)
        conv = triage_payload_captured.get("conversation", [])
        contents = [m["content"] for m in conv]
        assert "trip to tokyo" not in contents
        assert any("remind me to pack" in c for c in contents)

        # Last triage index should be updated
        new_index = get_last_triage_index(chat_id)
        assert new_index is not None
        assert new_index > 2
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_main_agent.py::TestTriageWindowIntegration -v`
Expected: FAIL — current code uses `conversation[-MEMORY_TRIAGE_WINDOW:]` instead of smart windowing.

**Step 3: Update `_trigger_memory_triage` to use smart windowing**

In `bot/main_agent.py`, update `_trigger_memory_triage` signature to accept `chat_id` for index tracking (it already does), and replace the conversation building logic.

Replace lines 96-104 (the triage conversation building):

```python
    # Build triage payload
    triage_conversation = [
        {
            "role": m.get("role", ""),
            "content": _text_only(m.get("content", "")),
        }
        for m in conversation[-MEMORY_TRIAGE_WINDOW:]
        if m.get("role") in ("user", "assistant")
    ]
```

With:

```python
    # Build triage payload with smart windowing
    last_triage_idx = get_last_triage_index(chat_id)
    windowed = _get_triage_window(conversation, last_triage_idx)
    triage_conversation = [
        {
            "role": m.get("role", ""),
            "content": _text_only(m.get("content", "")),
        }
        for m in windowed
    ]
```

Also, after the triage call succeeds (after line 147 `return data`), update the triage index. Replace the end of the try block:

```python
        # Update last triage index to current end of conversation
        set_last_triage_index(chat_id, len(conversation) - 1)

        if (
            data.get("should_save")
            and data.get("pending_id")
            and memory_confirmation_callback
        ):
            await memory_confirmation_callback(
                chat_id, data["pending_id"], data.get("draft", {})
            )
        return data
```

Update the import at the top of `bot/main_agent.py` to include the new functions:

```python
from bot.context_manager import get_history, append_message, trim_history, get_last_triage_index, set_last_triage_index
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_main_agent.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add bot/main_agent.py tests/test_main_agent.py
git commit -m "feat: wire smart conversation windowing into triage trigger"
```

---

### Task 4: Log triage reason from BearMemori response

**Files:**
- Modify: `bot/main_agent.py:132-137` (the triage response logging)

**Step 1: Update the logging**

In `bot/main_agent.py`, update the triage response logging (around line 132) to include the reason field:

```python
        logger.info(
            "Memory triage response: should_save=%s, pending_id=%s, reason=%s, draft=%s",
            data.get("should_save"),
            data.get("pending_id"),
            data.get("reason"),
            data.get("draft"),
        )
```

**Step 2: Run all tests**

Run: `uv run pytest -v`
Expected: All PASS.

**Step 3: Commit**

```bash
git add bot/main_agent.py
git commit -m "feat: log triage reason from BearMemori response"
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
