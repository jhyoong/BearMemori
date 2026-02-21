"""Shared utility functions for the Core service."""

from datetime import datetime


def parse_db_datetime(dt_str: str | None) -> datetime | None:
    """Parse datetime string from database, handling 'Z' and '+00:00' formats."""
    if not dt_str:
        return None
    if "+" in dt_str and dt_str.endswith("Z"):
        dt_str = dt_str[:-1]
    elif dt_str.endswith("Z"):
        dt_str = dt_str.replace("Z", "+00:00")
    return datetime.fromisoformat(dt_str)
