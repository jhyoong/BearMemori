"""LLM jobs router for managing background LLM processing tasks."""

import json
import logging
import uuid
from datetime import datetime, timezone

import aiosqlite
from fastapi import APIRouter, Depends, HTTPException, Request, status

from core_svc.audit import log_audit
from core_svc.database import get_db
from core_svc.utils import parse_db_datetime
from shared_lib.redis_streams import (
    STREAM_LLM_EMAIL_EXTRACT,
    STREAM_LLM_FOLLOWUP,
    STREAM_LLM_IMAGE_TAG,
    STREAM_LLM_INTENT,
    STREAM_LLM_TASK_MATCH,
    publish,
)
from shared_lib.schemas import LLMJobCreate, LLMJobResponse, LLMJobUpdate

logger = logging.getLogger(__name__)

router = APIRouter(tags=["llm_jobs"])

JOB_TYPE_TO_STREAM: dict[str, str] = {
    "image_tag": STREAM_LLM_IMAGE_TAG,
    "intent_classify": STREAM_LLM_INTENT,
    "followup": STREAM_LLM_FOLLOWUP,
    "task_match": STREAM_LLM_TASK_MATCH,
    "email_extract": STREAM_LLM_EMAIL_EXTRACT,
}


@router.post("", response_model=LLMJobResponse, status_code=status.HTTP_201_CREATED)
async def create_llm_job(
    job: LLMJobCreate,
    request: Request,
    db: aiosqlite.Connection = Depends(get_db),
) -> LLMJobResponse:
    """
    Create a new LLM job.

    - Generate UUID
    - Insert into llm_jobs table with status = "queued"
    - Call log_audit() to log the creation
    - Return: LLMJobResponse
    """
    # Generate UUID for id
    job_id = str(uuid.uuid4())

    # Serialize payload to JSON
    payload_json = json.dumps(job.payload)

    # Insert into llm_jobs table
    await db.execute(
        """
        INSERT INTO llm_jobs (id, job_type, payload, user_id, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (job_id, job.job_type, payload_json, job.user_id, "queued"),
    )
    await db.commit()

    # Determine actor for audit log
    actor = f"user:{job.user_id}" if job.user_id is not None else "system:api"

    # Log audit
    await log_audit(db, "llm_job", job_id, "created", actor)

    # Publish to Redis stream for LLM Worker to consume
    stream = JOB_TYPE_TO_STREAM.get(job.job_type)
    redis_client = getattr(request.app.state, "redis", None)
    if stream and redis_client:
        await publish(
            redis_client,
            stream,
            {
                "job_id": job_id,
                "job_type": job.job_type,
                "payload": job.payload,
                "user_id": job.user_id,
            },
        )

    # Fetch and return the created job
    cursor = await db.execute(
        "SELECT * FROM llm_jobs WHERE id = ?",
        (job_id,),
    )
    row = await cursor.fetchone()

    return LLMJobResponse(
        id=row["id"],
        job_type=row["job_type"],
        payload=json.loads(row["payload"]),
        user_id=row["user_id"],
        status=row["status"],
        result=json.loads(row["result"]) if row["result"] else None,
        error_message=row["error_message"],
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )


@router.get("/{id}", response_model=LLMJobResponse)
async def get_llm_job(
    id: str,
    db: aiosqlite.Connection = Depends(get_db),
) -> LLMJobResponse:
    """
    Get an LLM job by ID.

    - Fetch job by ID
    - If not found: return 404
    - Return: LLMJobResponse
    """
    # Fetch job by ID
    cursor = await db.execute(
        "SELECT * FROM llm_jobs WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="LLM job not found")

    return LLMJobResponse(
        id=row["id"],
        job_type=row["job_type"],
        payload=json.loads(row["payload"]),
        user_id=row["user_id"],
        status=row["status"],
        result=json.loads(row["result"]) if row["result"] else None,
        error_message=row["error_message"],
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )


@router.patch("/{id}", response_model=LLMJobResponse)
async def update_llm_job(
    id: str,
    job_update: LLMJobUpdate,
    db: aiosqlite.Connection = Depends(get_db),
) -> LLMJobResponse:
    """
    Update an LLM job by ID.

    - Fetch existing job; 404 if not found
    - Update provided fields
    - Always update updated_at = now
    - Call log_audit() to log the update
    - Return: LLMJobResponse
    """
    # Fetch existing job
    cursor = await db.execute(
        "SELECT * FROM llm_jobs WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="LLM job not found")

    # Build UPDATE query for provided fields
    update_fields = []
    update_values = []

    if job_update.status is not None:
        update_fields.append("status = ?")
        update_values.append(job_update.status)

    if job_update.result is not None:
        update_fields.append("result = ?")
        update_values.append(json.dumps(job_update.result))

    if job_update.error_message is not None:
        update_fields.append("error_message = ?")
        update_values.append(job_update.error_message)

    # Always update updated_at
    update_fields.append("updated_at = ?")
    updated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    update_values.append(updated_at)

    # Add id to values for WHERE clause
    update_values.append(id)

    # Execute update
    if update_fields:
        sql = f"UPDATE llm_jobs SET {', '.join(update_fields)} WHERE id = ?"
        await db.execute(sql, update_values)
        await db.commit()

    # Log audit
    await log_audit(db, "llm_job", id, "updated", "system:llm_worker")

    # Fetch and return updated job
    cursor = await db.execute(
        "SELECT * FROM llm_jobs WHERE id = ?",
        (id,),
    )
    row = await cursor.fetchone()

    return LLMJobResponse(
        id=row["id"],
        job_type=row["job_type"],
        payload=json.loads(row["payload"]),
        user_id=row["user_id"],
        status=row["status"],
        result=json.loads(row["result"]) if row["result"] else None,
        error_message=row["error_message"],
        created_at=parse_db_datetime(row["created_at"]),
        updated_at=parse_db_datetime(row["updated_at"]),
    )


@router.get("", response_model=list[LLMJobResponse])
async def get_llm_jobs(
    status: str | None = None,
    job_type: str | None = None,
    user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[LLMJobResponse]:
    """
    Get LLM jobs with optional filters.

    Query params:
    - status (optional): Filter by status
    - job_type (optional): Filter by job type
    - user_id (optional): Filter by user ID
    - limit (default 50): Maximum number of results
    - offset (default 0): Number of results to skip

    Default sort: ORDER BY created_at DESC
    Return: list[LLMJobResponse]
    """
    # Build WHERE clauses
    where_clauses = []
    query_params = []

    if status is not None:
        where_clauses.append("status = ?")
        query_params.append(status)

    if job_type is not None:
        where_clauses.append("job_type = ?")
        query_params.append(job_type)

    if user_id is not None:
        where_clauses.append("user_id = ?")
        query_params.append(user_id)

    # Build query
    query = "SELECT * FROM llm_jobs"
    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)
    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    query_params.extend([limit, offset])

    # Execute query
    cursor = await db.execute(query, query_params)
    rows = await cursor.fetchall()

    # Convert to LLMJobResponse objects
    jobs = [
        LLMJobResponse(
            id=row["id"],
            job_type=row["job_type"],
            payload=json.loads(row["payload"]),
            user_id=row["user_id"],
            status=row["status"],
            result=json.loads(row["result"]) if row["result"] else None,
            error_message=row["error_message"],
            created_at=parse_db_datetime(row["created_at"]),
            updated_at=parse_db_datetime(row["updated_at"]),
        )
        for row in rows
    ]

    return jobs
