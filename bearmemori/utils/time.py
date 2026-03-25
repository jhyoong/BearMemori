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
