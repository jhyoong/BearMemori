# /timezone Command Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `/timezone` command to the Telegram bot so users can view and set their timezone using UTC offsets or IANA timezone names.

**Architecture:** The command parses a UTC offset (e.g., `+8`) into an `Etc/GMT` IANA zone (with inverted sign per IANA convention), or accepts a raw IANA name. It calls the Core API PUT `/settings/{user_id}` endpoint via a new `update_settings` method on `CoreClient`.

**Tech Stack:** python-telegram-bot, zoneinfo (stdlib), httpx, pytest

---

### Task 1: Add `offset_to_iana` helper to tz_utils.py

**Files:**
- Modify: `telegram/tg_gateway/tz_utils.py`
- Test: `tests/test_telegram/test_tz_utils.py` (create)

**Step 1: Write the failing tests**

Create `tests/test_telegram/test_tz_utils.py`:

```python
"""Tests for timezone utility functions."""

import os
import sys

import pytest

telegram_dir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "telegram",
)
if telegram_dir not in sys.path:
    sys.path.insert(0, telegram_dir)

from tg_gateway.tz_utils import offset_to_iana


class TestOffsetToIana:
    def test_positive_offset(self):
        assert offset_to_iana("+8") == "Etc/GMT-8"

    def test_negative_offset(self):
        assert offset_to_iana("-5") == "Etc/GMT+5"

    def test_zero_offset(self):
        assert offset_to_iana("+0") == "Etc/GMT+0"

    def test_negative_zero(self):
        assert offset_to_iana("-0") == "Etc/GMT+0"

    def test_leading_zero(self):
        assert offset_to_iana("+08") == "Etc/GMT-8"

    def test_max_positive(self):
        assert offset_to_iana("+14") == "Etc/GMT-14"

    def test_max_negative(self):
        assert offset_to_iana("-12") == "Etc/GMT+12"

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            offset_to_iana("+15")

    def test_negative_out_of_range_raises(self):
        with pytest.raises(ValueError, match="out of range"):
            offset_to_iana("-13")

    def test_half_hour_rejected(self):
        with pytest.raises(ValueError, match="whole hours"):
            offset_to_iana("+5:30")

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            offset_to_iana("abc")

    def test_missing_sign(self):
        with pytest.raises(ValueError):
            offset_to_iana("8")
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram/test_tz_utils.py -v`
Expected: FAIL with ImportError (offset_to_iana does not exist)

**Step 3: Implement `offset_to_iana` in tz_utils.py**

Add to `telegram/tg_gateway/tz_utils.py` after the existing functions:

```python
def offset_to_iana(offset_str: str) -> str:
    """Convert a UTC offset string like '+8' or '-5' to an Etc/GMT IANA zone.

    IANA Etc/GMT zones use inverted signs: Etc/GMT-8 means UTC+8.
    Only whole-hour offsets are supported (UTC-12 to UTC+14).

    Args:
        offset_str: Offset string starting with '+' or '-' (e.g., '+8', '-5', '+08').

    Returns:
        IANA timezone name (e.g., 'Etc/GMT-8').

    Raises:
        ValueError: If the offset is invalid, out of range, or not a whole hour.
    """
    if not offset_str or offset_str[0] not in ("+", "-"):
        raise ValueError(
            f"Invalid offset '{offset_str}'. Must start with '+' or '-'."
        )

    sign = offset_str[0]
    rest = offset_str[1:]

    if ":" in rest:
        raise ValueError(
            f"Offset '{offset_str}' is not a whole hour. "
            f"For half-hour offsets, use the IANA name directly "
            f"(e.g., Asia/Kolkata)."
        )

    try:
        hours = int(rest)
    except ValueError:
        raise ValueError(f"Invalid offset '{offset_str}'. Use format like +8 or -5.")

    if sign == "-" and hours > 12:
        raise ValueError(f"Offset '{offset_str}' out of range (UTC-12 to UTC+14).")
    if sign == "+" and hours > 14:
        raise ValueError(f"Offset '{offset_str}' out of range (UTC-12 to UTC+14).")

    # IANA Etc/GMT uses inverted signs
    if hours == 0:
        return "Etc/GMT+0"
    if sign == "+":
        return f"Etc/GMT-{hours}"
    return f"Etc/GMT+{hours}"
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram/test_tz_utils.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telegram/tg_gateway/tz_utils.py tests/test_telegram/test_tz_utils.py
git commit -m "feat: add offset_to_iana helper for /timezone command"
```

