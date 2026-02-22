"""Users router — upsert Telegram users on first contact."""

import logging

import aiosqlite
from fastapi import APIRouter, Depends, status

from core_svc.database import get_db
from shared_lib.schemas import UserResponse, UserUpsert

logger = logging.getLogger(__name__)

router = APIRouter(tags=["users"])


@router.post("", response_model=UserResponse, status_code=status.HTTP_200_OK)
async def upsert_user(
    user: UserUpsert,
    db: aiosqlite.Connection = Depends(get_db),
) -> UserResponse:
    """Insert the user if they don't exist yet; otherwise do nothing."""
    await db.execute(
        """
        INSERT OR IGNORE INTO users (telegram_user_id, display_name, is_allowed)
        VALUES (?, ?, 1)
        """,
        (user.telegram_user_id, user.display_name),
    )
    await db.execute(
        "INSERT OR IGNORE INTO user_settings (user_id) VALUES (?)",
        (user.telegram_user_id,),
    )
    await db.commit()

    cursor = await db.execute(
        "SELECT telegram_user_id, display_name, is_allowed, created_at FROM users WHERE telegram_user_id = ?",
        (user.telegram_user_id,),
    )
    row = await cursor.fetchone()
    return UserResponse(
        telegram_user_id=row[0],
        display_name=row[1],
        is_allowed=bool(row[2]),
        created_at=row[3],
    )
