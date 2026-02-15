"""Audit router for read-only access to audit logs."""

import json
import logging
from datetime import datetime

import aiosqlite
from fastapi import APIRouter, Depends

from core.database import get_db
from shared.schemas import AuditLogEntry
from shared.enums import EntityType, AuditAction

logger = logging.getLogger(__name__)

router = APIRouter(tags=["audit"])


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


def parse_actor_to_user_id(actor: str) -> int:
    """
    Parse actor string to extract user_id.

    Expected formats:
    - "user:123456" -> 123456
    - "system:scheduler" -> 0 (system user)
    - "system:llm_worker" -> 0 (system user)
    """
    if actor.startswith("user:"):
        try:
            return int(actor.split(":", 1)[1])
        except (ValueError, IndexError):
            logger.warning(f"Failed to parse user_id from actor: {actor}")
            return 0
    elif actor.startswith("system"):
        return 0
    else:
        logger.warning(f"Unknown actor format: {actor}")
        return 0


@router.get("", response_model=list[AuditLogEntry])
async def get_audit_logs(
    entity_type: EntityType | None = None,
    entity_id: str | None = None,
    action: AuditAction | None = None,
    actor: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: aiosqlite.Connection = Depends(get_db),
) -> list[AuditLogEntry]:
    """
    Fetch audit log entries with optional filters.

    Query parameters:
    - entity_type: Filter by entity type (memory, task, reminder, event, llm_job)
    - entity_id: Filter by specific entity ID
    - action: Filter by action type (created, updated, deleted, etc.)
    - actor: Filter by actor (e.g., "user:123456", "system:scheduler")
    - limit: Maximum number of entries to return (default 100, max 1000)
    - offset: Number of entries to skip (default 0)

    Returns:
    - List of audit log entries, ordered by created_at DESC (newest first)
    """
    # Build query with optional WHERE clauses
    query = "SELECT * FROM audit_log"
    conditions = []
    params = []

    if entity_type is not None:
        conditions.append("entity_type = ?")
        params.append(entity_type.value)

    if entity_id is not None:
        conditions.append("entity_id = ?")
        params.append(entity_id)

    if action is not None:
        conditions.append("action = ?")
        params.append(action.value)

    if actor is not None:
        conditions.append("actor = ?")
        params.append(actor)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    # Add ORDER BY and pagination
    # Use id DESC as secondary sort for deterministic ordering when timestamps are identical
    query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    # Execute query
    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()

    # Parse rows into AuditLogEntry objects
    result = []
    for row in rows:
        # Parse detail from JSON string to dict
        detail = None
        if row["detail"]:
            try:
                detail = json.loads(row["detail"])
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse detail JSON for audit log {row['id']}: {row['detail']}")
                detail = None

        # Parse actor to user_id
        user_id = parse_actor_to_user_id(row["actor"])

        # Parse entity_type and action to enum
        try:
            entity_type_enum = EntityType(row["entity_type"])
        except ValueError:
            logger.warning(f"Unknown entity_type: {row['entity_type']}")
            entity_type_enum = EntityType.memory  # Default fallback

        try:
            action_enum = AuditAction(row["action"])
        except ValueError:
            logger.warning(f"Unknown action: {row['action']}")
            action_enum = AuditAction.updated  # Default fallback

        result.append(
            AuditLogEntry(
                id=str(row["id"]),
                user_id=user_id,
                entity_type=entity_type_enum,
                entity_id=row["entity_id"],
                action=action_enum,
                detail=detail,
                created_at=parse_db_datetime(row["created_at"]),
            )
        )

    return result