---

### Task 2: Add `update_settings` to CoreClient

**Files:**
- Modify: `telegram/tg_gateway/core_client.py`
- Test: `tests/test_telegram/test_commands.py`

**Step 1: Write the failing test**

Add to `tests/test_telegram/test_commands.py`:

```python
class TestCoreClientUpdateSettings:
    @pytest.mark.asyncio
    async def test_update_settings_calls_put(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        from tg_gateway.core_client import CoreClient
        from shared_lib.schemas import UserSettingsUpdate

        client = CoreClient(base_url="http://localhost:8083")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.json.return_value = {
            "user_id": 12345,
            "timezone": "Etc/GMT-8",
            "language": "en",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-03-01T00:00:00Z",
        }

        with patch.object(client._client, "put", new_callable=AsyncMock, return_value=mock_response) as mock_put:
            result = await client.update_settings(12345, UserSettingsUpdate(timezone="Etc/GMT-8"))

        mock_put.assert_awaited_once_with(
            "/settings/12345",
            json={"timezone": "Etc/GMT-8"},
        )
        assert result.timezone == "Etc/GMT-8"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_telegram/test_commands.py::TestCoreClientUpdateSettings -v`
Expected: FAIL with AttributeError (update_settings does not exist)

**Step 3: Implement `update_settings` in core_client.py**

Add `UserSettingsUpdate` to the imports at the top of `telegram/tg_gateway/core_client.py`:

```python
from shared_lib.schemas import (
    ...
    UserSettingsResponse,
    UserSettingsUpdate,  # add this
    UserUpsert,
)
```

Add the method after `get_settings` (after line 350):

```python
    async def update_settings(
        self, user_id: int, data: UserSettingsUpdate
    ) -> UserSettingsResponse:
        """Update user settings."""
        try:
            response = await self._client.put(
                f"/settings/{user_id}",
                json=data.model_dump(mode="json", exclude_none=True),
            )
        except (ConnectError, TimeoutException) as e:
            logger.exception("Failed to connect to Core API")
            raise CoreUnavailableError(f"Core API unavailable: {e}") from e

        if not response.is_success:
            logger.error(
                f"Failed to update settings: {response.status_code} {response.text}"
            )
            raise CoreClientError(
                f"Failed to update settings: {response.status_code} {response.text}"
            )

        return UserSettingsResponse.model_validate(response.json())
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_telegram/test_commands.py::TestCoreClientUpdateSettings -v`
Expected: PASS

**Step 5: Commit**

```bash
git add telegram/tg_gateway/core_client.py tests/test_telegram/test_commands.py
git commit -m "feat: add update_settings method to CoreClient"
```

---

### Task 3: Add `timezone_command` handler

**Files:**
- Modify: `telegram/tg_gateway/handlers/command.py`
- Test: `tests/test_telegram/test_commands.py`

**Step 1: Write the failing tests**

Add to `tests/test_telegram/test_commands.py`:

