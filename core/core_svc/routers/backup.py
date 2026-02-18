"""Backup router for read-only access to backup job status."""

import logging
from datetime import datetime

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from core_svc.database import get_db
from shared_lib.schemas import BackupStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backup"])


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


@router.get("/status/{user_id}", response_model=BackupStatus)
async def get_backup_status(
    user_id: int,
    db: aiosqlite.Connection = Depends(get_db),
) -> BackupStatus:
    """
    Fetch the most recent backup status for the given user.

    Query:
    - SELECT * FROM backup_jobs WHERE user_id = ? ORDER BY started_at DESC LIMIT 1

    Returns:
    - BackupStatus with the most recent backup job details

    Raises:
    - 404 if no backup job found for the user
    """
    # Fetch the most recent backup job for the user
    cursor = await db.execute(
        "SELECT * FROM backup_jobs WHERE user_id = ? ORDER BY started_at DESC LIMIT 1",
        (user_id,),
    )
    row = await cursor.fetchone()

    # If not found, return 404
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No backup job found for user {user_id}",
        )

    # Return the backup status
    return BackupStatus(
        backup_id=row["backup_id"],
        user_id=row["user_id"],
        started_at=parse_db_datetime(row["started_at"]),
        completed_at=parse_db_datetime(row["completed_at"]),
        status=row["status"],
        file_path=row["file_path"],
        error_message=row["error_message"],
    )
