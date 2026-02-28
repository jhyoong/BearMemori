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