```python
from shared_lib.schemas import UserSettingsResponse
from datetime import datetime, timezone


def _make_settings_response(tz: str = "UTC") -> UserSettingsResponse:
    return UserSettingsResponse(
        user_id=12345,
        timezone=tz,
        language="en",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )


class TestTimezoneCommand:
    @pytest.mark.asyncio
    async def test_no_args_shows_current_timezone(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone")
        core_client = AsyncMock()
        core_client.get_settings = AsyncMock(
            return_value=_make_settings_response("Etc/GMT-8")
        )
        context = _make_context(bot_data={"core_client": core_client})
        context.args = []

        await timezone_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "Etc/GMT-8" in reply
        assert "UTC+8" in reply

    @pytest.mark.asyncio
    async def test_set_positive_offset(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone +8")
        core_client = AsyncMock()
        core_client.update_settings = AsyncMock(
            return_value=_make_settings_response("Etc/GMT-8")
        )
        context = _make_context(bot_data={"core_client": core_client})
        context.args = ["+8"]

        await timezone_command(update, context)

        core_client.update_settings.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "updated" in reply.lower()
        assert "Etc/GMT-8" in reply

    @pytest.mark.asyncio
    async def test_set_negative_offset(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone -5")
        core_client = AsyncMock()
        core_client.update_settings = AsyncMock(
            return_value=_make_settings_response("Etc/GMT+5")
        )
        context = _make_context(bot_data={"core_client": core_client})
        context.args = ["-5"]

        await timezone_command(update, context)

        core_client.update_settings.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Etc/GMT+5" in reply

    @pytest.mark.asyncio
    async def test_set_iana_name_directly(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone Asia/Kolkata")
        core_client = AsyncMock()
        core_client.update_settings = AsyncMock(
            return_value=_make_settings_response("Asia/Kolkata")
        )
        context = _make_context(bot_data={"core_client": core_client})
        context.args = ["Asia/Kolkata"]

        await timezone_command(update, context)

        core_client.update_settings.assert_awaited_once()
        reply = update.message.reply_text.call_args[0][0]
        assert "Asia/Kolkata" in reply

    @pytest.mark.asyncio
    async def test_invalid_offset_shows_error(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone +99")
        core_client = AsyncMock()
        context = _make_context(bot_data={"core_client": core_client})
        context.args = ["+99"]

        await timezone_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "invalid" in reply.lower() or "error" in reply.lower()

    @pytest.mark.asyncio
    async def test_invalid_iana_name_shows_error(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone Fake/Zone")
        core_client = AsyncMock()
        context = _make_context(bot_data={"core_client": core_client})
        context.args = ["Fake/Zone"]

        await timezone_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "unknown" in reply.lower() or "invalid" in reply.lower()

    @pytest.mark.asyncio
    async def test_no_core_client(self):
        from tg_gateway.handlers.command import timezone_command

        update = _make_update(text="/timezone")
        context = _make_context(bot_data={})
        context.args = []

        await timezone_command(update, context)

        reply = update.message.reply_text.call_args[0][0]
        assert "Error" in reply
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_telegram/test_commands.py::TestTimezoneCommand -v`
Expected: FAIL with ImportError (timezone_command does not exist)

**Step 3: Implement `timezone_command`**

Add to the end of `telegram/tg_gateway/handlers/command.py`:

