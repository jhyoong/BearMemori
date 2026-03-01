"""Timezone conversion utilities for the Telegram gateway.

All datetimes stored in the database are UTC. These helpers convert
between the user's local timezone and UTC at the input/display boundaries.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def user_now(tz_name: str) -> datetime:
    """Return the current time in the user's timezone (tz-aware)."""
    return datetime.now(ZoneInfo(tz_name))


def to_utc(dt: datetime, tz_name: str) -> datetime:
    """Convert a naive or tz-aware datetime to UTC.

    If dt is naive, assume it's in the user's timezone.
    If dt is already tz-aware, just convert to UTC.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(timezone.utc)


def format_for_user(dt: datetime, tz_name: str) -> str:
    """Format a UTC datetime for display in the user's timezone."""
    user_dt = dt.astimezone(ZoneInfo(tz_name))
    return user_dt.strftime("%Y-%m-%d %H:%M")


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
