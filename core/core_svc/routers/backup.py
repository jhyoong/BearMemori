"""Backup router for read-only access to backup job status."""

import logging

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException

from core_svc.database import get_db
from core_svc.utils import parse_db_datetime
from shared_lib.schemas import BackupStatus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["backup"])


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
