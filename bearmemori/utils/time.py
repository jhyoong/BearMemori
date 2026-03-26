from datetime import UTC, datetime
from zoneinfo import ZoneInfo


def get_server_time(user_timezone: str = "UTC") -> str:
    """Generate a human-readable current time string."""
    now_utc = datetime.now(UTC)
    try:
        tz = ZoneInfo(user_timezone)
    except KeyError:
        tz = UTC
        user_timezone = "UTC"
    now_local = now_utc.astimezone(tz)
    tz_label = user_timezone if user_timezone != "UTC" else "UTC"
    return now_local.strftime(f"%A, %B %d, %Y, %I:%M %p %z ({tz_label})")


def utc_to_local_iso(utc_iso: str, user_timezone: str = "UTC") -> str:
    """Convert a UTC ISO 8601 string to local timezone ISO string for display."""
    try:
        parsed = datetime.fromisoformat(utc_iso)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        tz = ZoneInfo(user_timezone)
        local = parsed.astimezone(tz)
        return local.isoformat()
    except (ValueError, KeyError):
        return utc_iso