```python
async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """View or set the user's timezone.

    Usage:
        /timezone          - show current timezone
        /timezone +8       - set to UTC+8
        /timezone -5       - set to UTC-5
        /timezone Asia/Kolkata - set using IANA name

    Args:
        update: The Telegram update.
        context: The context with bot_data and args.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    from shared_lib.schemas import UserSettingsUpdate
    from tg_gateway.tz_utils import offset_to_iana

    user = update.effective_user
    if not user:
        await update.message.reply_text("Error: Could not identify user.")
        return

    core_client = context.bot_data.get("core_client")
    if not core_client:
        await update.message.reply_text("Error: Core client not available.")
        return

    args = context.args if context.args else []

    # No argument: show current timezone
    if not args:
        try:
            settings = await core_client.get_settings(user.id)
            tz_name = settings.timezone
            now_local = datetime.now(ZoneInfo(tz_name))
            local_time_str = now_local.strftime("%Y-%m-%d %H:%M")
            await update.message.reply_text(
                f"Your timezone is {tz_name}.\n"
                f"Local time: {local_time_str}"
            )
        except Exception:
            await update.message.reply_text("Failed to get timezone settings.")
        return

    arg = args[0]

    # Try as UTC offset first (starts with + or -)
    if arg[0] in ("+", "-"):
        try:
            tz_name = offset_to_iana(arg)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return
    else:
        # Try as raw IANA timezone name
        tz_name = arg
        try:
            ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, KeyError):
            await update.message.reply_text(
                f"Unknown timezone: {tz_name}. "
                f"Use a UTC offset like +8 or a valid IANA timezone name."
            )
            return

    # Save the timezone
    try:
        await core_client.update_settings(
            user.id, UserSettingsUpdate(timezone=tz_name)
        )
        now_local = datetime.now(ZoneInfo(tz_name))
        local_time_str = now_local.strftime("%Y-%m-%d %H:%M")
        await update.message.reply_text(
            f"Timezone updated to {tz_name}.\n"
            f"Local time: {local_time_str}"
        )
    except Exception:
        logger.exception("Failed to update timezone")
        await update.message.reply_text("Failed to update timezone settings.")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_telegram/test_commands.py::TestTimezoneCommand -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add telegram/tg_gateway/handlers/command.py tests/test_telegram/test_commands.py
git commit -m "feat: add /timezone command handler"
```

---

### Task 4: Register /timezone in main.py and update help text

**Files:**
- Modify: `telegram/tg_gateway/main.py:54-72` (command import and registration)
- Modify: `telegram/tg_gateway/main.py:187-195` (bot commands menu)
- Modify: `telegram/tg_gateway/handlers/command.py:28-33` (help text)
- Test: `tests/test_telegram/test_menu_commands.py` (verify registration)

**Step 1: Update the import in main.py**

In `telegram/tg_gateway/main.py`, add `timezone_command` to the import block at line 54-62:

```python
        from tg_gateway.handlers.command import (
            help_command,
            find_command,
            tasks_command,
            pinned_command,
            cancel_command,
            queue_command,
            status_command,
            timezone_command,
        )
```

**Step 2: Add the CommandHandler to the list at line 64-72**

```python
        command_handlers = [
            CommandHandler("help", help_command, filters=allowed_filter),
            CommandHandler("find", find_command, filters=allowed_filter),
            CommandHandler("tasks", tasks_command, filters=allowed_filter),
            CommandHandler("pinned", pinned_command, filters=allowed_filter),
            CommandHandler("cancel", cancel_command, filters=allowed_filter),
            CommandHandler("queue", queue_command, filters=allowed_filter),
            CommandHandler("status", status_command, filters=allowed_filter),
            CommandHandler("timezone", timezone_command, filters=allowed_filter),
        ]
```

**Step 3: Add to the bot commands menu at line 187-195**

```python
    commands = [
        BotCommand("help", "Show this help message"),
        BotCommand("find", "Search memories"),
        BotCommand("tasks", "List your tasks"),
        BotCommand("pinned", "Show pinned memories"),
        BotCommand("cancel", "Cancel current action"),
        BotCommand("queue", "Queue statistics (admin)"),
        BotCommand("status", "Your status and LLM health"),
        BotCommand("timezone", "View or set your timezone"),
    ]
```

**Step 4: Update help text in command.py**

Update the help_text in `telegram/tg_gateway/handlers/command.py` (lines 28-33):

```python
    help_text = """Available commands:
/help - Show this help message
/find <query> - Search memories
/tasks - List your tasks
/pinned - Show pinned memories
/timezone - View or set your timezone
/cancel - Cancel current action"""
```

**Step 5: Run the menu commands test to verify registration**

Run: `pytest tests/test_telegram/test_menu_commands.py -v`
Expected: PASS (or update the test if it checks for exact command count)

**Step 6: Run full telegram test suite**

Run: `pytest tests/test_telegram/ -v`
Expected: All PASS

**Step 7: Commit**

```bash
git add telegram/tg_gateway/main.py telegram/tg_gateway/handlers/command.py
git commit -m "feat: register /timezone command and update help text"
```
