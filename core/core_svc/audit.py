"""Audit logging helper for tracking system state changes."""

import json
import aiosqlite


async def log_audit(
    db: aiosqlite.Connection,
    entity_type: str,    # e.g., "memory", "task", "reminder", "event", "llm_job"
    entity_id: str,      # UUID of the entity
    action: str,         # e.g., "created", "updated", "deleted", "fired", "expired"
    actor: str,          # e.g., "user:123456", "system:scheduler", "system:llm_worker"
    detail: dict | None = None  # optional JSON-serializable context
) -> None:
    """
    Log an audit entry for a state change in the system.

    Args:
        db: Database connection
        entity_type: Type of entity (e.g., "memory", "task", "reminder")
        entity_id: UUID of the entity
        action: Action performed (e.g., "created", "updated", "deleted")
        actor: Who performed the action (e.g., "user:123456", "system:scheduler")
        detail: Optional JSON-serializable context dictionary
    """
    # Serialize detail to JSON string if provided, else None
    detail_json = json.dumps(detail) if detail is not None else None

    # Insert audit log entry
    await db.execute(
        "INSERT INTO audit_log (entity_type, entity_id, action, actor, detail) VALUES (?, ?, ?, ?, ?)",
        (entity_type, entity_id, action, actor, detail_json)
    )

    # Commit the transaction
    await db.commit()
