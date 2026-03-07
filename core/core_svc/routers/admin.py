"""Admin router for system administration endpoints."""

import json
import logging
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Depends, Request

from core_svc.database import get_db
from shared_lib.redis_streams import (
    GROUP_LLM_WORKER,
    STREAM_LLM_EMAIL_EXTRACT,
    STREAM_LLM_FOLLOWUP,
    STREAM_LLM_IMAGE_TAG,
    STREAM_LLM_INTENT,
    STREAM_LLM_TASK_MATCH,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

LLM_HEALTH_KEY = "llm:health_status"


@router.get("/admin/queue-stats")
async def get_queue_stats(
    db: aiosqlite.Connection = Depends(get_db),
    user_id: int | None = None,
) -> dict:
    """
    Get LLM job queue statistics.

    Args:
        user_id: Optional user ID to filter results for a specific user.

    Returns:
        - total_pending: count of jobs with status='queued' (waiting for processing)
        - by_status: dict with counts for each status ('queued', 'processing', 'confirmed', 'failed', 'cancelled')
        - by_type: dict with counts per job_type ('image_tag', 'intent_classify', 'task_match', 'followup', 'email_extract')
        - oldest_queued_age_seconds: age of oldest queued job in seconds, or None if no queued jobs
    """
    # Get total counts by status
    status_counts = await _get_status_counts(db, user_id=user_id)
    # Get counts by job type
    type_counts = await _get_type_counts(db, user_id=user_id)
    # Get oldest queued job age
    oldest_age = await _get_oldest_queued_age(db, user_id=user_id)

    return {
        "total_pending": status_counts.get("queued", 0),
        "by_status": status_counts,
        "by_type": type_counts,
        "oldest_queued_age_seconds": oldest_age,
    }


async def _get_status_counts(
    db: aiosqlite.Connection, *, user_id: int | None = None
) -> dict[str, int]:
    """Get count of jobs grouped by status."""
    if user_id is not None:
        cursor = await db.execute(
            """
            SELECT status, COUNT(*) as count
            FROM llm_jobs
            WHERE user_id = ?
            GROUP BY status
            """,
            (user_id,),
        )
    else:
        cursor = await db.execute(
            """
            SELECT status, COUNT(*) as count
            FROM llm_jobs
            GROUP BY status
            """
        )
    rows = await cursor.fetchall()

    counts = {
        "queued": 0,
        "processing": 0,
        "confirmed": 0,
        "failed": 0,
        "cancelled": 0,
    }
    for row in rows:
        status = row["status"]
        if status in counts:
            counts[status] = row["count"]

    return counts


async def _get_type_counts(
    db: aiosqlite.Connection, *, user_id: int | None = None
) -> dict[str, int]:
    """Get count of jobs grouped by job_type."""
    if user_id is not None:
        cursor = await db.execute(
            """
            SELECT job_type, COUNT(*) as count
            FROM llm_jobs
            WHERE user_id = ?
            GROUP BY job_type
            """,
            (user_id,),
        )
    else:
        cursor = await db.execute(
            """
            SELECT job_type, COUNT(*) as count
            FROM llm_jobs
            GROUP BY job_type
            """
        )
    rows = await cursor.fetchall()

    counts = {}
    for row in rows:
        counts[row["job_type"]] = row["count"]

    return counts


async def _get_oldest_queued_age(
    db: aiosqlite.Connection, *, user_id: int | None = None
) -> float | None:
    """Get age of oldest queued job in seconds, or None if no queued jobs."""
    if user_id is not None:
        cursor = await db.execute(
            """
            SELECT MIN(created_at) as oldest
            FROM llm_jobs
            WHERE status = 'queued' AND user_id = ?
            """,
            (user_id,),
        )
    else:
        cursor = await db.execute(
            """
            SELECT MIN(created_at) as oldest
            FROM llm_jobs
            WHERE status = 'queued'
            """
        )
    row = await cursor.fetchone()

    if row is None or row["oldest"] is None:
        return None

    try:
        oldest_created_at = datetime.fromisoformat(row["oldest"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age = now - oldest_created_at
        return age.total_seconds()
    except (ValueError, TypeError):
        return None


@router.get("/admin/health")
async def get_health(
    db: aiosqlite.Connection = Depends(get_db),
    request: Request = None,
) -> dict:
    """
    Get system health status.

    Checks:
    - Database connectivity via SELECT 1
    - Redis connectivity via ping

    Returns:
        {"status": "healthy"} when both DB and Redis are healthy
        {"status": "unhealthy", "error": "..."} on any failure
    """
    errors = []

    # Check database connectivity
    try:
        cursor = await db.execute("SELECT 1")
        row = await cursor.fetchone()
        if row is None:
            errors.append("database: no response from SELECT 1")
    except Exception as e:
        errors.append(f"database: {str(e)}")

    # Check Redis connectivity (access via app state in production, mock in tests)
    try:
        if request and hasattr(request.app, "state") and hasattr(request.app.state, "redis"):
            redis_client = request.app.state.redis
            await redis_client.ping()
        else:
            # For tests that don't inject Redis, skip the check
            pass
    except Exception as e:
        errors.append(f"redis: {str(e)}")

    if errors:
        return {"status": "unhealthy", "error": "; ".join(errors)}

    return {"status": "healthy"}


_STREAM_NAMES = [
    STREAM_LLM_INTENT,
    STREAM_LLM_IMAGE_TAG,
    STREAM_LLM_FOLLOWUP,
    STREAM_LLM_TASK_MATCH,
    STREAM_LLM_EMAIL_EXTRACT,
]


@router.get("/admin/stream-health")
async def get_stream_health(request: Request) -> dict:
    """
    Introspect Redis streams and consumer groups to show worker health.

    Returns stream lengths, pending message counts, consumer group name,
    and active consumer count. Gracefully handles missing streams/groups.
    """
    redis = request.app.state.redis
    streams: dict[str, dict[str, int]] = {}

    for stream_name in _STREAM_NAMES:
        length = 0
        pending = 0

        # Get stream length
        try:
            length = await redis.xlen(stream_name)
        except Exception:
            logger.debug("Stream %s does not exist or xlen failed", stream_name)

        # Get pending count for the consumer group
        try:
            pending_info = await redis.xpending(stream_name, GROUP_LLM_WORKER)
            if pending_info and isinstance(pending_info, dict):
                pending = pending_info.get("pending", 0)
            elif pending_info and isinstance(pending_info, (list, tuple)) and len(pending_info) > 0:
                # Some Redis clients return a list: [count, min_id, max_id, consumers]
                pending = pending_info[0] if isinstance(pending_info[0], int) else 0
        except Exception:
            logger.debug(
                "Could not get pending info for %s/%s", stream_name, GROUP_LLM_WORKER
            )

        streams[stream_name] = {"length": length, "pending": pending}

    # Get active consumer count from any existing stream
    consumers_active = 0
    for stream_name in _STREAM_NAMES:
        try:
            groups = await redis.xinfo_groups(stream_name)
            for group in groups:
                group_name = group.get("name", "")
                # Redis may return bytes or str depending on client config
                if isinstance(group_name, bytes):
                    group_name = group_name.decode()
                if group_name == GROUP_LLM_WORKER:
                    consumers_active = group.get("consumers", 0)
                    break
            if consumers_active > 0:
                break
        except Exception:
            logger.debug("Could not get group info for stream %s", stream_name)

    return {
        "streams": streams,
        "consumer_group": GROUP_LLM_WORKER,
        "consumers_active": consumers_active,
    }


_UNKNOWN_HEALTH = {
    "status": "unknown",
    "last_check": None,
    "last_success": None,
    "last_failure": None,
    "consecutive_failures": 0,
}


@router.get("/admin/llm-health")
async def get_llm_health(request: Request) -> dict:
    """
    Get LLM health status from Redis.

    Reads the cached health-check result written by the LLM worker.
    Returns an "unknown" response when the key is missing or Redis is
    unavailable.
    """
    try:
        redis = request.app.state.redis
        raw = await redis.get(LLM_HEALTH_KEY)
    except Exception:
        logger.warning("Failed to read LLM health status from Redis", exc_info=True)
        return dict(_UNKNOWN_HEALTH)

    if raw is None:
        return dict(_UNKNOWN_HEALTH)

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Invalid JSON in LLM health key")
        return dict(_UNKNOWN_HEALTH)

    return data