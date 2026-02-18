"""Settings router with upsert pattern."""

import logging
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Depends

from core_svc.audit import log_audit
from core_svc.database import get_db
from shared_lib.schemas import UserSettingsResponse, UserSettingsUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


def parse_db_datetime(dt_str: str | None) -> datetime | None:
    """Parse datetime string from database, handling both 'Z' and '+00:00' formats."""
    if not dt_str:
        return None
    # Handle edge case: string ending with both timezone offset and 'Z' (e.g., '+00:00Z')
    if '+' in dt_str and dt_str.endswith('Z'):
        dt_str = dt_str[:-1]  # Remove trailing 'Z'
    # Replace 'Z' with '+00:00' for ISO parsing
    elif dt_str.endswith('Z'):
        dt_str = dt_str.replace('Z', '+00:00')
    return datetime.fromisoformat(dt_str)


@router.get("/{user_id}", response_model=UserSettingsResponse)
async def get_user_settings(
    user_id: int,
    db: aiosqlite.Connection = Depends(get_db),
) -> UserSettingsResponse:
    """
    Fetch user settings from user_settings table.

    - If not found: return defaults (timezone="UTC", language="en")
    - Return: UserSettingsResponse
    """
    # Fetch user settings
    cursor = await db.execute(
        "SELECT * FROM user_settings WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()

    # If not found, return defaults
    if row is None:
        now = datetime.now(timezone.utc)
        return UserSettingsResponse(
            user_id=user_id,
            timezone="UTC",
            language="en",
            created_at=now,
            updated_at=now,
        )

    # Return existing settings
    return UserSettingsResponse(
        user_id=row["user_id"],
        timezone=row["timezone"],
        language=row["language"],
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )


@router.put("/{user_id}", response_model=UserSettingsResponse)
async def update_user_settings(
    user_id: int,
    settings_update: UserSettingsUpdate,
    db: aiosqlite.Connection = Depends(get_db),
) -> UserSettingsResponse:
    """
    Update or insert user settings using upsert pattern.

    - Accept: UserSettingsUpdate body
    - Use INSERT OR REPLACE pattern to upsert settings
    - Always update updated_at = now
    - Call log_audit(db, "user_settings", user_id, "updated", f"user:{user_id}")
    - Return: UserSettingsResponse
    """
    # Fetch existing settings to determine if this is an insert or update
    cursor = await db.execute(
        "SELECT * FROM user_settings WHERE user_id = ?",
        (user_id,),
    )
    existing_row = await cursor.fetchone()

    # Determine timezone and language values
    if existing_row is None:
        # New record: use provided values or defaults
        timezone_value = settings_update.timezone if settings_update.timezone is not None else "UTC"
        language_value = settings_update.language if settings_update.language is not None else "en"
        created_at = datetime.now(timezone.utc).isoformat()
    else:
        # Existing record: use provided values or keep existing
        timezone_value = settings_update.timezone if settings_update.timezone is not None else existing_row["timezone"]
        language_value = settings_update.language if settings_update.language is not None else existing_row["language"]
        created_at = existing_row["created_at"]

    # Always update updated_at
    updated_at = datetime.now(timezone.utc).isoformat()

    # Use INSERT OR REPLACE to upsert
    await db.execute(
        """
        INSERT OR REPLACE INTO user_settings (
            user_id, timezone, language, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (user_id, timezone_value, language_value, created_at, updated_at),
    )
    await db.commit()

    # Log audit
    await log_audit(db, "user_settings", str(user_id), "updated", f"user:{user_id}")

    # Fetch and return the updated settings
    cursor = await db.execute(
        "SELECT * FROM user_settings WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()

    return UserSettingsResponse(
        user_id=row["user_id"],
        timezone=row["timezone"],
        language=row["language"],
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )
