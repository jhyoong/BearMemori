# /timezone Command Design

## Problem

The user's timezone defaults to UTC. When the user says "remind me at 10pm", the LLM resolves it as 10pm UTC rather than 10pm in the user's actual local timezone. Relative time references like "in 10 minutes" work correctly because they are timezone-agnostic.

Users need a way to set their timezone through the Telegram bot.

## Design

### Usage

- `/timezone` -- display current timezone setting and local time
- `/timezone +8` -- set timezone to UTC+8 (stored as `Etc/GMT-8`)
- `/timezone -5` -- set timezone to UTC-5 (stored as `Etc/GMT+5`)
- `/timezone Asia/Kolkata` -- set timezone directly using IANA name (fallback for half-hour offsets)

### Input Parsing

1. No argument: show current setting
2. Starts with `+` or `-`: parse as UTC offset
   - Accept `+N`, `-N` (whole hours only)
   - Validate range: UTC-12 to UTC+14
   - Reject half-hour offsets with a message suggesting IANA name input
   - Map to `Etc/GMT` zone with inverted sign (IANA convention: `Etc/GMT-8` = UTC+8)
3. Otherwise: treat as raw IANA timezone name, validate with `ZoneInfo()`

### Response Messages

- View: `"Your timezone is Etc/GMT-8 (UTC+8). Local time: 2026-03-01 20:45"`
- Update: `"Timezone updated to Etc/GMT-8 (UTC+8). Local time: 2026-03-01 20:45"`
- Invalid offset: `"Invalid offset. Use format like +8 or -5 (whole hours only). For half-hour offsets, use the IANA name directly (e.g., /timezone Asia/Kolkata)."`
- Invalid IANA name: `"Unknown timezone: <input>. Use a UTC offset like +8 or a valid IANA timezone name."`

## Components to Modify

### 1. `telegram/tg_gateway/tz_utils.py`

Add `offset_to_iana(offset_str: str) -> str` helper:
- Parse the offset string, validate range and whole-hour constraint
- Invert sign and return `Etc/GMT{inverted_sign}{hours}`
- Verify result with `ZoneInfo()` before returning

Add `format_tz_display(tz_name: str) -> str` helper:
- Return a human-readable string like `"Etc/GMT-8 (UTC+8)"`

### 2. `telegram/tg_gateway/core_client.py`

Add `update_settings(user_id: int, data: UserSettingsUpdate) -> UserSettingsResponse`:
- PUT to `/settings/{user_id}` with JSON body
- Return parsed `UserSettingsResponse`

### 3. `telegram/tg_gateway/handlers/command.py`

Add `timezone_command(update, context)`:
- Parse `context.args` for the offset/timezone argument
- No args: fetch and display current timezone + local time
- With args: validate, convert, save via `core_client.update_settings()`, confirm

### 4. `telegram/tg_gateway/main.py`

- Add `CommandHandler("timezone", timezone_command, filters=allowed_filter)` to handler list
- Add `BotCommand("timezone", "View or set your timezone")` to bot commands menu
